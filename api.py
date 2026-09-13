"""FastAPI REST API for prescription parsing.
POST /parse with multipart file(s) -> structured JSON + verification.

Run: uvicorn api:app --host 0.0.0.0 --port 8000
"""
from fastapi import FastAPI, UploadFile, File
from typing import List
import tempfile, os, shutil, json
from prescription import get_prescription_informations, dedupe_medications, normalize_frequency
from indian_db import verify_medicine

app = FastAPI(title="Rx Parser API", version="1.0")

@app.get("/")
def root(): return {"ok": True, "post": "/parse"}

@app.post("/parse")
async def parse(files: List[UploadFile] = File(...)):
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
            m["frequency"] = normalize_frequency(m.get("frequency",""))
        res["medications"] = dedupe_medications(res.get("medications"))
        checks = [verify_medicine(m.get("name","")) for m in res.get("medications",[])]
        return {"result": res, "verification": checks}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
