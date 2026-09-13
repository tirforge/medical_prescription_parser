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
    """Grounded medication Q&A scoped to a parse result. Needs GOOGLE_API_KEY."""
    question = (body.get("question") or "").strip()
    context = str(body.get("context") or "")[:3000]
    if not question:
        raise HTTPException(status_code=400, detail="question required")
    if not os.environ.get("GOOGLE_API_KEY"):
        raise HTTPException(status_code=503, detail="GOOGLE_API_KEY not set on server")
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import HumanMessage
        llm = ChatGoogleGenerativeAI(
            model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            google_api_key=os.environ.get("GOOGLE_API_KEY", ""),
            temperature=0,
        )
        ans = llm.invoke([HumanMessage(content=(
            f"Context prescription JSON: {context}\nQuestion: {question}\n"
            "Answer concisely, not medical advice, cite composition if relevant."
        ))]).content
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
