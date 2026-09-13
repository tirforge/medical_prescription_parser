# Migration: Streamlit UI → Website UI + FastAPI backend

Goal: retire the Streamlit UI (`prescription.py`) as the user-facing product and
ship `rx-prescription-app.html` + `medical_prescription_parser/api.py` instead.
The HTML page is the full product UI; FastAPI is the only backend.

## Architecture (target)

```
browser: rx-prescription-app.html (static, no build step)
    │  GET /health · POST /parse · GET /verify · POST /chat
    ▼
api:  api.py (uvicorn :8000, GOOGLE_API_KEY in env)
    │  vision (Gemini) · indian_db (offline CSV) · rxnorm · openFDA
    ▼
data: indian_medicine_db.csv (43 MB, server-side only — never ships to browser)
```

## Frontend — done (assistant)

- [x] Upload-gated results (nothing renders before files are chosen)
- [x] Real file picker + drag-and-drop + file chips
- [x] Staged loader (progress %, skeleton, aria-busy, input locked)
- [x] Live `POST /parse` render with demo-pattern fallback
- [x] Role toggle, A−/A/A+ text scaling, dark mode (persisted)
- [x] Copy / CSV / TXT exports bound to live rows
- [x] One-click sample scan, client-side risk banner, print stylesheet
- [x] Local history (localStorage, confirm-before-clear)
- [x] Chat panel wired to `POST /chat` (offline notice when backend down)
- [x] Reduced-motion + keyboard tabs + 44px targets

## Backend — owner: you

- [x] `api.py`: CORS, `/health`, offline `/verify`, `/parse` (key-gated 503) — fixed missing `@app.post("/parse")` 2026-09-13
- [x] `POST /chat` (assistant added scaffold — verify prompt + grounding)
- [x] `Dockerfile` now runs `uvicorn api:app` on 8000 (Streamlit kept on 8501 as fallback)
- [x] `GOOGLE_API_KEY` via env only — no input box in website or Streamlit (removed `st.text_input` 2026-09-13)
- [x] Serve the HTML — `api.py` now serves `rx-prescription-app.html` at `GET /` and `/app` (relative `API = ''` when served via http, `http://127.0.0.1:8000` for `file://`)
- [x] `prescription.py` marked deprecated (banner + README) — keep until website parity accepted, Streamlit not primary

## Run locally (both)

```powershell
# terminal 1 — backend (key via env, never in code)
$env:GOOGLE_API_KEY = '<your-key>'
python -m uvicorn api:app --host 127.0.0.1 --port 8000  # in this folder

# browser — frontend (static file, no server needed)
# open rx-prescription-app.html → status pill reads "Backend online"
```

Without the backend (or without a key) the page runs its honest demo
pattern — uploads still preview, results are labelled samples.

## Open questions

- Tabs vs multipage navigation (see `ui_plan.md` Phase 3).
- Real prescription imagery blocked on PHI consent — placeholder stands.
- Deployed API base URL + key story for hosted use.
- `prescription.py` retirement date (keep until website history/chat parity
  is accepted).
