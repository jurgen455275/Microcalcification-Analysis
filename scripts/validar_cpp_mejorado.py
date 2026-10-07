import argparse
import csv
import ctypes
import json
import pathlib
import time

import numpy as np

import validacion_inbreast as base

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="Evalúa los dos modos del C++ mejorado")
parser.add_argument("--dataset", type=pathlib.Path, default=REPO_ROOT / "data" / "INbreast Release 1.0")
parser.add_argument("--dll", type=pathlib.Path, default=REPO_ROOT / "bin" / "windows" / "deform_inbreast_mejorado.dll")
parser.add_argument("--results", type=pathlib.Path, default=REPO_ROOT / "results")
args = parser.parse_args()
DATA = args.dataset
OUTDIR = args.results
OUTDIR.mkdir(parents=True, exist_ok=True)
DLL = args.dll
CSV_OUT = OUTDIR / "verificacion_cpp_mejorado_por_imagen.csv"
JSON_OUT = OUTDIR / "comparacion_tres_algoritmos.json"

lib = ctypes.CDLL(str(DLL))
fn = lib.analyze_inbreast_mejorado
fn.argtypes = [
    ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8),
    ctypes.c_uint32, ctypes.c_uint32, ctypes.c_float,
    ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64),
    ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_double),
]
fn.restype = ctypes.c_int

rows = []
dicoms = sorted((DATA / "AllDICOMs").glob("*.dcm"))
started = time.time()
for index, dcm in enumerate(dicoms, 1):
    image_id = dcm.stem.split("_")[0]
    image, spacing, laterality, view, _ = base.load_inbreast_dicom(str(dcm))
    image = np.ascontiguousarray(image, dtype=np.float32)
    mask = np.ascontiguousarray(base.breast_mask_and_pectoral_removal(image), dtype=np.uint8)
    gt = base.load_gt_mask_inbreast(str(DATA / "AllXML" / f"{image_id}.xml"), image.shape)
    individual = gt is not None
    combined = individual or image_id in {"20587054", "20587080"}
    gt_array = np.ascontiguousarray(gt, dtype=np.uint8) if gt is not None else None
    gt_ptr = gt_array.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)) if gt_array is not None else None
    thresholds = (ctypes.c_double * 2)()
    candidates = (ctypes.c_uint64 * 2)()
    tp = (ctypes.c_uint64 * 2)()
    fp = (ctypes.c_uint64 * 2)()
    detected = (ctypes.c_int * 2)()
    elapsed = ctypes.c_double()
    rc = fn(
        image.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        mask.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)), gt_ptr,
        image.shape[0], image.shape[1], spacing,
        thresholds, candidates, tp, fp, detected, ctypes.byref(elapsed),
    )
    if rc != 0:
        raise RuntimeError(f"C++ mejorado devolvio {rc} en {image_id}")
    for mode_index, mode in enumerate(("balanced", "sensitive")):
        min_candidates = 3 if mode == "balanced" else 1
        predicted = candidates[mode_index] >= min_candidates
        if combined and predicted: result = "TP"
        elif combined: result = "FN"
        elif predicted: result = "FP"
        else: result = "TN"
        rows.append({
            "image_id": image_id, "dcm": dcm.stem, "laterality": laterality, "view": view,
            "mode": mode, "gt_positive": combined, "gt_individual": individual,
            "threshold": thresholds[mode_index], "candidates": int(candidates[mode_index]),
            "candidate_tp": int(tp[mode_index]), "candidate_fp": int(fp[mode_index]),
            "localized_hit": bool(detected[mode_index]), "predicted_positive": predicted,
            "presence_result": result, "time_ms_dual": elapsed.value,
        })
    if index == 1 or index % 20 == 0 or index == len(dicoms):
        print(f"PROGRESO {index}/{len(dicoms)} ({time.time()-started:.1f}s)", flush=True)

with open(CSV_OUT, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)

summary = {}
for mode in ("balanced", "sensitive"):
    group = [r for r in rows if r["mode"] == mode]
    tp_i = sum(r["presence_result"] == "TP" for r in group)
    tn_i = sum(r["presence_result"] == "TN" for r in group)
    fp_i = sum(r["presence_result"] == "FP" for r in group)
    fn_i = sum(r["presence_result"] == "FN" for r in group)
    cand_tp = sum(r["candidate_tp"] for r in group)
    cand_fp = sum(r["candidate_fp"] for r in group)
    localized = sum(r["localized_hit"] for r in group if r["gt_individual"])
    summary[mode] = {
        "tp": tp_i, "tn": tn_i, "fp": fp_i, "fn": fn_i,
        "precision_presence": tp_i / (tp_i + fp_i) if tp_i + fp_i else 0,
        "sensitivity_presence": tp_i / (tp_i + fn_i) if tp_i + fn_i else 0,
        "specificity_presence": tn_i / (tn_i + fp_i) if tn_i + fp_i else 0,
        "accuracy": (tp_i + tn_i) / len(group) if group else 0,
        "localized_images": localized,
        "localized_rate": localized / 313,
        "total_candidates": cand_tp + cand_fp,
        "candidate_tp": cand_tp, "candidate_fp": cand_fp,
        "candidate_precision": cand_tp / (cand_tp + cand_fp) if cand_tp + cand_fp else 0,
        "fp_candidates_per_image": cand_fp / 410,
        "mean_time_ms_dual": sum(r["time_ms_dual"] for r in group) / len(group),
    }
with open(JSON_OUT, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(json.dumps(summary, ensure_ascii=False, indent=2))
