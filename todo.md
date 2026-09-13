# Medical Prescription Parser — TODO

Gap analysis vs top similar repos (checked 2026-09-13):
upstream `mohtasham9/medical_prescription_parser` ·
`Tusharsharma420/medsafe-ai` · `tishact7/medscan-lens` ·
`ramanujala/Medical-Prescription-Analyzer` · `f20240594-byte/MediParse` ·
`Abhinay-sai-krishna/DrugScan` · `csotherden/prescription-parser` ·
`AdarshBP/LLM-Drug-Interaction-Checker` · `junioralive/Indian-Medicine-Dataset`

What we already have (don't rebuild): Gemini/Gemma vision → structured JSON,
multi-upload, clipboard paste-image, preocr denoise/deskew, copy-to-clipboard
text+JSON, Indian DB verify (brand/salt/auto-correct/pack/type), openFDA side
effects + plain-English batch simplify, boxed warnings, DailyMed links, review
flags, medical disclaimer, git-ignored secrets.

Legend: effort S < 1h · M = few hours · L = day+.

## P0 — Bugs (fix first)

- [x] **Temp-folder leak**: `sweep_stale_outputs()` at startup + success-path
      removal (try/finally impractical without re-indenting `main`). DONE 2026-09-13.
- [x] **Pin requirements**: pinned working set 2026-09-13. DONE.
- [x] **Dedupe medications**: `dedupe_medications()` merges same
      name+dosage+frequency, keeps informative duration. DONE 2026-09-13.

## P1 — Clinical safety (the core gap vs medsafe-ai, DrugScan, RxCheck)

- [x] **Drug-drug interaction check**: batched one-call Gemini screen
      (`drug_info.check_interactions`) over all meds, severity-ordered red
      flags. NOTE: RxNav's public interaction feed is retired (verified
      2026-09-13), so this is AI-screened + pharmacist disclaimer, not
      curated DB. DONE 2026-09-13.
- [ ] **Upgrade to the 45MB updated Indian dataset**: native `side_effects`,
      `drug_interactions`, `medicine_desc`, `salt_composition` columns. Covers
      India-local brands where openFDA returns nothing. Keep current CSV as
      backup. (`junioralive/Indian-Medicine-Dataset` → `DATA/updated_indian_medicine_data.csv`) · M
- [ ] **Show `medicine_desc`** (what it's for + how to take it) in each drug
      card once the 45MB file lands. (same source) · S
- [ ] **Age-specific dosage check**: verify prescribed dosage fits patient age
      (esp. children/elderly), warn on mismatch. (DrugScan) · M
- [ ] **Alternative medication suggestions** when an interaction or risky dose
      is found. (DrugScan) · M
- [ ] **Latin abbreviation support**: Rx shorthand OD/BD/TDS/QID/SOS and
      1-0-1 schedule notation common in Indian prescriptions — normalize before
      verify. (`Medical-Prescription-Analyzer`) · S

## P2 — Product / UX (vs medscan-lens, medsafe-ai, MediParse)

- [x] **Rewrite README**: documents Gemini/Gemma 4, quotas, setup, structure,
      disclaimer. DONE 2026-09-13.
- [x] **Build the sidebar**: model picker, API-key input, about, disclaimer.
      DONE 2026-09-13.
- [ ] **Tabbed layout**: separate "Prescription Analyzer" vs "Single Drug
      Scanner" tabs like medscan-lens (single-drug tab = fast safety lookup
      without full parse). · M
- [ ] **Export results**: download parsed result + safety as PDF/CSV/print view
      for doctors. (own audit) · M
- [ ] **Sample-image button**: one-click "Try a sample" from `accuracy_test/`
      so visitors test without uploading. (common pattern) · S
- [ ] **PDF input**: accept scanned prescription PDFs (preocr already supports
      pages; need pdf→image step). (`csotherden`, MediParse) · M
- [ ] **Before/after enhance preview**: side-by-side original vs
      preocr-enhanced image. (neonwatty pattern) · S
- [x] **Load `.env` + Streamlit secrets**: `load_dotenv()` wired; sidebar key
      input added; `.streamlit/config.toml` theme added. DONE 2026-09-13.
- [x] **Sidebar key input**: password field → env. DONE 2026-09-13.
- [ ] **Result history**: persist past parses (SQLite like MediParse, or
      MongoDB like Analyzer) with re-view. · M
- [ ] **Confidence per field**: show low-confidence extractions highlighted
      (Analyzer does blue/yellow/red). Needs model logprobs or a verify pass. · L

## P3 — Quality / accuracy engine (vs Analyzer, csotherden, Donut repos)

- [ ] **Accuracy runner for `accuracy_test/`**: images + ground truth exist but
      no script computes match rate/WER. Add `eval_accuracy.py` + score table.
      (`csotherden` scoring, Donut WER tracking) · M
- [ ] **Second-pass review**: re-parse with extracted JSON as context to catch
      model errors (multi-pass pipeline). (`csotherden`) · M
- [ ] **Offline OCR fallback**: EasyOCR/PaddleOCR path when Gemini quota dies,
      so the app degrades instead of failing. (Analyzer, MediParse) · L
- [ ] **Batch folder mode**: point at a directory, parse all, CSV summary.
      (Handwritten-to-Digital-OCR-Project) · S

## P4 — Ship readiness (vs medsafe-ai, MediParse, Analyzer)

- [ ] **Tests**: `tests/` with unit tests for verify/safety/flags
      (medsafe-ai has `test_medicine_db.py`, `test_llm_helper.py`). · M
- [ ] **Dockerfile + CI**: container + GitHub Actions compile/test workflow
      (medsafe-ai `.github/`, MediParse). · M
- [ ] **LICENSE + CONTRIBUTING**: pick MIT/Apache-2.0 (medsafe-ai, MediParse). · S
- [ ] **Live demo deploy**: Streamlit Community Cloud (`share.streamlit.io`)
      with secrets config (medscan-lens, medsafe-ai both do this). · S
- [ ] **REST API mode**: `/parse` endpoint for integration into other systems
      (FastAPI like Analyzer, Go service like csotherden). · L
- [ ] **Sample-learning loop**: store corrected parses, retrieve similar ones
      as few-shot context (pgvector pattern in csotherden). · L
- [ ] **AI medication chat**: ask follow-up questions about the parsed drugs
      with grounded answers. (DrugScan) · M
- [ ] **Privacy review**: free-tier APIs may retain data — document this;
      paid tier / self-host path for real patient data. (all repos) · S
