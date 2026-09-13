"""Offline verification against the open Indian Medicine Dataset
(junioralive/Indian-Medicine-Dataset, ~254k brands).
Updated 2026-09-13 to use updated_indian_medicine_data.csv (43MB) which adds
medicine_desc, side_effects, drug_interactions, salt_composition.
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
    """Returns (brands, salts): brands maps base-name -> [(full, comp, mfr, active, price, pack, mtype, desc, se, di, salt)], salts maps salt -> [count, example]."""
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
            # Fallback: some rows have empty short_composition but salt_composition is populated
            if not comp:
                comp = (row.get("salt_composition") or "").strip()
            mfr = (row.get("manufacturer_name") or "").strip()
            # New CSV uses 'price' without (₹); old used 'price(₹)'
            price = (row.get("price(₹)") or row.get("price") or "").strip()
            pack = (row.get("pack_size_label") or "").strip()
            mtype = (row.get("type") or "").strip()
            desc = (row.get("medicine_desc") or "").strip()
            se = (row.get("side_effects") or "").strip()
            di = (row.get("drug_interactions") or "").strip()
            salt_comp = (row.get("salt_composition") or "").strip()
            active = (row.get("Is_discontinued") or "").strip().upper() != "TRUE"
            brands.setdefault(base, []).append((full, comp, mfr, active, price, pack, mtype, desc, se, di, salt_comp))
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


def _entry_details(entry):
    """Unpack a brand entry into display fields."""
    # Tuple: (full, comp, mfr, active, price, pack, mtype, desc, se, di, salt_comp)
    full, comp, mfr, _active, price, pack, mtype, desc, se, di, salt_comp = entry
    return {"match": full, "composition": comp, "manufacturer": mfr,
            "price": price, "pack_size": pack, "med_type": mtype,
            "medicine_desc": desc, "side_effects_db": se, "drug_interactions_db": di,
            "salt_composition": salt_comp}


@st.cache_data(ttl=86400, show_spinner=False)
def verify_medicine(name: str) -> dict:
    """Check one medicine name against the offline Indian DB.
    Returns extracted/match/composition/manufacturer/status."""
    return _verify_local(name)


@st.cache_data(ttl=86400, show_spinner=False)
def _verify_local(name: str) -> dict:
    result = {"extracted": name, "match": "", "composition": "", "manufacturer": "",
              "price": "", "pack_size": "", "med_type": "", "medicine_desc": "",
              "side_effects_db": "", "drug_interactions_db": "", "salt_composition": "",
              "salt_count": 0, "salt_example": "", "status": "Not checked"}
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
        result.update(_entry_details(_best_entry(brands[clean])),
                      status="Verified - brand in Indian DB")
        return result

    # 2. Salt / ingredient match (e.g. Diclofenac, Omeprazole written as generics)
    core = re.split(r"[^a-z]+", clean)
    for tok in core:
        if tok in salts:
            count, example = salts[tok]
            result.update(match=f"{count} products incl. {example[:60]}",
                          salt_count=count, salt_example=example[:60],
                          composition=tok, status="Verified - salt in Indian DB")
            return result

    # 3. Fuzzy brand suggestion (same first letter bucket for speed)
    bucket = [k for k in brands if k[:1] == clean[:1]] or list(brands)
    suggestions = difflib.get_close_matches(clean, bucket, n=3, cutoff=0.72)
    if suggestions:
        # Auto-correct: take the closest brand instead of asking the user.
        best = _best_entry(brands[suggestions[0]])
        details = _entry_details(best)
        details["match"] = best[0]
        result.update(details, status=f"Auto-corrected from '{(name or '').strip()}'")
    else:
        result["status"] = "Not found (likely BD-local brand)"
    return result


@st.cache_data(ttl=86400, show_spinner=False)
def find_alternatives(composition: str, exclude: str = "", n: int = 3) -> list:
    """Alternatives with same salt/composition (different brand)."""
    if not composition: return []
    # Use first salt token as key
    toks = [t for t in re.split(r"[^a-z]+", composition.lower()) if len(t) >= 4]
    if not toks: return []
    key = toks[0]
    try:
        brands, _ = _load_db()
    except: return []
    alts = []
    for base, entries in brands.items():
        if base == _clean(exclude): continue
        for ent in entries:
            comp = ent[1] or ""
            if key in comp.lower():
                alts.append(ent[0])
                break
        if len(alts) >= n: break
    return alts[:n]
