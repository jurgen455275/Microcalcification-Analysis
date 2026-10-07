import argparse
from collections import Counter
from pathlib import Path
import pydicom
import numpy as np

repo_root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="Audita etiquetas DICOM relevantes de INbreast")
parser.add_argument("--dataset", type=Path, default=repo_root / "data" / "INbreast Release 1.0")
args = parser.parse_args()
root = args.dataset / "AllDICOMs"
files = sorted(root.glob("*.dcm"))
tags = Counter()
photo = Counter()
lut = Counter()
bits = Counter()
for path in files:
    ds = pydicom.dcmread(path, stop_before_pixels=True)
    tags[("WindowCenter" in ds, "WindowWidth" in ds)] += 1
    photo[str(getattr(ds, "PhotometricInterpretation", "missing"))] += 1
    lut[str(getattr(ds, "PresentationLUTShape", "missing"))] += 1
    bits[(getattr(ds, "BitsStored", None), getattr(ds, "BitsAllocated", None))] += 1
print("files", len(files))
print("window_tags", tags)
print("photometric", photo)
print("presentation_lut", lut)
print("bits", bits)
for path in files[:3]:
    ds = pydicom.dcmread(path)
    img = ds.pixel_array.astype(np.float32)
    wc = float(np.median(img))
    ww = float(img.max() - img.min())
    bg = (float(img.min()) - (wc - ww/2)) / ww if ww else 0
    print(path.name, "min", float(img.min()), "median", wc, "max", float(img.max()), "fallback_min_maps_to", bg)
