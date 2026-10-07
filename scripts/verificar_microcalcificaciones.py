import argparse
import csv
import ctypes
import json
import os
import pathlib
import plistlib
import re
import time

import cv2
import numpy as np
import pydicom


POINT_RE = re.compile(r"\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)")


def load_metadata(csv_path):
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    return {str(row["File Name"]).strip(): row for row in rows}, rows


def parse_xml(xml_path, shape=None):
    roi_count = 0
    point_count = 0
    names = {}
    mask = np.zeros(shape, dtype=np.uint8) if shape else None
    if not xml_path.exists():
        return roi_count, point_count, mask, names
    with open(xml_path, "rb") as f:
        data = plistlib.load(f)
    for image_data in data.get("Images", []):
        for roi in image_data.get("ROIs", []):
            name = str(roi.get("Name", "")).strip()
            names[name] = names.get(name, 0) + 1
            if "calcification" not in name.lower():
                continue
            roi_count += 1
            pts = []
            for raw in roi.get("Point_px", []):
                match = POINT_RE.match(str(raw))
                if not match:
                    continue
                point_count += 1
                if shape:
                    x = int(round(float(match.group(1))))
                    y = int(round(float(match.group(2))))
                    if 0 <= x < shape[1] and 0 <= y < shape[0]:
                        pts.append([x, y])
            if mask is not None:
                if len(pts) == 1:
                    mask[pts[0][1], pts[0][0]] = 255
                elif len(pts) == 2:
                    cv2.line(mask, tuple(pts[0]), tuple(pts[1]), 255, 1)
                elif len(pts) >= 3:
                    cv2.fillPoly(mask, [np.asarray(pts, dtype=np.int32)], 255)
    return roi_count, point_count, mask, names


def load_dicom(path):
    ds = pydicom.dcmread(path)
    image = ds.pixel_array.astype(np.float32)
    try:
        wc = ds.WindowCenter
        ww = ds.WindowWidth
        if isinstance(wc, pydicom.multival.MultiValue):
            wc = float(wc[0])
        else:
            wc = float(wc)
        if isinstance(ww, pydicom.multival.MultiValue):
            ww = float(ww[0])
        else:
            ww = float(ww)
    except Exception:
        wc = float(np.median(image))
        ww = float(image.max() - image.min())
    if ww <= 0:
        ww = 1.0
    image = np.clip((image - (wc - ww / 2.0)) / ww, 0, 1).astype(np.float32)
    try:
        spacing = float(ds.ImagerPixelSpacing[0])
    except Exception:
        spacing = 0.07
    return np.ascontiguousarray(image), spacing


def breast_mask(image):
    image_u8 = (image * 255).astype(np.uint8)
    _, threshold = cv2.threshold(image_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(threshold, connectivity=8)
    if n_labels <= 1:
        return np.ones_like(image_u8, dtype=np.uint8)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    result = (labels == largest).astype(np.uint8) * 255
    result = cv2.morphologyEx(result, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    return np.ascontiguousarray(result)


def load_cpp(dll_path):
    lib = ctypes.CDLL(str(dll_path))
    fn = lib.analyze_inbreast_cpp
    fn.argtypes = [
        ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_float, ctypes.c_double,
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_double),
    ]
    fn.restype = ctypes.c_int
    return fn


def call_cpp(fn, image, mask, gt_mask, spacing, k):
    mean = ctypes.c_double()
    stddev = ctypes.c_double()
    threshold = ctypes.c_double()
    candidates = ctypes.c_uint64()
    tp = ctypes.c_uint64()
    fp = ctypes.c_uint64()
    detected = ctypes.c_int()
    elapsed = ctypes.c_double()
    gt_ptr = gt_mask.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)) if gt_mask is not None else None
    rc = fn(
        image.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        mask.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
        gt_ptr,
        image.shape[0], image.shape[1], spacing, k,
        ctypes.byref(mean), ctypes.byref(stddev), ctypes.byref(threshold),
        ctypes.byref(candidates), ctypes.byref(tp), ctypes.byref(fp),
        ctypes.byref(detected), ctypes.byref(elapsed),
    )
    if rc != 0:
        raise RuntimeError(f"C++ devolvio codigo {rc}")
    return {
        "cpp_mean": mean.value,
        "cpp_std": stddev.value,
        "cpp_threshold": threshold.value,
        "cpp_candidates": int(candidates.value),
        "cpp_candidates_on_gt": int(tp.value),
        "cpp_candidates_off_gt": int(fp.value),
        "cpp_localized_hit": bool(detected.value),
        "cpp_time_ms": elapsed.value,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--dll", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--k", type=float, default=70.0)
    args = parser.parse_args()

    dataset = pathlib.Path(args.dataset)
    output_path = pathlib.Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata, metadata_rows = load_metadata(dataset / "INbreast.csv")
    dicoms = sorted((dataset / "AllDICOMs").glob("*.dcm"))
    cpp_fn = load_cpp(pathlib.Path(args.dll))
    rows = []
    roi_name_counts = {}
    started = time.time()

    for idx, dcm_path in enumerate(dicoms, 1):
        image_id = dcm_path.stem.split("_")[0]
        meta = metadata.get(image_id, {})
        image, spacing = load_dicom(dcm_path)
        mask = breast_mask(image)
        roi_count, point_count, gt_mask, names = parse_xml(dataset / "AllXML" / f"{image_id}.xml", image.shape)
        for name, count in names.items():
            roi_name_counts[name] = roi_name_counts.get(name, 0) + count
        has_calc = roi_count > 0 and gt_mask is not None and bool(np.any(gt_mask))
        cpp = call_cpp(cpp_fn, image, mask, gt_mask if has_calc else None, spacing, args.k)
        predicted = cpp["cpp_candidates"] > 0
        if has_calc and predicted:
            result = "TP"
        elif has_calc and not predicted:
            result = "FN"
        elif not has_calc and predicted:
            result = "FP"
        else:
            result = "TN"
        rows.append({
            "image_id": image_id,
            "dcm": dcm_path.stem,
            "laterality": meta.get("Laterality", ""),
            "view": meta.get("View", ""),
            "acr": meta.get("ACR", ""),
            "bi_rads": meta.get("Bi-Rads", ""),
            "spacing_mm": spacing,
            "gt_has_microcalcifications": has_calc,
            "gt_calcification_rois": roi_count,
            "gt_annotation_points": point_count,
            "k": args.k,
            **cpp,
            "cpp_predicted_positive": predicted,
            "presence_result": result,
            "presence_correct": result in ("TP", "TN"),
        })
        if idx == 1 or idx % 20 == 0 or idx == len(dicoms):
            print(f"PROGRESO {idx}/{len(dicoms)} ({time.time()-started:.1f}s)", flush=True)

    fields = list(rows[0].keys())
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    tp = sum(r["presence_result"] == "TP" for r in rows)
    tn = sum(r["presence_result"] == "TN" for r in rows)
    fp = sum(r["presence_result"] == "FP" for r in rows)
    fn = sum(r["presence_result"] == "FN" for r in rows)
    gt_positive = tp + fn
    gt_negative = tn + fp
    localized_hits = sum(bool(r["cpp_localized_hit"]) for r in rows if r["gt_has_microcalcifications"])
    summary = {
        "metadata_rows": len(metadata_rows),
        "dicom_files": len(dicoms),
        "analyzed_images": len(rows),
        "gt_positive_images": gt_positive,
        "gt_negative_images": gt_negative,
        "gt_calcification_rois": sum(r["gt_calcification_rois"] for r in rows),
        "gt_annotation_points": sum(r["gt_annotation_points"] for r in rows),
        "k": args.k,
        "tp_presence": tp,
        "tn_presence": tn,
        "fp_presence": fp,
        "fn_presence": fn,
        "accuracy": (tp + tn) / len(rows) if rows else None,
        "sensitivity_presence": tp / gt_positive if gt_positive else None,
        "specificity_presence": tn / gt_negative if gt_negative else None,
        "precision_presence": tp / (tp + fp) if tp + fp else None,
        "f1_presence": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        "localized_positive_images": localized_hits,
        "localized_hit_rate": localized_hits / gt_positive if gt_positive else None,
        "total_cpp_candidates": sum(r["cpp_candidates"] for r in rows),
        "total_cpp_candidate_hits": sum(r["cpp_candidates_on_gt"] for r in rows),
        "total_cpp_candidate_false_positives": sum(r["cpp_candidates_off_gt"] for r in rows),
        "mean_cpp_time_ms": sum(r["cpp_time_ms"] for r in rows) / len(rows) if rows else None,
        "roi_name_counts": roi_name_counts,
        "elapsed_seconds": time.time() - started,
    }
    with open(args.summary, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
