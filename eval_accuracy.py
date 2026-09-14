"""Accuracy runner for accuracy_test/*.png vs *.json ground truth.
Computes simple medication-name hit rate and patient-name hit rate.
Usage: python eval_accuracy.py [--model gemini-3.5-flash-lite]
Outputs a table to stdout and eval_results.json
"""
import os, json, glob, argparse, sys, re
from pathlib import Path

def load_gt(path):
    j = json.load(open(path))
    gt = j.get("ground_truth") or j.get("groundTruth") or str(j)
    return str(gt).lower()

def med_names_from_result(res):
    return [m.get("name","").lower() for m in res.get("medications",[])]

def dose_hit_for(med, gt_txt):
    """Dosage-aware check: dose counts only when the med name matched AND the
    dosage number appears in ground truth (catches 72h-vs-12h style slips)."""
    dose = str(med.get("dosage") or "")
    nums = re.findall(r"\d+", dose)
    if not nums:
        return None  # no dose to check
    return 1 if any(n in gt_txt for n in nums) else 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("GEMINI_MODEL","gemini-3.5-flash-lite"))
    ap.add_argument("--dir", default="accuracy_test")
    args = ap.parse_args()
    os.environ["GEMINI_MODEL"] = args.model
    # import after env set
    from prescription import get_prescription_informations
    pattern = os.path.join(args.dir, "*.png")
    if not glob.glob(pattern):
        pattern = os.path.join(args.dir, "*.jpg")
    files = sorted(glob.glob(pattern))
    if not files:
        print("No images in", args.dir); sys.exit(1)
    rows = []
    for img in files:
        base = os.path.splitext(os.path.basename(img))[0]
        gt_path = os.path.join(args.dir, base + ".json")
        if not os.path.exists(gt_path):
            continue
        gt_txt = load_gt(gt_path)
        try:
            res = get_prescription_informations([img])
        except Exception as e:
            rows.append({"file": base, "error": str(e)[:120], "med_hit": 0, "patient_hit": 0})
            continue
        meds = med_names_from_result(res)
        # med hit: at least one med name appears in gt
        hits = sum(1 for m in meds if m and m in gt_txt)
        med_hit = hits / max(1, len(meds)) if meds else (1 if "medications" not in gt_txt else 0)
        # dosage hit: for name-matched meds, is the dose number in gt?
        dose_scores = []
        for m in res.get("medications", []):
            if (m.get("name","").lower() in gt_txt):
                s = dose_hit_for(m, gt_txt)
                if s is not None:
                    dose_scores.append(s)
        dose_hit = sum(dose_scores)/len(dose_scores) if dose_scores else None
        # blur log: soft photos explain real-world drops the clean set hides
        try:
            from prescription import blur_score as _bs
            blur = round(_bs(img), 1)
        except Exception:
            blur = None
        patient = (res.get("patient_name") or "").lower()
        patient_hit = 1 if patient and patient in gt_txt else 0
        illeg = len(res.get("illegible_lines") or [])
        rows.append({"file": base, "meds": meds, "med_hit": round(med_hit,2), "dose_hit": dose_hit, "blur": blur, "illegible": illeg, "patient": patient, "patient_hit": patient_hit})
        print(f"{base}: meds={meds} hit={med_hit:.2f} dose={dose_hit} blur={blur} illegible={illeg} patient='{patient}' hit={patient_hit}")
    avg_med = sum(r.get("med_hit",0) for r in rows)/max(1,len(rows))
    avg_pat = sum(r.get("patient_hit",0) for r in rows)/max(1,len(rows))
    _dh = [r["dose_hit"] for r in rows if r.get("dose_hit") is not None]
    avg_dose = sum(_dh)/len(_dh) if _dh else None
    print(f"\nOverall med hit: {avg_med:.2f}  dose hit: {avg_dose}  patient hit: {avg_pat:.2f}  n={len(rows)}")
    json.dump({"avg_med_hit": avg_med, "avg_dose_hit": avg_dose, "avg_patient_hit": avg_pat, "rows": rows}, open("eval_results.json","w"), indent=2)
    print("Wrote eval_results.json")

if __name__ == "__main__":
    main()
