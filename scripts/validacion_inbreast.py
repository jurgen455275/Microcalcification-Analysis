import argparse
import os, glob, csv, sys
from pathlib import Path
import numpy as np
import cv2
import pydicom
import xml.etree.ElementTree as ET
import pandas as pd
import plistlib
import re

# ==================== CONFIG ====================
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / 'data' / 'INbreast Release 1.0'
PATH_DICOM = str(DEFAULT_DATASET / 'AllDICOMs')
PATH_XML = str(DEFAULT_DATASET / 'AllXML')
PATH_XLS = str(DEFAULT_DATASET / 'INbreast.xls')
PATH_OUT = str(REPO_ROOT / 'results')
K_RANGE = [10,15,20,25,30,40,50,60,70]

# ==================== PASO 2: LECTOR DICOM 14-bit CON WINDOWING ====================
def load_inbreast_dicom(dcm_path):
    ds = pydicom.dcmread(dcm_path)
    img = ds.pixel_array.astype(np.float32) # 14-bit 0-16383
    try:
        wc = ds.WindowCenter
        ww = ds.WindowWidth
        if isinstance(wc, pydicom.multival.MultiValue): wc = float(wc[0])
        else: wc = float(wc)
        if isinstance(ww, pydicom.multival.MultiValue): ww = float(ww[0])
        else: ww = float(ww)
    except:
        wc = float(np.median(img))
        ww = float(img.max() - img.min())
    img = (img - (wc - ww/2.0)) / ww
    img = np.clip(img, 0, 1)
    try: spacing = float(ds.ImagerPixelSpacing[0])
    except: spacing = 0.07
    laterality = getattr(ds, 'ImageLaterality', 'U')
    view = getattr(ds, 'ViewPosition', 'U')
    return img, spacing, laterality, view, ds

# ==================== PASO 3: PARSER XML MASCARA GT EXACTA ====================
def load_gt_mask_inbreast(xml_path, img_shape):
    import plistlib
    import re

    mask = np.zeros(img_shape, dtype=np.uint8)

    if not os.path.exists(xml_path):
        return None

    try:
        with open(xml_path, 'rb') as f:
            data = plistlib.load(f)

        found_calc = False

        images = data.get('Images', [])

        for image_data in images:
            rois = image_data.get('ROIs', [])

            for roi in rois:
                name = str(roi.get('Name', '')).lower()

                # Solo queremos calcificaciones
                if 'calcification' not in name:
                    continue

                found_calc = True

                point_strings = roi.get('Point_px', [])
                pts = []

                for point_str in point_strings:
                    # Formato:
                    # "(2964.620117, 3427.979980)"
                    match = re.match(
                        r'\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)',
                        str(point_str)
                    )

                    if match:
                        x = int(round(float(match.group(1))))
                        y = int(round(float(match.group(2))))

                        # Verificar límites de la imagen
                        if 0 <= x < img_shape[1] and 0 <= y < img_shape[0]:
                            pts.append([x, y])

                if len(pts) == 1:
                    # Calcificación anotada como punto
                    x, y = pts[0]
                    mask[y, x] = 255

                elif len(pts) == 2:
                    # ROI de dos puntos
                    pts_np = np.array(pts, dtype=np.int32)
                    cv2.line(
                        mask,
                        tuple(pts_np[0]),
                        tuple(pts_np[1]),
                        255,
                        1
                    )

                elif len(pts) >= 3:
                    # ROI poligonal
                    pts_np = np.array(pts, dtype=np.int32)
                    cv2.fillPoly(mask, [pts_np], 255)

        if not found_calc:
            return None

        return mask if np.count_nonzero(mask) > 0 else None

    except Exception as e:
        print(f"Error XML {xml_path}: {e}")
        return None

# ==================== PASO 4: MASCARA DE MAMA ====================
def breast_mask_and_pectoral_removal(img):
    img_u8 = (img*255).astype(np.uint8)
    _, thresh = cv2.threshold(img_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(thresh, connectivity=8)
    if num_labels <= 1:
        return np.ones_like(img_u8, dtype=bool)
    largest = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    breast = (labels == largest)
    breast_u8 = breast.astype(np.uint8)*255
    breast_u8 = cv2.morphologyEx(breast_u8, cv2.MORPH_CLOSE, np.ones((25,25), np.uint8))
    return breast_u8.astype(bool)

# ==================== PASO 5: MAPA DE DEFORMACION ====================
def deformation_map_inbreast(img):
    Is = cv2.GaussianBlur(img, (3,3), 0)
    gx = cv2.Sobel(Is, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(Is, cv2.CV_32F, 0, 1, ksize=3)
    gxx = cv2.GaussianBlur(gx*gx, (7,7), 2)
    gyy = cv2.GaussianBlur(gy*gy, (7,7), 2)
    gxy = cv2.GaussianBlur(gx*gy, (7,7), 2)
    tr = gxx + gyy
    det = np.sqrt((gxx-gyy)**2 + 4*(gxy**2))
    coh = det / (tr + 1e-6)
    coh = np.clip(coh, 0, 1)
    energy = tr / (tr.max() + 1e-6)
    deform = (1.0 - coh) * energy
    deform = deform / (deform.max() + 1e-6)
    return deform, coh, energy

# ==================== PASO 6 y 7 ====================
def adaptive_threshold_inbreast(deform, breast_mask, k):
    vals = deform[breast_mask]
    mean = np.mean(vals); std = np.std(vals)
    thresh = mean + k*std
    if thresh > 0.95: thresh = 0.95
    return thresh, mean, std

def extract_candidates_inbreast(deform, thresh, spacing, area_min_mm2=0.01, area_max_mm2=1.0):
    binary = (deform > thresh).astype(np.uint8)*255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area_min_px = area_min_mm2 / (spacing**2)
    area_max_px = area_max_mm2 / (spacing**2)
    candidates = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area_min_px < area < area_max_px:
            M = cv2.moments(cnt)
            if M['m00']!= 0:
                cx = int(M['m10']/M['m00']); cy = int(M['m01']/M['m00'])
                candidates.append((cx,cy,area))
    return candidates, binary

def evaluate_inbreast(candidates, gt_mask):
    if gt_mask is None:
        return 0, len(candidates), False
    gt_bool = gt_mask > 0
    tp = fp = 0
    for (cx,cy,_) in candidates:
        y_min = max(0, cy-5); y_max = min(gt_mask.shape[0], cy+6)
        x_min = max(0, cx-5); x_max = min(gt_mask.shape[1], cx+6)
        if np.any(gt_bool[y_min:y_max, x_min:x_max]): tp+=1
        else: fp+=1
    detected = tp>0
    return tp, fp, detected

# ==================== PASO 1 y 9: VERIFICACION + LOOP MAESTRO ====================
def main():
    global PATH_DICOM, PATH_XML, PATH_XLS, PATH_OUT, K_RANGE
    parser = argparse.ArgumentParser(description='Validación Python del detector sobre INbreast')
    parser.add_argument('--dataset', type=Path, default=DEFAULT_DATASET)
    parser.add_argument('--output', type=Path, default=REPO_ROOT / 'results')
    parser.add_argument('--k-values', default=','.join(str(k) for k in K_RANGE),
                        help='Valores de k separados por comas')
    args = parser.parse_args()
    PATH_DICOM = str(args.dataset / 'AllDICOMs')
    PATH_XML = str(args.dataset / 'AllXML')
    PATH_XLS = str(args.dataset / 'INbreast.xls')
    PATH_OUT = str(args.output)
    K_RANGE = [float(value.strip()) for value in args.k_values.split(',') if value.strip()]
    os.makedirs(PATH_OUT, exist_ok=True)
    if not Path(PATH_DICOM).is_dir() or not Path(PATH_XML).is_dir():
        raise FileNotFoundError(
            f'Dataset incompleto en {args.dataset}. Se requieren AllDICOMs y AllXML.'
        )
    dcm_files = glob.glob(os.path.join(PATH_DICOM, '*.dcm'))
    print(f"Total DICOMs encontrados: {len(dcm_files)} (esperado 410)")
    if os.path.exists(PATH_XLS):
        try:
            df = pd.read_excel(PATH_XLS)
            print(df['Bi-Rads'].value_counts() if 'Bi-Rads' in df.columns else df.head())
        except Exception as e: print(f"No se pudo leer XLS: {e}")

    out_csv = os.path.join(PATH_OUT, 'froc_inbreast.csv')
    with open(out_csv,'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['dcm','spacing','k','mean','std','thresh','num_candidates','tp','fp','detected','has_calc','laterality','view','image_id'])
        for dcm_path in dcm_files:
            base = os.path.splitext(os.path.basename(dcm_path))[0]

            image_id = base.split('_')[0]

            xml_path = os.path.join(PATH_XML, image_id + '.xml')
            try:
                img, spacing, lat, view, ds = load_inbreast_dicom(dcm_path)
                breast_mask = breast_mask_and_pectoral_removal(img)
                deform, coh, energy = deformation_map_inbreast(img)
                gt_mask = load_gt_mask_inbreast(xml_path, img.shape)
                has_calc = gt_mask is not None
                for k in K_RANGE:
                    thresh, mean, std = adaptive_threshold_inbreast(deform, breast_mask, k)
                    cands, binary = extract_candidates_inbreast(deform, thresh, spacing)
                    tp, fp, detected = evaluate_inbreast(cands, gt_mask)
                    writer.writerow([base, spacing, k, mean, std, thresh, len(cands), tp, fp, detected, has_calc, lat, view, image_id])
                    print(f"{base} [{lat}-{view}] k={k} thr={thresh:.3f} TP={tp} FP={fp} det={detected} has_calc={has_calc}")
            except Exception as e:
                print(f"ERROR en {base}: {e}")
                continue
    print(f"\nListo. CSV en {out_csv}")

if __name__ == "__main__":
    main()
