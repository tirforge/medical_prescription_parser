"""Offline verification against the open Indian Medicine Dataset
(junioralive/Indian-Medicine-Dataset, ~254k brands, name + composition + manufacturer).
No API key, no internet needed after the one-time CSV download.
"""
import csv
import difflib
import os
import re

import streamlit as st

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "indian_medicine_db.csv")

DOSE_PREFIX = re.compile(r'^(tab\.?|cap\.?|caps?ule|syp\.?|syrup|inj\.?|injection|susp\.?|drops?|oint\.?)\s*', re.I)
FORM_SUFFIX = re.compile(r'\s+(tablets?|capsules?|syrup|suspension|injections?|drops|cream|gel|ointment|sachet|kit)\b.*$', re.I)


def _clean(name: str) -> str:
    name = DOSE_PREFIX.sub("", name or "").strip()
    return FORM_SUFFIX.sub("", name).strip().lower()


@st.cache_resource(show_spinner=False)
def _load_db():
    """Returns (brands, salts): brands maps base-name -> [(full, comp, mfr, active)], salts maps salt -> [count, example]."""
    brands: dict = {}
    salts: dict = {}
    with open(DB_PATH, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            full = (row.get("name") or "").strip()
            if not full:
                continue
            base = FORM_SUFFIX.sub("", full).strip().lower()
            comp = " + ".join(
                x.strip() for x in (row.get("short_composition1", ""), row.get("short_composition2", ""))
                if x.strip()
            )
            mfr = (row.get("manufacturer_name") or "").strip()
            active = (row.get("Is_discontinued") or "").strip().upper() != "TRUE"
            brands.setdefault(base, []).append((full, comp, mfr, active))
            for tok in set(re.split(r"[^a-z]+", comp.lower())):
                if len(tok) >= 5:
                    entry = salts.setdefault(tok, [0, full])
                    entry[0] += 1
    return brands, salts


def _best_entry(entries):
    """Prefer non-discontinued products."""
    for e in entries:
        if e[3]:
            return e
    return entries[0]


@st.cache_data(ttl=86400, show_spinner=False)
def verify_medicine(name: str) -> dict:
    """Check one medicine name against the offline Indian DB.
    Returns extracted/match/composition/manufacturer/status."""
    return _verify_local(name)


@st.cache_data(ttl=86400, show_spinner=False)
def _verify_local(name: str) -> dict:
    result = {"extracted": name, "match": "", "composition": "", "manufacturer": "", "status": "Not checked"}
    try:
        brands, salts = _load_db()
    except FileNotFoundError:
        result["status"] = "DB missing (indian_medicine_db.csv)"
        return result

    clean = _clean(name)
    if not clean:
        result["status"] = "Skipped (no name)"
        return result

    # 1. Exact brand match
    if clean in brands:
        full, comp, mfr, _ = _best_entry(brands[clean])
        result.update(match=full, composition=comp, manufacturer=mfr,
                      status="Verified - brand in Indian DB")
        return result

    # 2. Salt / ingredient match (e.g. Diclofenac, Omeprazole written as generics)
    core = re.split(r"[^a-z]+", clean)
    for tok in core:
        if tok in salts:
            count, example = salts[tok]
            result.update(match=f"{count} products incl. {example[:60]}",
                          composition=tok, status="Verified - salt in Indian DB")
            return result

    # 3. Fuzzy brand suggestion (same first letter bucket for speed)
    bucket = [k for k in brands if k[:1] == clean[:1]] or list(brands)
    suggestions = difflib.get_close_matches(clean, bucket, n=3, cutoff=0.72)
    if suggestions:
        full, comp, mfr, _ = _best_entry(brands[suggestions[0]])
        result.update(match="; ".join(brands[s][0][0][:50] for s in suggestions[:3]),
                      composition=comp, manufacturer=mfr,
                      status="Suggestion - confirm spelling")
    else:
        result["status"] = "Not found (likely BD-local brand)"
    return result
