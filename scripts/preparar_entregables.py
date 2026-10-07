import argparse
import csv
import importlib.util
import os
import struct
import time
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pydicom

REPO_ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="Genera resúmenes, FROC, ejemplos y entradas de benchmark")
parser.add_argument("--dataset", type=Path, default=REPO_ROOT / "data" / "INbreast Release 1.0")
parser.add_argument("--results", type=Path, default=REPO_ROOT / "results")
args = parser.parse_args()
DATA = args.dataset
WORK = REPO_ROOT / "build"
OUT = args.results
VIS = REPO_ROOT / "examples"
BENCH = WORK / "benchmark_inputs"
OUT.mkdir(parents=True, exist_ok=True)
VIS.mkdir(parents=True, exist_ok=True)
BENCH.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location("validacion", Path(__file__).with_name("validacion_inbreast.py"))
val = importlib.util.module_from_spec(spec)
spec.loader.exec_module(val)

results = pd.read_csv(OUT / "froc_inbreast.csv")
meta = pd.read_csv(DATA / "INbreast.csv", sep=";")
meta["File Name"] = meta["File Name"].astype(str)
results["image_id"] = results["dcm"].astype(str).str.split("_").str[0]
merged = results.merge(meta, left_on="image_id", right_on="File Name", how="left")
merged["has_calc"] = merged["has_calc"].astype(str).str.lower().eq("true")
merged["detected"] = merged["detected"].astype(str).str.lower().eq("true")
merged["birads_class"] = pd.to_numeric(
    merged["Bi-Rads"].astype(str).str.extract(r"([1-6])", expand=False), errors="coerce"
)

summary_rows = []
acr_rows = []
for k, g in merged.groupby("k", sort=True):
    positives = g[g.has_calc]
    sens = float(positives.detected.mean()) if len(positives) else float("nan")
    fp_img = float(g.fp.sum() / len(g))
    summary_rows.append({
        "k": int(k), "imagenes": len(g), "imagenes_con_calcificaciones": len(positives),
        "imagenes_detectadas": int(positives.detected.sum()), "sensibilidad_imagen": sens,
        "fp_por_imagen": fp_img, "umbral_medio": float(g.thresh.mean())
    })
    for acr, ag in g.groupby("ACR", dropna=False):
        ap = ag[ag.has_calc]
        acr_rows.append({
            "k": int(k), "ACR": acr, "imagenes": len(ag),
            "imagenes_con_calcificaciones": len(ap), "sensibilidad_imagen": float(ap.detected.mean()) if len(ap) else float("nan"),
            "fp_por_imagen": float(ag.fp.sum() / len(ag)), "umbral_medio": float(ag.thresh.mean())
        })
summary = pd.DataFrame(summary_rows)
by_acr = pd.DataFrame(acr_rows)
summary.to_csv(OUT / "resumen_por_k.csv", index=False, float_format="%.6f")
by_acr.to_csv(OUT / "resumen_por_k_y_acr.csv", index=False, float_format="%.6f")
results.to_csv(OUT / "froc_inbreast.csv", index=False)

eligible = summary[summary.fp_por_imagen < 2.0]
k_opt = int((eligible.sort_values(["sensibilidad_imagen", "fp_por_imagen"], ascending=[False, True]).iloc[0]
             if len(eligible) else summary.sort_values("fp_por_imagen").iloc[0]).k)

plt.figure(figsize=(7.4, 5.2), dpi=180)
plt.plot(summary.fp_por_imagen, summary.sensibilidad_imagen, marker="o", linewidth=2, color="#1f4e79")
for _, r in summary.iterrows():
    plt.annotate(f"k={int(r.k)}", (r.fp_por_imagen, r.sensibilidad_imagen), xytext=(5, 4), textcoords="offset points", fontsize=8)
plt.axvline(2.0, color="#b22222", linestyle="--", linewidth=1.2, label="Límite del protocolo: 2 FP/imagen")
plt.axhline(0.75, color="#2e7d32", linestyle="--", linewidth=1.2, label="Meta del protocolo: 75 %")
plt.xlabel("Falsos positivos por imagen")
plt.ylabel("Sensibilidad a nivel de imagen")
plt.title("Curva FROC en INbreast")
plt.grid(alpha=0.25)
plt.legend(fontsize=8)
plt.tight_layout()
plt.savefig(OUT / "froc_inbreast.png", bbox_inches="tight")
plt.close()

gopt = merged[merged.k == k_opt].copy()
priority = []
targets = [(1, "CC"), (1, "MLO"), (4, "CC"), (4, "MLO")]
for acr, view in targets:
    q = gopt[(gopt.birads_class == acr) & (gopt.View == view)].copy()
    if acr == 4:
        q = q.sort_values(["has_calc", "detected", "tp"], ascending=False)
    else:
        q = q.sort_values(["fp"], ascending=True)
    if len(q): priority.append(q.iloc[0])
remaining = gopt[(gopt.birads_class.isin([1, 4])) & ~gopt.dcm.isin([r.dcm for r in priority])].copy()
remaining = remaining.sort_values(["birads_class", "detected", "tp"], ascending=[False, False, False])
for _, r in remaining.iterrows():
    if len(priority) >= 5: break
    priority.append(r)

example_records = []
bench_python = []
for idx, row in enumerate(priority[:5], 1):
    dcm_path = DATA / "AllDICOMs" / f"{row.dcm}.dcm"
    xml_path = DATA / "AllXML" / f"{row.image_id}.xml"
    img, spacing, _, _, _ = val.load_inbreast_dicom(str(dcm_path))
    t0 = time.perf_counter()
    breast = val.breast_mask_and_pectoral_removal(img)
    deform, _, _ = val.deformation_map_inbreast(img)
    thresh, mean, std = val.adaptive_threshold_inbreast(deform, breast, k_opt)
    cands, _ = val.extract_candidates_inbreast(deform, thresh, spacing)
    py_ms = (time.perf_counter() - t0) * 1000.0
    bench_python.append({"archivo": f"{row.image_id}.inbr", "python_ms": py_ms, "python_candidatos": len(cands)})
    gt = val.load_gt_mask_inbreast(str(xml_path), img.shape)

    raw_path = BENCH / f"{row.image_id}.inbr"
    with open(raw_path, "wb") as f:
        f.write(struct.pack("<IIIf", 0x494E4252, img.shape[0], img.shape[1], float(spacing)))
        f.write(np.ascontiguousarray(img, dtype="<f4").tobytes())
        f.write(np.ascontiguousarray(breast, dtype=np.uint8).tobytes())

    raw_pixels = pydicom.dcmread(str(dcm_path)).pixel_array.astype(np.float32)
    display_vals = raw_pixels[raw_pixels > 0]
    lo, hi = np.percentile(display_vals, [1.0, 99.5]) if display_vals.size else (0.0, 1.0)
    base = np.clip((raw_pixels - lo) / max(hi - lo, 1e-6) * 255.0, 0, 255).astype(np.uint8)
    overlay = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)
    if gt is not None:
        gt_vis = cv2.dilate((gt > 0).astype(np.uint8), np.ones((21, 21), np.uint8))
        overlay[gt_vis > 0] = (0, 255, 0)
    for cx, cy, _ in cands:
        cv2.circle(overlay, (int(cx), int(cy)), 14, (0, 0, 255), 3)
    scale = min(1.0, 1600.0 / max(overlay.shape[:2]))
    if scale < 1.0:
        overlay = cv2.resize(overlay, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    label = f"{row.image_id}  ACR {int(row.ACR)}  BI-RADS {row['Bi-Rads']}  {row.Laterality}-{row.View}  k={k_opt}"
    cv2.rectangle(overlay, (0, 0), (overlay.shape[1], 76), (0, 0, 0), -1)
    cv2.putText(overlay, label, (16, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(overlay, "Verde: ground truth    Rojo: deteccion", (16, 61), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (220, 220, 220), 2, cv2.LINE_AA)
    out_img = VIS / f"ejemplo_{idx}_{row.image_id}.png"
    cv2.imwrite(str(out_img), overlay)
    example_records.append({
        "ejemplo": idx, "image_id": row.image_id, "ACR": int(row.ACR), "Bi-Rads": row["Bi-Rads"],
        "laterality": row.Laterality, "view": row.View, "k": k_opt, "detected": bool(row.detected),
        "tp": int(row.tp), "fp": int(row.fp), "archivo": out_img.name
    })

pd.DataFrame(example_records).to_csv(OUT / "indice_ejemplos.csv", index=False)
pd.DataFrame(bench_python).to_csv(WORK / "benchmark_python.csv", index=False, float_format="%.3f")

best = summary.loc[summary.k == k_opt].iloc[0]
comparison = pd.DataFrame([
    {"base": "mini-MIAS", "sensibilidad_imagen": 0.86, "fp_por_imagen": np.nan, "k": np.nan,
     "alcance": "Valor informado en el protocolo; FP/imagen no disponible en los archivos suministrados"},
    {"base": "INbreast", "sensibilidad_imagen": best.sensibilidad_imagen, "fp_por_imagen": best.fp_por_imagen, "k": k_opt,
     "alcance": "410 imágenes; evaluación a nivel de imagen con el CSV generado por Python"}
])
comparison.to_csv(OUT / "comparacion_mini_mias_vs_inbreast.csv", index=False, float_format="%.6f")

with open(WORK / "k_optimo.txt", "w", encoding="utf-8") as f:
    f.write(str(k_opt))
print(f"k_optimo={k_opt}")
print(summary.to_string(index=False))
print(f"Ejemplos: {len(example_records)}")
