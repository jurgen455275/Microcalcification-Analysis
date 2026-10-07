import argparse
import csv
import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="Compara Python, C++ actual y C++ mejorado")
parser.add_argument("--results", type=pathlib.Path, default=REPO_ROOT / "results")
args = parser.parse_args()
OUT = args.results
OUT.mkdir(parents=True, exist_ok=True)
CLUSTER_ONLY = {"20587054", "20587080"}

def truth(v): return str(v).strip().lower() == "true"

def summarize(rows, predicted, gt_positive, gt_individual, localized, candidates, cand_tp, cand_fp):
    tp = sum(gt_positive(r) and predicted(r) for r in rows)
    fp = sum((not gt_positive(r)) and predicted(r) for r in rows)
    positives = sum(gt_positive(r) for r in rows)
    negatives = len(rows) - positives
    fn, tn = positives - tp, negatives - fp
    ctp, cfp = sum(cand_tp(r) for r in rows), sum(cand_fp(r) for r in rows)
    individual = sum(gt_individual(r) for r in rows)
    loc = sum(gt_individual(r) and localized(r) for r in rows)
    return {
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "precision_presence": tp/(tp+fp) if tp+fp else 0,
        "sensitivity_presence": tp/positives if positives else 0,
        "specificity_presence": tn/negatives if negatives else 0,
        "accuracy": (tp+tn)/len(rows),
        "balanced_accuracy": 0.5*((tp/positives if positives else 0)+(tn/negatives if negatives else 0)),
        "f1_presence": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,
        "localized_images": loc, "localized_rate": loc/individual if individual else 0,
        "total_candidates": sum(candidates(r) for r in rows),
        "candidate_tp": ctp, "candidate_fp": cfp,
        "candidate_precision": ctp/(ctp+cfp) if ctp+cfp else 0,
        "fp_candidates_per_image": cfp/len(rows),
    }

with open(OUT/"froc_inbreast.csv", encoding="utf-8-sig", newline="") as f:
    python_all=list(csv.DictReader(f))
with open(OUT/"verificacion_cpp_mejorado_por_imagen.csv", encoding="utf-8-sig", newline="") as f:
    improved_all=list(csv.DictReader(f))
with open(OUT/"verificacion_por_imagen_final.csv", encoding="utf-8-sig", newline="") as f:
    current=list(csv.DictReader(f))

comparison={}
for k, label in [(20,"cpp_original_documento_equivalente_k20"),(70,"python_referencia_k70")]:
    rows=[r for r in python_all if int(float(r['k']))==k]
    comparison[label]=summarize(
        rows,
        lambda r:int(r['num_candidates'])>0,
        lambda r:truth(r['has_calc']) or r['image_id'] in CLUSTER_ONLY,
        lambda r:truth(r['has_calc']),
        lambda r:truth(r['detected']),
        lambda r:int(r['num_candidates']),
        lambda r:int(r['tp']),
        lambda r:int(r['fp']),
    )

comparison['cpp_actual_k70']=summarize(
    current,
    lambda r:int(r['cpp_candidates'])>0,
    lambda r:truth(r['gt_has_microcalcifications']),
    lambda r:truth(r['gt_has_individual_microcalcifications']),
    lambda r:truth(r['cpp_localized_hit']),
    lambda r:int(r['cpp_candidates']),
    lambda r:int(r['cpp_candidates_on_gt']),
    lambda r:int(r['cpp_candidates_off_gt']),
)

balanced=[r for r in improved_all if r['mode']=='balanced']
comparison['cpp_mejorado_balanced_min3']=summarize(
    balanced,
    lambda r:int(r['candidates'])>=3,
    lambda r:truth(r['gt_positive']),
    lambda r:truth(r['gt_individual']),
    lambda r:truth(r['localized_hit']),
    lambda r:int(r['candidates']),
    lambda r:int(r['candidate_tp']),
    lambda r:int(r['candidate_fp']),
)

sensitive=[r for r in improved_all if r['mode']=='sensitive']
comparison['cpp_mejorado_sensitive_min1']=summarize(
    sensitive,
    lambda r:int(r['candidates'])>=1,
    lambda r:truth(r['gt_positive']),
    lambda r:truth(r['gt_individual']),
    lambda r:truth(r['localized_hit']),
    lambda r:int(r['candidates']),
    lambda r:int(r['candidate_tp']),
    lambda r:int(r['candidate_fp']),
)

with open(OUT/"comparacion_tres_algoritmos.json","w",encoding="utf-8") as f:
    json.dump(comparison,f,ensure_ascii=False,indent=2)
fields=['algoritmo']+list(next(iter(comparison.values())).keys())
with open(OUT/"comparacion_tres_algoritmos.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
    for name,metrics in comparison.items(): w.writerow({'algoritmo':name,**metrics})
print(json.dumps(comparison,ensure_ascii=False,indent=2))
