"""RxCare backend — FastAPI REST API for prescription parsing + offline verify.

Run:  uvicorn api:app --host 127.0.0.1 --port 8000
Docs: http://127.0.0.1:8000/docs

Endpoints:
  GET  /health          -> status + dependency check (no API key needed)
  GET  /verify?name=X   -> offline Indian-DB check for one medicine (no key)
  POST /parse           -> multipart file(s) -> structured JSON + verification
                           (needs GOOGLE_API_KEY + langchain_google_genai)
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path
from typing import List
import tempfile, os, shutil

app = FastAPI(title="RxCare API", version="1.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _deps():
    out = {}
    for mod in ("fastapi", "streamlit", "pandas", "PIL",
                "langchain_core", "langchain_google_genai"):
        try:
            __import__(mod)
            out[mod] = True
        except Exception:
            out[mod] = False
    out["google_api_key"] = bool(os.environ.get("GOOGLE_API_KEY"))
    return out


@app.get("/")
def root():
    # Serve the website UI at / if it exists — otherwise JSON (backward compat)
    html = Path(__file__).parent / "rx-prescription-app.html"
    if html.exists():
        return FileResponse(str(html), media_type="text/html")
    return {"ok": True, "endpoints": ["/health", "/verify?name=Dolo 650", "/parse", "/chat"]}


@app.get("/app")
def app_page():
    html = Path(__file__).parent / "rx-prescription-app.html"
    if html.exists():
        return FileResponse(str(html), media_type="text/html")
    raise HTTPException(status_code=404, detail="rx-prescription-app.html not found")


@app.get("/health")
def health():
    deps = _deps()
    vision = deps.get("langchain_google_genai") and deps.get("google_api_key")
    return {"ok": True, "deps": deps, "vision_ready": bool(vision)}


@app.get("/verify")
def verify(name: str):
    """Offline single-medicine check — no API key, no internet."""
    from indian_db import verify_medicine, find_alternatives
    check = verify_medicine(name)
    alts = find_alternatives(check.get("composition", ""), exclude=check.get("match", ""), n=3)
    return {"check": check, "alternatives": alts}


@app.post("/chat")
async def chat(body: dict):
    """Grounded medication Q&A - answers about any drug, not just prescription context."""
    question = (body.get("question") or "").strip()
    context = str(body.get("context") or "")[:3000]
    if not question:
        raise HTTPException(status_code=400, detail="question required")
    if not os.environ.get("GOOGLE_API_KEY"):
        raise HTTPException(status_code=503, detail="GOOGLE_API_KEY not set on server")
    # Enrich with Indian DB lookup for any drug mentioned in question
    db_ctx = ""
    try:
        from indian_db import verify_medicine
        import re
        # extract candidate drug tokens (3+ chars) and bigrams like "Rosidan PD"
        toks = re.findall(r"[A-Za-z]{3,}", question)
        # also try bigrams
        bigrams = [" ".join(toks[i:i+2]) for i in range(len(toks)-1)]
        candidates = toks + bigrams
        seen = set()
        for cand in candidates:
            lc = cand.lower()
            if lc in seen or len(lc) < 3:
                continue
            seen.add(lc)
            try:
                chk = verify_medicine(cand)
                if chk.get("status", "").startswith("Verified"):
                    db_ctx += f"\nDB hit for '{cand}': {chk.get('match')} | {chk.get('composition')} | {chk.get('manufacturer','')} | {chk.get('medicine_desc','')[:400]} | Side effects: {chk.get('side_effects_db','')[:400]}"
                elif "Not found" in chk.get("status","") and len(cand) >= 4:
                    if cand.lower() not in {"what","sideeffect","side","effect","whatis","is","of","the","and","for","with","a","an"}:
                        db_ctx += f"\nDB: '{cand}' not in Indian registry (254k) — may be BD-local or misspelled."
            except Exception:
                pass
            if len(db_ctx) > 1500:
                break
    except Exception:
        pass
    # Direct not-found answer for main drug to avoid hallucination (Sato, Rosidan PD)
    import re as _re2
    m = _re2.search(r"DB: '([^']+)' not in Indian registry", db_ctx)
    if m:
        drug = m.group(1)
        return {"answer": f"{drug} not found in Indian registry (254k brands) — may be a Bangladesh-local brand or misspelling. Please check the strip spelling, manufacturer and QR, and consult a pharmacist. Not medical advice."}
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import HumanMessage
        llm = ChatGoogleGenerativeAI(
            model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            google_api_key=os.environ.get("GOOGLE_API_KEY", ""),
            temperature=0,
        )
        prompt = (
            f"Prescription context (may be empty): {context}\n"
            f"Indian DB lookup for question terms:{db_ctx or ' (no DB hit)'}\n"
            f"Question: {question}\n"
            "Answer helpfully and concisely in plain English. If DB gives side effects/composition, cite them. "
            "If DB says Not found, say so plainly and suggest checking the strip spelling or manufacturer. "
            "Never invent side effects not in DB. Not medical advice — advise see doctor/pharmacist."
        )
        ans = llm.invoke([HumanMessage(content=prompt)]).content
        if isinstance(ans, list):
            ans = " ".join(b.get("text", "") for b in ans if isinstance(b, dict) and b.get("type") == "text")
        return {"answer": ans}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Chat failed: {e}")


@app.post("/parse")
async def parse(files: List[UploadFile] = File(...)):
    try:
        from prescription import (
            get_prescription_informations,
            dedupe_medications,
            normalize_frequency,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Vision stack unavailable: {e}")
    if not os.environ.get("GOOGLE_API_KEY"):
        raise HTTPException(status_code=503, detail="GOOGLE_API_KEY not set on server")
    from indian_db import verify_medicine
    tmpdir = tempfile.mkdtemp(prefix="rx_api_")
    try:
        paths = []
        for f in files:
            p = os.path.join(tmpdir, f.filename or "upload.png")
            with open(p, "wb") as out:
                out.write(await f.read())
            paths.append(p)
        res = get_prescription_informations(paths)
        for m in res.get("medications", []):
            m["frequency"] = normalize_frequency(m.get("frequency", ""))
        res["medications"] = dedupe_medications(res.get("medications"))
        checks = [verify_medicine(m.get("name", "")) for m in res.get("medications", [])]
        return {"result": res, "verification": checks}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
