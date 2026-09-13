"""NIH RxNorm / RxNav lookups: free, keyless, JSON, monthly releases.

Used for world-registry presence check (independent of our Indian CSV) and
name normalization to RxCUI.
NOTE: RxNav's public API no longer exposes the DrugBank interaction feed
(verified 2026-09-13 — no /interaction resource exists), so interactions are
screened with one batched Gemini call in drug_info.check_interactions().
Docs: https://rxnav.nlm.nih.gov/RxNormAPIs.html
"""
import requests
import streamlit as st

BASE = "https://rxnav.nlm.nih.gov/REST"
TIMEOUT = 20


def _get(path, params=None):
    try:
        r = requests.get(f"{BASE}{path}", params=params or {}, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        return r.json()
    except requests.RequestException:
        return None


@st.cache_data(ttl=7 * 86400, show_spinner=False)
def rxnorm_lookup(name: str) -> dict:
    """Normalize a brand/generic name to an RxCUI.
    Returns {rxcui, matched_name, status}. Status is Found / Not found / Lookup failed."""
    info = {"rxcui": "", "matched_name": "", "status": "Not checked"}
    clean = (name or "").strip()
    if len(clean) < 3:
        info["status"] = "Skipped (no name)"
        return info
    # 1. Exact-or-normalized search, then approximate fallback.
    data = _get("/rxcui.json", {"name": clean, "search": 2})
    ids = (data or {}).get("idGroup", {}).get("rxnormId", []) if data else []
    if not ids:
        approx = _get("/approximateTerm.json", {"term": clean, "maxEntries": 1})
        cands = (approx or {}).get("approximateGroup", {}).get("candidate", []) if approx else []
        ids = [cands[0]["rxcui"]] if cands else []
    if ids is None:
        info["status"] = "Lookup failed (network)"
        return info
    if not ids:
        info["status"] = "Not in world registry"
        return info
    rxcui = ids[0]
    detail = _get(f"/rxcui/{rxcui}.json")
    disp = (detail or {}).get("idGroup", {}).get("name", "") if detail else ""
    info.update(rxcui=rxcui, matched_name=disp or clean, status="Found in world registry")
    return info


def score_genuineness(check: dict, rx: dict) -> dict:
    """Registry-presence signals. This is NOT proof of genuineness — only the
    manufacturer's QR/serialization check proves that (see UI note).
    Returns {score, max_score, verdict, signals: [(ok: True/False/None, text)]}."""
    signals = []
    status = check.get("status", "")
    if status.startswith("Verified - brand"):
        signals.append((True, "Exact brand in Indian registry (254k brands)"))
    elif status.startswith("Auto-corrected"):
        signals.append((None, f"Brand name auto-corrected — {status}"))
    elif status.startswith("Verified - salt"):
        signals.append((None, "Generic salt exists — this exact brand is unverified"))
    else:
        signals.append((False, "Brand NOT in Indian registry"))
    if rx.get("rxcui"):
        signals.append((True, f"In world registry (RxNorm: {rx.get('matched_name', '')})"))
    else:
        signals.append((False, "Not in world registry (RxNorm)"))
    if check.get("manufacturer"):
        signals.append((True, f"Manufacturer listed: {check['manufacturer'][:60]}"))
    else:
        signals.append((False, "No manufacturer on record"))
    if check.get("pack_size") or check.get("med_type"):
        signals.append((True, "Pack/type details on record — compare with your strip"))
    else:
        signals.append((None, "No pack details on record"))
    score = sum(1 for ok, _ in signals if ok is True)
    total = len(signals)
    if score >= 4:
        verdict = "Passes registry checks"
    elif score >= 2:
        verdict = "Partially verifiable — check the strip carefully"
    else:
        verdict = "Not verifiable — verify manufacturer QR before use"
    return {"score": score, "max_score": total, "verdict": verdict, "signals": signals}
