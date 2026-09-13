# Medical Prescription Parsing 🏥

Upload a handwritten prescription photo → structured data (patient, doctor,
medicines) + Indian registry verification + side effects + interaction screen.
Built with Streamlit and free-tier vision models (Gemini / Gemma 4).

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

## Run

```bash
streamlit run prescription.py   # → http://localhost:8501
```

Expose publicly (Cloudflare quick tunnel):

```bash
cloudflared tunnel --url http://localhost:8501
```

Streamlit Community Cloud: set `GOOGLE_API_KEY` under App → Settings → Secrets.

## Project structure

| File | What |
|---|---|
| `prescription.py` | Streamlit app: parse, scan, verify, safety UI |
| `indian_db.py` | Offline Indian medicine verification (CSV-backed) |
| `drug_info.py` | openFDA side effects, plain-English simplify, interaction screen |
| `rxnorm.py` | NIH RxNorm registry check + genuineness scoring |
| `indian_medicine_db.csv` | 254k-brand Indian dataset (offline) |
| `accuracy_test/` | Sample prescriptions + ground truth |
| `todo.md` / `ui_plan.md` / `genuine_scan_plan.md` | Roadmaps & research notes |

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
