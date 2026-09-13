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
- [x] Local history (localStorage, confirm-before-clear)
- [x] Chat panel wired to `POST /chat` (offline notice when backend down)
- [x] Reduced-motion + keyboard tabs + 44px targets

## Backend — owner: you

- [x] `api.py`: CORS, `/health`, offline `/verify`, `/parse` (key-gated 503)
- [x] `POST /chat` (assistant added scaffold — verify prompt + grounding)
- [ ] Set `GOOGLE_API_KEY` in the deploy environment (never commit it)
- [ ] Deploy API (Dockerfile exists — add uvicorn CMD or extend it)
- [ ] Serve the HTML (any static host) with `API` base URL configured
- [ ] Decide: retire `prescription.py` / Streamlit from requirements,
      or keep as internal tool

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
