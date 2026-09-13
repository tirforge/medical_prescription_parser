# RxCare — Prescription Safety 🏥

Upload a handwritten prescription photo → structured data (patient, doctor,
medicines) + Indian registry verification + side effects + interaction screen.
**Primary UI is now `rx-prescription-app.html` + `api.py` (FastAPI)** — fast,
mobile-friendly, no Streamlit chrome. Streamlit (`prescription.py`) is kept as
a deprecated fallback (see `migration.md`).

Built with free-tier vision models (Gemini / Gemma 4).

**Dataset for testing**: [Illegible Medical Prescription Images (Kaggle)](https://www.kaggle.com/datasets/mehaksingal/illegible-medical-prescription-images-dataset)
(see `accuracy_test/` for bundled samples).

## Features

- 📄 **Prescription parsing** — multi-page upload, clipboard paste, or strip photo;
  preocr denoise/deskew runs locally before the vision model reads it
- 🔍 **Scan a Medicine** — type a name or snap a strip for genuine-check signals
  + full data card (composition, manufacturer, pack, side effects)
- ✅ **Indian DB verification** — ~254k brands offline, fuzzy auto-correct,
  salt matching, pack/type details, human-review flags
- 💊 **Side effects + interactions** — openFDA labels in plain English,
  boxed warnings, DailyMed links, one-shot combination screening
- 🌍 **World-registry cross-check** — NIH RxNorm (free, keyless)
- 📋 **Copy results** — one-click text + JSON export
- 🎨 Medical theme (light + dark), sidebar model picker, metrics + staged progress

## Run rule — never use `pkill -f` (hangs)

Use `make` (uses `fuser`/`lsof` on ports, not `pkill -f` scan):

```bash
make run        # api 8000 (uvicorn api:app) — primary website backend
make run-streamlit  # fallback Streamlit 8501 if needed
make stop       # kills 8000+8501 via fuser/lsof/pid, no pkill
make logs       # tail /tmp/uvicorn.log
make health     # curl /health + html check
```

Manual (same, instant):
```bash
fuser -k 8000/tcp 2>/dev/null || lsof -ti:8000 | xargs -r kill -9
```

## Vision models & free quotas (verified 2026-09-13, reset midnight PT)

| Model (default first) | Req/day |
|---|---|
| `gemini-3.5-flash-lite` | 500 |
| `gemma-4-26b-a4b-it` / `gemma-4-31b-it` | 14,400 |
| `gemini-2.5-flash(-lite)` | 20 |

Switch via sidebar, or `GEMINI_MODEL` env var.

## Setup

```bash
git clone <this-repo> && cd medical_prescription_parser
pip install -r requirements.txt   # pinned, tested set
```

API key — any ONE of these (first found wins: sidebar → `keys.py` → `.env` → env):

```bash
cp keys.example.py keys.py   # then set GOOGLE_API_KEY inside
# free key: https://aistudio.google.com/app/apikey
```

## Run (Website — primary)

```bash
GOOGLE_API_KEY=<your-key> uvicorn api:app --host 127.0.0.1 --port 8000
# open rx-prescription-app.html in browser (file://) or http://127.0.0.1:8000/ (served by api)
# /health → Backend online, /parse → real results, /verify → offline check, /chat → grounded Q&A
```

Docker:
```bash
docker build -t rxcare . && docker run -p 8000:8000 -e GOOGLE_API_KEY=<key> rxcare
# → http://localhost:8000/ (website) + http://localhost:8000/docs (API)
```

Fallback (deprecated Streamlit):
```bash
streamlit run prescription.py   # → http://localhost:8501 — will be retired
```

## Project structure

| File | What |
|---|---|
| `rx-prescription-app.html` | **Primary UI** — static website (no build), talks to `api.py` |
| `api.py` | FastAPI backend: `/health`, `/verify`, `/parse`, `/chat` (serves the HTML at `/`) |
| `prescription.py` | Streamlit fallback (deprecated, see `migration.md`) |
| `indian_db.py` | Offline Indian medicine verification (CSV-backed) |
| `drug_info.py` | openFDA side effects, plain-English simplify, interaction screen |
| `rxnorm.py` | NIH RxNorm registry check + genuineness scoring |
| `indian_medicine_db.csv` | 254k-brand Indian dataset (offline, 43 MB) |
| `accuracy_test/` | Sample prescriptions + ground truth |
| `todo.md` / `ui_plan.md` / `genuine_scan_plan.md` / `migration.md` | Roadmaps & research notes |

## Data sources

- Indian Medicine Dataset (open, ~254k brands) — offline verification
- openFDA drug labels — side effects/warnings (US labels; India-local brands may miss)
- NIH RxNorm — world-registry presence (monthly releases)

## ⚠️ Disclaimer

Educational tool only — **not medical advice**. Registry checks catch
misspellings and fictitious makers but cannot prove a strip is genuine; only
the manufacturer's QR/serialization check can. Always verify with a doctor or
pharmacist. Free-tier APIs may retain data — real patient data belongs on a
paid tier.
