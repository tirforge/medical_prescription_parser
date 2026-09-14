"""RxCare backend — FastAPI REST API for prescription parsing + offline verify.

Run:  uvicorn api:app --host 127.0.0.1 --port 8000
Docs: http://127.0.0.1:8000/docs

Endpoints:
  GET  /health          -> status + dependency check (no API key needed)
  GET  /verify?name=X   -> offline Indian-DB check for one medicine (no key)
  POST /parse           -> multipart file(s) -> structured JSON + verification
                           (needs GOOGLE_API_KEY + langchain_google_genai)
  POST /correct         -> JSON {name} -> re-verify a hand-corrected spelling (no key)
  POST /strip           -> multipart strip/box photo -> brand read + verification
                           (needs GOOGLE_API_KEY)
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
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


MODEL_FALLBACK_CHAIN = [
    "gemini-3.6-flash",
    "gemini-3.6-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash",
    "gemini-3.1-flash-lite",
    "gemma-4-26b-a4b-it",
    "gemma-4-31b-it",
    "gemini-2.5-flash-lite",
]

def _last_good():
    m = os.environ.get("_LAST_GEMINI_MODEL", "").strip()
    if m:
        return m
    try:
        return open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_model.json")).read().strip()
    except Exception:
        return ""

def _chain(primary: str = "") -> list[str]:
    p = (primary or os.environ.get("GEMINI_MODEL", "") or "").strip()
    last = _last_good()
    seen, out = set(), []
    for m in ([last] if last else []) + ([p] if p else []) + MODEL_FALLBACK_CHAIN:
        if m and m not in seen:
            seen.add(m); out.append(m)
    return out

def _clean_chat_answer(ans: str) -> str:
    """Strip markdown clutter the LLM adds (bullets, **bold**, *italic* disclaimers)
    since the frontend renders the answer as plain text (textContent)."""
    import re
    s = (ans or "").strip()
    # bullet markers at line start (* / - / •) -> plain line
    s = re.sub(r"^\s*[\*\-•]\s+", "", s, flags=re.M)
    # **bold** -> bold (keep inner text)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s, flags=re.S)
    # any remaining stray asterisks (e.g. *Disclaimer...*)
    s = s.replace("*", "")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

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
    out["gemini_model"] = os.environ.get("GEMINI_MODEL", MODEL_FALLBACK_CHAIN[0])
    out["fallback_chain"] = _chain()
    out["last_model"] = os.environ.get("_LAST_GEMINI_MODEL", "")
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
    mode = (body.get("mode") or "patient").lower()  # patient | doctor
    if not question:
        raise HTTPException(status_code=400, detail="question required")
    if not os.environ.get("GOOGLE_API_KEY"):
        raise HTTPException(status_code=503, detail="GOOGLE_API_KEY not set on server")
    # Heavy work (Indian-DB enrich + LLM) runs in a threadpool so the event
    # loop stays responsive — /health and other requests never block on it.
    return await run_in_threadpool(_chat_worker, question, context, mode)


def _chat_worker(question: str, context: str, mode: str) -> dict:
    # Enrich with Indian DB lookup for any drug mentioned in question
    db_ctx = ""
    best_chk = None
    try:
        from indian_db import verify_medicine
        import re
        # extract candidate drug tokens (allow numbers for dosage like 650) and bigrams like "Dolo 650", "Rosidan PD"
        toks = re.findall(r"[A-Za-z0-9]{2,}", question)
        # also try bigrams
        bigrams = [" ".join(toks[i:i+2]) for i in range(len(toks)-1)]
        candidates = toks + bigrams
        stop = {"what","are","side","effects","effect","sideeffect","sideeffects","whatis","is","of","the","and","for","with","a","an","tell","me","about","show","details","info","information","medicine","drug","tablet","capsule","syrup","are","whats","what's"}
        seen = set()
        for cand in candidates:
            lc = cand.lower()
            if lc in seen or len(lc) < 3 or lc in stop:
                continue
            if " " not in lc and lc in stop:
                continue
            # skip bigrams containing stopwords only
            words = lc.split()
            if words and all(w in stop for w in words):
                continue
            seen.add(lc)
            try:
                chk = verify_medicine(cand)
                # guard false positives: e.g. "side" -> Slide Suspension; require at least 4 chars and not pure stopword fuzzy
                if chk.get("status", "").startswith("Verified") and len(cand) < 4:
                    continue
                if chk.get("status", "").startswith("Verified"):
                    if best_chk is None or (not best_chk.get("side_effects_db") and chk.get("side_effects_db")):
                        best_chk = chk
                    db_ctx += f"\nDB hit for '{cand}': {chk.get('match')} | {chk.get('composition')} | {chk.get('manufacturer','')} | {chk.get('pack_size','')} | {chk.get('medicine_desc','')[:400]} | Side effects: {chk.get('side_effects_db','')[:400]} | Salt: {chk.get('salt_composition','')[:200]}"
                elif "Not found" in chk.get("status","") and len(cand) >= 4:
                    # skip common phrases like "what sideeffect" — only real drug-like tokens
                    words = cand.lower().split()
                    if any(w in {"what","sideeffect","side","effect","whatis","is","of","the","and","for","with","a","an"} for w in words):
                        continue
                    db_ctx += f"\nDB: '{cand}' not in Indian registry (254k) — may be misspelled or a local pack; suggest strip-QR check."
            except Exception:
                pass
            if len(db_ctx) > 1800:
                break
        # If best hit has empty side_effects (e.g. "Dolo" -> Drops with no SE), enrich via FDA/openFDA
        if best_chk and not (best_chk.get("side_effects_db") or "").strip():
            try:
                from drug_info import get_drug_safety
                comp = (best_chk.get("composition") or "").split("(")[0].strip().split(",")[0].strip()
                if comp:
                    safety = get_drug_safety(comp)
                    if safety and (safety.get("side_effects") or safety.get("label_text","")[:300]):
                        se = safety.get("side_effects") or safety.get("label_text","")[:400]
                        db_ctx += f"\nFDA label for {comp}: {str(se)[:500]} (use as fallback; registry entry had none)"
            except Exception:
                pass
            # also try stronger hit "Dolo 650" if question was just "Dolo" (same salt, different pack)
            try:
                if "dolo" in question.lower() or (best_chk.get("match","").lower().startswith("dolo")):
                    alt = verify_medicine("Dolo 650")
                    if alt.get("status","").startswith("Verified") and alt.get("side_effects_db"):
                        db_ctx += f"\nRelated pack {alt.get('match')} ({alt.get('composition')}) side effects: {alt.get('side_effects_db')[:300]} — same salt Paracetamol, use with dosage note; primary {best_chk.get('match')} had none listed."
            except Exception:
                pass
    except Exception:
        pass
    # Direct not-found only if no Verified hit (so Dolo 650 still gets normal answer, sato gets not-found)
    if "DB hit for" not in db_ctx:
        import re as _re2
        m = _re2.search(r"DB: '([^']+)' not in Indian registry", db_ctx)
        if m:
            drug = m.group(1)
            return {"answer": _clean_chat_answer(f"{drug} not found in Indian registry (254k brands) — may be a Bangladesh-local brand or misspelling. Please check the strip spelling, manufacturer and QR, and consult a pharmacist. Not medical advice.")}
    # chat with ordered fallback 3.6 -> 3.6-lite -> 3.5 -> 3.5-lite -> 3.1 -> 3.1-lite -> gemma
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage
    role_instruction = (
        "You are answering a clinician. Use precise medical terminology, include salt composition, pack, manufacturer and alternatives when in DB, and cite side effects and interactions exactly as in DB/FDA. Still add disclaimer."
        if mode == "doctor" else
        "Answer helpfully and concisely in plain English for a patient. If DB gives side effects/composition, cite them in simple words."
    )
    prompt = (
        f"Mode: {mode}\n"
        f"Prescription context (may be empty): {context}\n"
        f"Indian DB lookup for question terms:{db_ctx or ' (no DB hit)'}\n"
        f"Question: {question}\n"
        f"{role_instruction} "
        "If DB says Not found, say so plainly and suggest checking the strip spelling or manufacturer. "
        "Never invent side effects not in DB/FDA label. Not medical advice — advise see doctor/pharmacist."
    )
    last_err = None
    from prescription import _make_llm, _remember_last_model
    for model in _chain():
        try:
            llm = _make_llm(model)
            ans = llm.invoke([HumanMessage(content=prompt)]).content
            if isinstance(ans, list):
                ans = " ".join(b.get("text","") for b in ans if isinstance(b, dict) and b.get("type")=="text")
            _remember_last_model(model)
            return {"answer": _clean_chat_answer(ans), "model": model}
        except Exception as e:
            msg = str(e).lower()
            last_err = e
            if any(k in msg for k in ("429","quota","rate","resource_exhausted","404","not found","503","500","502","overloaded","unavailable")):
                continue
            raise HTTPException(status_code=502, detail=f"Chat failed on {model}: {e}")
    raise HTTPException(status_code=502, detail=f"Chat all models exhausted {MODEL_FALLBACK_CHAIN}: {last_err}")


@app.post("/parse")
async def parse(files: List[UploadFile] = File(...)):
    if not os.environ.get("GOOGLE_API_KEY"):
        raise HTTPException(status_code=503, detail="GOOGLE_API_KEY not set on server")
    # Read all uploads quickly (async), then run the heavy parse in a threadpool
    # so other requests (/health, /verify, /chat) never block on it.
    tmpdir = tempfile.mkdtemp(prefix="rx_api_")
    try:
        paths = []
        for f in files:
            data = await f.read()
            fname = f.filename or "upload.png"
            p = os.path.join(tmpdir, fname)
            with open(p, "wb") as out:
                out.write(data)
            if fname.lower().endswith(".pdf"):
                # PDF → image rasterisation happens off the event loop too
                paths.append({"ext": "pdf", "path": p, "tmp": tmpdir})
            else:
                paths.append({"ext": "img", "path": p, "tmp": tmpdir})
        if not paths:
            raise HTTPException(status_code=400, detail="No valid images/PDF pages found")
        return await run_in_threadpool(_parse_worker, paths, tmpdir)
    finally:
        # _parse_worker keeps needed files; original upload dir is cleaned later
        pass


def _parse_worker(paths: list, tmpdir: str) -> dict:
    from indian_db import verify_medicine, find_alternatives
    # expand PDFs to page-images, collect real image paths
    image_paths = []
    for item in paths:
        if item["ext"] == "pdf":
            try:
                from prescription import pdf_to_images as _pdf2img
                with open(item["path"], "rb") as fh:
                    data = fh.read()
                imgs = _pdf2img(data, item["tmp"])
                image_paths.extend(imgs or [item["path"]])
            except Exception:
                image_paths.append(item["path"])
        else:
            image_paths.append(item["path"])
    if not image_paths:
        raise HTTPException(status_code=400, detail="No valid images/PDF pages found")
    from prescription import (
        get_prescription_informations,
        dedupe_medications,
        normalize_frequency,
        _add_confidence,
    )
    try:
        res = get_prescription_informations(image_paths)
    except RuntimeError as e:
        # Quota/network death raises (no guessed fallback) — surface as
        # actionable 503 so the frontend shows a real error instead of
        # invented medicines.
        raise HTTPException(status_code=503, detail=str(e))
    for m in res.get("medications", []):
        m["frequency"] = normalize_frequency(m.get("frequency", ""))
    res["medications"] = dedupe_medications(res.get("medications"))
    checks = []
    for m in res.get("medications", []):
        chk = verify_medicine(m.get("name", ""))
        try:
            alts = find_alternatives(chk.get("composition","") or m.get("name",""), exclude=chk.get("match",""), n=3)
            chk["alternatives"] = alts
        except Exception:
            chk["alternatives"] = []
        try:
            age = res.get("patient_age")
            if isinstance(age, str) and age.isdigit():
                age = int(age)
            if isinstance(age, int) and age < 12:
                dose = (m.get("dosage") or "").lower()
                if any(x in dose for x in ["500 mg","650 mg","1g","1000 mg"]):
                    chk["age_flag"] = f"High adult dose {m.get('dosage')} for age {age} — verify with pediatrician"
        except Exception:
            pass
        checks.append(chk)
    try:
        res = _add_confidence(res, checks)
    except Exception:
        pass
    import shutil as _sh
    _sh.rmtree(tmpdir, ignore_errors=True)
    return {"result": res, "verification": checks}


class CorrectIn(BaseModel):
    name: str = ""


@app.post("/correct")
def correct(body: CorrectIn):
    """Re-verify a hand-corrected spelling (no API key needed).

    Used by the UI under an unverified line: user fixes the spelling or
    pastes the strip brand, we return fresh verification + alternatives.
    """
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    from indian_db import verify_medicine, find_alternatives
    chk = verify_medicine(name)
    try:
        chk["alternatives"] = find_alternatives(
            chk.get("composition", "") or name, exclude=chk.get("match", ""), n=3
        )
    except Exception:
        chk["alternatives"] = []
    return {"verification": chk}


@app.post("/strip")
async def strip_scan(file: UploadFile = File(...)):
    """Read the brand off a strip/box photo, then verify it.

    Needs GOOGLE_API_KEY (one Gemini vision call via read_brand_from_strip).
    """
    if not os.environ.get("GOOGLE_API_KEY"):
        raise HTTPException(status_code=503, detail="GOOGLE_API_KEY not set on server")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    from prescription import read_brand_from_strip
    try:
        brand = await run_in_threadpool(read_brand_from_strip, data)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Strip read failed: {e}")
    if not brand:
        raise HTTPException(status_code=502, detail="Strip brand unreadable — try closer in good light")
    from indian_db import verify_medicine, find_alternatives
    chk = verify_medicine(brand)
    try:
        chk["alternatives"] = find_alternatives(
            chk.get("composition", "") or brand, exclude=chk.get("match", ""), n=3
        )
    except Exception:
        chk["alternatives"] = []
    return {"strip_brand": brand, "verification": chk}
