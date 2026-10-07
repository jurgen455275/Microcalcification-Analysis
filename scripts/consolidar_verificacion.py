import argparse
import csv
import json
import pathlib
import plistlib

repo_root = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="Consolida ground truth individual y por cluster")
parser.add_argument("--dataset", type=pathlib.Path, default=repo_root / "data" / "INbreast Release 1.0")
parser.add_argument("--results", type=pathlib.Path, default=repo_root / "results")
args = parser.parse_args()
dataset = args.dataset
outdir = args.results
outdir.mkdir(parents=True, exist_ok=True)
source = outdir / "verificacion_por_imagen.csv"
final_csv = outdir / "verificacion_por_imagen_final.csv"
positive_csv = outdir / "imagenes_con_microcalcificaciones_gt.csv"
bucket_csv = outdir / "acierto_por_cantidad.csv"
summary_json = outdir / "verificacion_resumen_final.json"


def as_bool(value):
    return str(value).strip().lower() in {"true", "1", "yes", "si", "sí"}


def annotation_inventory(image_id):
    path = dataset / "AllXML" / f"{image_id}.xml"
    calc = cluster = calc_points = cluster_points = 0
    if not path.exists():
        return calc, cluster, calc_points, cluster_points
    with open(path, "rb") as f:
        data = plistlib.load(f)
    for image in data.get("Images", []):
        for roi in image.get("ROIs", []):
            name = str(roi.get("Name", "")).strip().lower()
            points = roi.get("Point_px", [])
            if "calcification" in name:
                calc += 1
                calc_points += len(points) if isinstance(points, list) else 0
            elif name == "cluster":
                cluster += 1
                cluster_points += len(points) if isinstance(points, list) else 0
    return calc, cluster, calc_points, cluster_points


with open(source, encoding="utf-8-sig", newline="") as f:
    original = list(csv.DictReader(f))

rows = []
for row in original:
    image_id = row["image_id"]
    calc, cluster, calc_points, cluster_points = annotation_inventory(image_id)
    individual = calc > 0
    clustered = cluster > 0
    combined = individual or clustered
    predicted = as_bool(row["cpp_predicted_positive"])
    if combined and predicted:
        result = "TP"
    elif combined and not predicted:
        result = "FN"
    elif not combined and predicted:
        result = "FP"
    else:
        result = "TN"
    row.update({
        "gt_has_individual_microcalcifications": individual,
        "gt_has_cluster": clustered,
        "gt_has_microcalcifications": combined,
        "gt_calcification_rois": calc,
        "gt_cluster_rois": cluster,
        "gt_calcification_points": calc_points,
        "gt_cluster_points": cluster_points,
        "localized_evaluable": individual,
        "presence_result": result,
        "presence_correct": result in {"TP", "TN"},
    })
    rows.append(row)

preferred = [
    "image_id", "dcm", "laterality", "view", "acr", "bi_rads", "spacing_mm",
    "gt_has_microcalcifications", "gt_has_individual_microcalcifications", "gt_has_cluster",
    "gt_calcification_rois", "gt_cluster_rois", "gt_calcification_points", "gt_cluster_points",
    "k", "cpp_candidates", "cpp_predicted_positive", "presence_result", "presence_correct",
    "localized_evaluable", "cpp_localized_hit", "cpp_candidates_on_gt", "cpp_candidates_off_gt",
    "cpp_mean", "cpp_std", "cpp_threshold", "cpp_time_ms",
]
with open(final_csv, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=preferred)
    writer.writeheader()
    writer.writerows({key: row.get(key, "") for key in preferred} for row in rows)

positive_fields = [
    "image_id", "dcm", "laterality", "view", "acr", "bi_rads",
    "gt_has_individual_microcalcifications", "gt_has_cluster",
    "gt_calcification_rois", "gt_cluster_rois", "gt_calcification_points",
    "cpp_candidates", "cpp_predicted_positive", "presence_result",
    "cpp_localized_hit", "cpp_candidates_on_gt", "cpp_candidates_off_gt",
]
with open(positive_csv, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=positive_fields)
    writer.writeheader()
    writer.writerows({key: row.get(key, "") for key in positive_fields} for row in rows if as_bool(row["gt_has_microcalcifications"]))


def bucket(row):
    n = int(row["gt_calcification_rois"])
    if n == 0 and int(row["gt_cluster_rois"]) > 0:
        return "Solo cluster"
    if n <= 5:
        return "1-5"
    if n <= 10:
        return "6-10"
    if n <= 25:
        return "11-25"
    if n <= 50:
        return "26-50"
    return "51+"


bucket_order = ["1-5", "6-10", "11-25", "26-50", "51+", "Solo cluster"]
bucket_rows = []
positives = [row for row in rows if as_bool(row["gt_has_microcalcifications"])]
for label in bucket_order:
    group = [row for row in positives if bucket(row) == label]
    if not group:
        continue
    predicted_hits = sum(as_bool(row["cpp_predicted_positive"]) for row in group)
    evaluable = [row for row in group if as_bool(row["localized_evaluable"])]
    localized_hits = sum(as_bool(row["cpp_localized_hit"]) for row in evaluable)
    bucket_rows.append({
        "cantidad_gt": label,
        "imagenes": len(group),
        "cpp_positivas": predicted_hits,
        "sensibilidad_presencia": predicted_hits / len(group),
        "imagenes_localizables": len(evaluable),
        "aciertos_localizados": localized_hits,
        "tasa_acierto_localizado": localized_hits / len(evaluable) if evaluable else "",
        "promedio_candidatos_cpp": sum(int(row["cpp_candidates"]) for row in group) / len(group),
    })
with open(bucket_csv, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(bucket_rows[0].keys()))
    writer.writeheader()
    writer.writerows(bucket_rows)

tp = sum(row["presence_result"] == "TP" for row in rows)
tn = sum(row["presence_result"] == "TN" for row in rows)
fp = sum(row["presence_result"] == "FP" for row in rows)
fn = sum(row["presence_result"] == "FN" for row in rows)
pos = tp + fn
neg = tn + fp
individual_rows = [row for row in rows if as_bool(row["gt_has_individual_microcalcifications"])]
localized_hits = sum(as_bool(row["cpp_localized_hit"]) for row in individual_rows)
summary = {
    "total_images": len(rows),
    "gt_positive_combined": pos,
    "gt_positive_individual": len(individual_rows),
    "gt_cluster_images": sum(as_bool(row["gt_has_cluster"]) for row in rows),
    "gt_cluster_only_images": sum(as_bool(row["gt_has_cluster"]) and not as_bool(row["gt_has_individual_microcalcifications"]) for row in rows),
    "gt_negative_combined": neg,
    "gt_calcification_rois": sum(int(row["gt_calcification_rois"]) for row in rows),
    "gt_cluster_rois": sum(int(row["gt_cluster_rois"]) for row in rows),
    "tp": tp, "tn": tn, "fp": fp, "fn": fn,
    "accuracy": (tp + tn) / len(rows),
    "sensitivity_presence": tp / pos,
    "specificity_presence": tn / neg,
    "precision_presence": tp / (tp + fp),
    "f1_presence": 2 * tp / (2 * tp + fp + fn),
    "localized_hits_individual": localized_hits,
    "localized_hit_rate_individual": localized_hits / len(individual_rows),
    "total_cpp_candidates": sum(int(row["cpp_candidates"]) for row in rows),
    "total_cpp_candidates_on_gt": sum(int(row["cpp_candidates_on_gt"]) for row in rows),
    "total_cpp_candidates_off_gt": sum(int(row["cpp_candidates_off_gt"]) for row in rows),
    "cluster_only_ids": [row["image_id"] for row in rows if as_bool(row["gt_has_cluster"]) and not as_bool(row["gt_has_individual_microcalcifications"])],
}
with open(summary_json, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(json.dumps(summary, ensure_ascii=False, indent=2))
print(json.dumps(bucket_rows, ensure_ascii=False, indent=2))
