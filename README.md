# RxCare — Prescription Safety 🏥

Upload a handwritten prescription photo → structured data (patient, doctor,
medicines) + Indian registry verification + side effects + grounded Q&A chat.

**Primary UI is `rx-prescription-app.html` + `api.py` (FastAPI)** — fast,
mobile-friendly, no Streamlit chrome. Streamlit (`prescription.py`) is kept as
a deprecated fallback (see `migration.md`).

Built with free-tier vision models (Gemini / Gemma 4). Public repo:
<https://github.com/tirforge/medical_prescription_parser>

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
- 💬 **Grounded chat** — `/chat` answers on paracetamol/cold brands with DB/FDA
  context, patient or doctor mode; answers are auto-cleaned of LLM markdown
  clutter for the plain-text UI
- 🧪 **Accuracy runner** — `eval_accuracy.py` computes med/patient hit rate
  against `accuracy_test/` ground truth → `eval_results.json`
- 📋 **Copy results** — one-click text + JSON export
- 🎨 Medical theme (light + dark), sidebar model picker, metrics + staged progress

## Model resilience (auto-fallback, quota-safe)

All model calls go through an ordered fallback chain with **fail-fast** tuning:

| Model (chain order) | Note |
|---|---|
| `gemini-3.6-flash` | best handwriting (20 RPD free) |
| `gemini-3.6-flash-lite` / `gemini-3.1-flash(-lite)` / `gemini-2.5-flash-lite` | some free tiers return 404/503 (renamed/deprecated) and are skipped in ~0.2s |
| `gemini-3.5-flash` | 429s once daily quota hit |
| `gemini-3.5-flash-lite` | 500 RPD — reliable workhorse, often the fallback winner |
| `gemma-4-26b-a4b-it` / `gemma-4-31b-it` | 14,400 RPD safety net |

- `max_retries=0` → an exhausted model fails in **~0.2s** instead of burning ~35s
  of retries per call (the "takes long to analyse" fix)
- Name it: the chain used to stop after the first 3 models; it now walks the
  full list so a working model is always reached
- Last model that succeeded is cached to `last_model.json` (git-ignored) so
  restarts skip the dead models — `/chat` drops to ~1s after the first success
- If every model collapses at once, `/parse` returns HTTP 503 with a clear
  message instead of silently returning empty JSON
- Verified free-tier accuracy: **med hit 1.00, patient hit 1.00** on the bundled
  4-sample eval (`eval_accuracy.py --model gemini-3.5-flash-lite`)

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

## Setup

```bash
git clone https://github.com/tirforge/medical_prescription_parser && cd medical_prescription_parser
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
# /health → backend + model + last-model info
# /parse  → real structured results,  /verify → offline check,  /chat → grounded Q&A
# /docs   → interactive OpenAPI docs
```

Docker:
```bash
docker build -t rxcare . && docker run -p 8000:8000 -e GOOGLE_API_KEY=<key> rxcare
# → http://localhost:8000/ (website) + http://localhost:8000/docs (API)
```

Expose anywhere (free Cloudflare quick-tunnel):
```bash
cloudflared tunnel --url http://127.0.0.1:8000   # prints a public https URL
```

Fallback (deprecated Streamlit):
```bash
streamlit run prescription.py   # → http://localhost:8501 — will be retired
```

## Tests

```bash
python3 -m pytest            # unit tests (e.g. normalize_frequency)
python3 eval_accuracy.py     # accuracy vs accuracy_test/ ground truth
# Playwright specs in tests/ (e2e-user.spec.js, website.spec.js, website-full.spec.js)
```

## Project structure

| File | What |
|---|---|
| `rx-prescription-app.html` | **Primary UI** — static website (no build), talks to `api.py` |
| `api.py` | FastAPI backend: `/health`, `/verify`, `/parse`, `/chat` (serves the HTML at `/`) |
| `prescription.py` | Vision pipeline + Streamlit fallback (deprecated, see `migration.md`) |
| `indian_db.py` | Offline Indian medicine verification (CSV-backed) |
| `drug_info.py` | openFDA side effects, plain-English simplify, interaction screen |
| `rxnorm.py` | NIH RxNorm registry check + genuineness scoring |
| `vector_store.py` | Few-shot retrieval over prior parses / corrections |
| `eval_accuracy.py` | Accuracy runner → `eval_results.json` (git-ignored) |
| `indian_medicine_db.csv` | 254k-brand Indian dataset (offline, 43 MB) |
| `accuracy_test/` | Sample prescriptions + ground truth |
| `tests/` | pytest + Playwright specs |
| `last_model.json` | Runtime cache — last working Gemini model (git-ignored) |
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