import argparse
import pathlib
import plistlib

repo_root = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="Audita nombres y conteos de ROI en los XML de INbreast")
parser.add_argument("--dataset", type=pathlib.Path, default=repo_root / "data" / "INbreast Release 1.0")
args = parser.parse_args()
base = args.dataset / "AllXML"
calc = set()
cluster = set()
all_names = {}
for path in sorted(base.glob("*.xml")):
    with open(path, "rb") as f:
        data = plistlib.load(f)
    names = []
    for image in data.get("Images", []):
        for roi in image.get("ROIs", []):
            name = str(roi.get("Name", "")).strip()
            names.append(name)
            all_names[name] = all_names.get(name, 0) + 1
            if "calcification" in name.lower():
                calc.add(path.stem)
            if name.lower() == "cluster":
                cluster.add(path.stem)
print("imagenes_calcification", len(calc))
print("imagenes_cluster", len(cluster))
print("ambas", len(calc & cluster))
print("solo_cluster", sorted(cluster - calc))
print("solo_calcification", len(calc - cluster))
print("nombres", all_names)
