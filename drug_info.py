"""Side-effect / safety lookup via the free openFDA drug-label API.

No API key needed (generous unauthenticated quota). Results are cached for
7 days. If a brand has no FDA entry (common for India/BD-local brands), we
return the known composition and tell the user to verify with a pharmacist —
we never invent side effects.
"""
import re
import urllib.parse

import requests
import streamlit as st

FDA_LABEL_URL = "https://api.fda.gov/drug/label.json"
TIMEOUT = 20

# Indian (INN) -> US (USAN) generic names: openFDA labels use US names.
INN_TO_USAN = {
    "paracetamol": "acetaminophen",
    "amoxycillin": "amoxicillin",
    "sulphamethoxazole": "sulfamethoxazole",
    "adrenaline": "epinephrine",
    "noradrenaline": "norepinephrine",
    "lignocaine": "lidocaine",
    "frusemide": "furosemide",
    "beclomethasone": "beclometasone",
}


def _hit_matches(hit: dict, token: str) -> bool:
    """Reject wrong-drug labels: the searched token (or its US alias) must
    appear in the label's own substance/generic/brand names."""
    openfda = hit.get("openfda", {}) or {}
    names = []
    for k in ("substance_name", "generic_name", "brand_name"):
        v = openfda.get(k, [])
        names.extend(v if isinstance(v, list) else [v])
    blob = " ".join(str(n) for n in names).lower()
    candidates = {token.lower(), INN_TO_USAN.get(token.lower(), "")}
    for c in candidates:
        if c and re.search(r"\b" + re.escape(c) + r"\b", blob):
            return True
    return False


def _clean_fda_text(value, limit: int = 1200) -> str:
    """FDA label fields are lists of long strings — join, de-junk, truncate."""
    if isinstance(value, list):
        text = " ".join(str(v) for v in value)
    else:
        text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"SPL[^a-zA-Z]{0,3}(PATIENT|MEDICATION|UNCLASSIFIED).*?(GUIDE)?", "", text)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + " … (see full label)"
    return text


def _fda_search(term: str):
    """One openFDA label lookup by substance/brand name.
    Prefers a label that actually lists adverse reactions. Returns dict or None."""
    term = (term or "").strip()
    if len(term) < 3:
        return None
    for field in ("openfda.substance_name", "openfda.generic_name", "openfda.brand_name"):
        # First pass: labels that actually list adverse reactions.
        # Second pass: any label (warnings-only is still useful).
        for qualifier in (" AND _exists_:adverse_reactions", ""):
            try:
                q = f'{field}:"{term}"{qualifier}'
                r = requests.get(
                    FDA_LABEL_URL,
                    params={"search": q, "limit": 3},
                    timeout=TIMEOUT,
                )
                if r.status_code != 200:
                    continue
                results = r.json().get("results", [])
                if not results:
                    continue
                for hit in results:  # accept only labels for the drug we asked about
                    if hit.get("adverse_reactions") and _hit_matches(hit, term):
                        return hit
                if qualifier == "":
                    for hit in results:
                        if _hit_matches(hit, term):
                            return hit
                    continue  # no good hit for this field — try next field
            except requests.RequestException:
                return {"_connection_error": True}
    return None


def _composition_tokens(composition: str):
    """Split 'Paracetamol + Caffeine' into searchable tokens."""
    return [t for t in re.split(r"[^a-zA-Z]+", composition or "") if len(t) >= 4]


@st.cache_data(ttl=7 * 86400, show_spinner=False)
def get_drug_safety(name: str, composition: str = "") -> dict:
    """Look up side effects for one medicine.

    Tries each composition token (salt) first, then the brand name.
    Returns {name, composition, side_effects, warnings, boxed_warning,
    source, source_url, status}.
    """
    info = {
        "name": name,
        "composition": composition or "-",
        "side_effects": "",
        "warnings": "",
        "boxed_warning": "",
        "source": "openFDA drug label",
        "source_url": "",
        "status": "Not checked",
    }
    tried = []
    search_terms = []
    for token in _composition_tokens(composition) + ([name] if name else []):
        search_terms.append(token)
        usan = INN_TO_USAN.get(token.lower())
        if usan:
            search_terms.append(usan)
    for token in search_terms:
        if token.lower() in tried:
            continue
        tried.append(token.lower())
        hit = _fda_search(token)
        if hit is None:
            continue
        if hit.get("_connection_error"):
            info["status"] = "Lookup failed (network) — try again"
            return info
        info["side_effects"] = _clean_fda_text(hit.get("adverse_reactions"))
        info["warnings"] = _clean_fda_text(hit.get("warnings"), limit=800)
        info["boxed_warning"] = _clean_fda_text(hit.get("boxed_warning"), limit=500)
        info["source_url"] = (
            "https://dailymed.nlm.nih.gov/dailymed/search.cfm?query="
            + urllib.parse.quote(token)
        )
        if info["side_effects"] or info["warnings"] or info["boxed_warning"]:
            info["status"] = f"Found (via '{token}')"
            return info
    info["status"] = "No FDA entry — verify with pharmacist"
    return info


@st.cache_data(ttl=7 * 86400, show_spinner=False)
def check_interactions(items: list) -> dict:
    """Screen ALL drugs together in ONE Gemini call (fast + quota-friendly).
    items: [(name, composition)]. Returns {pairs: [{drugs, detail}], status}.
    AI-screened from label knowledge — NOT a substitute for a pharmacist or a
    curated interaction database. Returns {}-safe empty result on failure."""
    clean = [(n, c) for n, c in items if n]
    if len(clean) < 2:
        return {"pairs": [], "status": "Need 2+ medicines to check combinations"}
    try:
        import os
        from langchain_google_genai import ChatGoogleGenerativeAI
        key = os.environ.get("GOOGLE_API_KEY", "")
        if not key:
            return {"pairs": [], "status": "No API key — cannot screen combinations"}
        llm = ChatGoogleGenerativeAI(
            model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            google_api_key=key,
            temperature=0,
        )
        listed = "\n".join(f"{i + 1}. {n} ({c or 'composition unknown'})"
                           for i, (n, c) in enumerate(clean))
        prompt = (
            "You screen drug combinations for safety. Given these medicines, list "
            "ONLY well-established, clinically significant drug-drug interactions "
            "between them. Reply with exactly one line per interacting PAIR in this "
            "format: DrugA + DrugB: one plain-English sentence on the risk and what "
            "to watch for. Only include pairs with real known interactions — never "
            "invent. If no significant interactions are known, reply with exactly: "
            "NONE\n\nMedicines:\n" + listed
        )
        raw = llm.invoke(prompt).content or ""
        if isinstance(raw, list):
            raw = " ".join(
                b.get("text", "") for b in raw
                if isinstance(b, dict) and b.get("type") == "text"
            )
        pairs = []
        for line in str(raw).splitlines():
            line = re.sub(r"^\s*\d+[.)]\s*", "", line).strip().strip("-•* ").strip()
            if not line or line.strip().upper() == "NONE":
                continue
            if ":" not in line:
                continue
            drugs, detail = line.split(":", 1)
            drugs, detail = drugs.strip(), detail.strip()
            if drugs and detail and "+" in drugs:
                pairs.append({"drugs": drugs, "detail": detail[:400]})
        if not pairs:
            return {"pairs": [],
                    "status": "No significant known interactions flagged (AI screen — verify with pharmacist)"}
        return {"pairs": pairs,
                "status": f"{len(pairs)} potential interaction(s) flagged — verify with pharmacist"}
    except Exception:
        return {"pairs": [], "status": "Screening failed — verify with pharmacist"}


@st.cache_data(ttl=7 * 86400, show_spinner=False)
def simplify_all_for_patient(items: list) -> dict:
    """One Gemini call for ALL drugs (fast + quota-friendly).
    Returns {drug_name: 'effect1, effect2, effect3'} short plain-English lines.
    Never invents: only condenses the given FDA texts. Returns {} on failure."""
    items = [(n, t) for n, t in items if n and t and len(t.strip()) >= 20]
    if not items:
        return {}
    try:
        import os
        from langchain_google_genai import ChatGoogleGenerativeAI
        key = os.environ.get("GOOGLE_API_KEY", "")
        if not key:
            return {}
        llm = ChatGoogleGenerativeAI(
            model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            google_api_key=key,
            temperature=0,
        )
        numbered = "\n".join(
            f"{i + 1}. {name}: {text[:900]}" for i, (name, text) in enumerate(items)
        )
        prompt = (
            "For each numbered drug below, list its 3-5 most common side effects "
            "in plain everyday words. Reply with exactly one line per drug in this "
            "format: DrugName: effect1, effect2, effect3. Only use what the text "
            "states — never add effects not in the text.\n\n" + numbered
        )
        raw = (llm.invoke(prompt).content or "")
        if isinstance(raw, list):
            raw = " ".join(
                b.get("text", "") for b in raw
                if isinstance(b, dict) and b.get("type") == "text"
            )
        out = {}
        wanted = set(n.lower() for n, _ in items)
        for line in str(raw).splitlines():
            line = re.sub(r"^\s*\d+[.)]\s*", "", line).strip().strip("-•* ").strip()
            if ":" not in line:
                continue
            head, tail = line.split(":", 1)
            head, tail = head.strip().lower(), tail.strip()
            if head in wanted and tail:
                out[head] = tail[:300]
        return out
    except Exception:
        return {}
