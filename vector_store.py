"""Lightweight few-shot retrieval for prescription parsing.
Uses TF-IDF over accuracy_test ground truths when sklearn is available,
falls back to difflib. No heavy deps (chromadb/faiss optional later)."""
import os, json, glob, difflib
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    HAS_SK = True
except: HAS_SK = False

CACHE = {}

def _load_examples():
    if "docs" in CACHE: return CACHE["docs"]
    docs = []
    for p in glob.glob(os.path.join(os.path.dirname(__file__), "accuracy_test", "*.json")):
        if p.endswith(".out.json"): continue
        try:
            j = json.load(open(p))
            gt = j.get("ground_truth") or j.get("groundTruth") or str(j)
            docs.append((os.path.basename(p), gt))
        except: continue
    # learning corrections persisted to JSONL
    lp = os.path.join(os.path.dirname(__file__), "learning_corrections.jsonl")
    if os.path.exists(lp):
        for line in open(lp):
            try:
                j = json.loads(line)
                docs.append((f"learn_{j.get('ts','')}", json.dumps(j.get("correction", j))))
            except: continue
    CACHE["docs"] = docs
    if HAS_SK and docs:
        vec = TfidfVectorizer(max_features=2000, stop_words="english")
        mat = vec.fit_transform([d[1] for d in docs])
        CACHE["vec"], CACHE["mat"] = vec, mat
    return docs

def find_similar(query: str, k=2):
    docs = _load_examples()
    if not docs: return []
    if HAS_SK and "vec" in CACHE:
        import sklearn.metrics.pairwise as pw
        qv = CACHE["vec"].transform([query])
        sims = pw.cosine_similarity(qv, CACHE["mat"])[0]
        idx = sims.argsort()[::-1][:k]
        return [docs[i] for i in idx if sims[i] > 0.1]
    # difflib fallback
    texts = [d[1] for d in docs]
    matches = difflib.get_close_matches(query[:500], texts, n=k, cutoff=0.1)
    out = []
    for m in matches:
        for name, gt in docs:
            if gt == m: out.append((name, gt)); break
    return out[:k]
