# Genuine vs Fake Medicine Scanner — Proposal (ask before building)

Date: 2026-09-13. Nothing below is implemented yet — approve first.

## 1. What the top repos do

| Repo | Approach | Verdict for us |
|---|---|---|
| `yash0122/medtrack` | Blockchain supply-chain + QR verification (manufacturer→pharmacy→consumer) | Needs a manufacturer network; overkill, can't clone-and-use |
| `Sauravpandey98/Fake-Medicine-Detector` | Deep-learning packet-photo compare (original vs test image) | Needs a reference photo of EVERY product; good fakes pass it |
| `MuhammadRamzy/PharmaTraceChain` | Blockchain + QR + geofencing | Same ecosystem problem as medtrack |
| `ayush6645/QRPrintVerifier` | ML detects photocopied QR prints | Lab-grade, not a ready tool |
| `noahluddy/counter-pill` | Pill photo → authenticity guess | 2016 hackathon toy |

**Recommendation: clone NONE.** Their approaches don't fit (blockchain needs an
ecosystem; image-compare needs a reference-photo DB we don't have). Build the
scanner ourselves from verification APIs instead.

## 2. Verification APIs found

| API | Cost/key | What it gives us | Limitation |
|---|---|---|---|
| **RxNorm / RxNav (NIH)** `https://rxnav.nlm.nih.gov/REST` | FREE, no key, JSON | `findRxcuiByString` (exact/normalized/approximate name match), `getDrugs`, NDC status, **drug-drug interaction API** (DrugBank-powered, no severity) | US-centric brands; Indian salts map well, local brand names often don't |
| **openFDA** (already integrated) | FREE, no key | Labels, adverse events, NDC directory | US labels only |
| **CDSCO (India)** | — | **NO public checking API exists.** QR on top-300 brands verifies against *manufacturer* data (phone scan → maker info). CDSCO publishes monthly NSQ/spurious-drug alert lists (PDF/web) | No API; QR check stays a phone task. We link the NSQ alerts + QR guide |
| Indian DB CSV (already in repo) | local | 254k brands: composition, manufacturer, pack, type | Registry presence only |

## 3. Proposed design — "🔍 Scan Medicine" section

Top of app, above the prescription flow. Two inputs:

1. **Type the name** (text box), or
2. **Snap the strip** (photo upload / paste → Gemini reads brand + mfg + batch text off the pack, 1 call)

Then a 4-source check per medicine (parallel, cached 7 days):

- **Indian DB** (local): exact / auto-corrected / salt / not-found + full details
- **RxNorm** (new): normalized RxCUI match? → independent "exists in world registry" signal + interaction pairs
- **openFDA** (have it): label + side effects (already built)
- **CDSCO**: no API — show QR-guide link + NSQ-alert link instead

**Genuineness signals** (scores, never a verdict — see §4):

- ✅ Exact brand in Indian registry (+2)
- ✅ Also in RxNorm world registry (+1)
- ✅ Manufacturer name present (+1)
- ✅ Pack/type details present (+1)
- ✅ Not discontinued (+1)
- ⚠️ Salt-only match → "generic exists, brand unverified"
- 🛑 Not in any registry → "cannot verify — check manufacturer QR"

Bands: 4–5 "Passes registry checks" · 2–3 "Partially verifiable" · 0–1
"Not verifiable — verify manufacturer QR before use".

**Full data card** per scan: composition, manufacturer, pack, type,
side effects (plain English), interactions (RxNorm pairs), DailyMed link,
prescribed-vs-registry compare checklist ("does YOUR strip say the same
manufacturer?").

## 4. Honesty limits (shown in UI)

No offline check can PROVE a strip is genuine — only the manufacturer's QR /
serialization check can. Our scanner proves *registry presence + consistency*,
which catches wrongspellings, fictitious manufacturers, and unknown brands
(the common tells), but a perfect counterfeit of a real brand still passes.
The UI will say this plainly.

## 5. Build steps (after approval)

1. `rxnorm.py`: `findRxcuiByString` (approximate) + interaction lookup, cached
2. Scan section in `prescription.py` (text + strip-photo → brand reader)
3. Signals scoring + full data card UI + QR/NSQ guide links
4. Compile, live-test (Dolo 650 genuine-pattern, XyzalXYZ unknown-pattern),
   restart tunnel

Needs from you: nothing (no new keys — RxNorm/openFDA are keyless).
