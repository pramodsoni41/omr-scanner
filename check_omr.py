# -*- coding: utf-8 -*-
"""
check_omr.py  -  Steps 3 & 4 of the OMR workflow.

Place this file (or run it) from inside the exam folder, e.g.:
    cd EXAM2026
    python check_omr.py

Expected folder layout:
    <exam_folder>/
        exam_config.json            <- created by generate_exam.py
        <name>.template.json        <- created by generate_exam.py
        answer_key.xlsx  (or .csv)  <- filled in by teacher
        scans/
            student1.jpg
            student2.jpg
            ...
        scan_checked/               <- annotated output (auto-created)
        results.xlsx                <- grading summary (auto-created)

The script reads exam_config.json for the marking scheme, auto-locates the
template and answer key, grades every image in scans/, writes annotated images
to scan_checked/, and produces results.xlsx + results.csv.
"""

import os
import sys
import json
import glob
import time
import cv2

# ---- allow running from either the exam folder or the app root ------------- #
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# If run from inside an exam folder, the OMR library lives one level up.
_PARENT    = os.path.dirname(_THIS_DIR)
for _p in (_THIS_DIR, _PARENT):
    if os.path.exists(os.path.join(_p, "omr_reader.py")):
        if _p not in sys.path:
            sys.path.insert(0, _p)
        break

from omr_reader import grade_file, load_template  # noqa: E402

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}


# ---------------------------------------------------------------------------- #
def find_file(directory, extensions_or_names, label):
    """Return first match; raise if not found."""
    candidates = []
    for item in os.listdir(directory):
        lower = item.lower()
        if any(lower.endswith(e) or lower == e for e in extensions_or_names):
            candidates.append(os.path.join(directory, item))
    if not candidates:
        raise FileNotFoundError(
            f"No {label} found in {directory}\n"
            f"  Expected one of: {extensions_or_names}"
        )
    if len(candidates) > 1:
        print(f"  [warn] Multiple {label} files found; using: {candidates[0]}")
    return candidates[0]


def load_config(exam_dir):
    cfg_path = os.path.join(exam_dir, "exam_config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path) as fh:
            return json.load(fh)
    return {}


# ---------------------------------------------------------------------------- #
def main():
    exam_dir = _THIS_DIR          # script lives inside the exam folder
    print("=" * 62)
    print("  OMR Batch Checker")
    print(f"  Exam folder: {exam_dir}")
    print("=" * 62)

    # ---- load config -------------------------------------------------------- #
    config = load_config(exam_dir)
    scheme = config.get("marking_scheme", {})
    marks_correct     = float(scheme.get("marks_correct", 1.0))
    marks_incorrect   = float(scheme.get("marks_incorrect", 0.0))
    marks_unattempted = float(scheme.get("marks_unattempted", 0.0))

    print(f"  Marking scheme: +{marks_correct} / {marks_incorrect} / {marks_unattempted}")

    # ---- locate template ---------------------------------------------------- #
    tmpl_path = find_file(exam_dir, [".template.json"], "template JSON")
    template  = load_template(tmpl_path)
    print(f"  Template      : {os.path.basename(tmpl_path)}")

    # ---- locate answer key -------------------------------------------------- #
    # prefer explicit names first, then fall back to any xlsx/csv that is NOT
    # a manifest or results file
    _key_path = None
    for _name in ("answer_key.xlsx", "answer_key.csv"):
        _candidate = os.path.join(exam_dir, _name)
        if os.path.exists(_candidate):
            _key_path = _candidate
            break
    if _key_path is None:
        for _f in sorted(os.listdir(exam_dir)):
            _lower = _f.lower()
            if (_lower.endswith(".xlsx") or _lower.endswith(".csv")) and \
               "manifest" not in _lower and "result" not in _lower:
                _key_path = os.path.join(exam_dir, _f)
                break
    if _key_path is None:
        raise FileNotFoundError(f"No answer key (answer_key.xlsx / .csv) found in {exam_dir}")
    key_path = _key_path
    print(f"  Answer key    : {os.path.basename(key_path)}")

    # ---- locate scans ------------------------------------------------------- #
    scans_dir = os.path.join(exam_dir, "scans")
    if not os.path.isdir(scans_dir):
        print(f"\nERROR: 'scans' folder not found at {scans_dir}")
        print("  Create the folder and paste student scan photos into it.")
        sys.exit(1)

    image_files = sorted([
        f for f in glob.glob(os.path.join(scans_dir, "*"))
        if os.path.splitext(f)[1].lower() in IMAGE_EXTS
    ])
    if not image_files:
        print(f"\nNo image files found in {scans_dir}")
        print("  Supported formats: " + ", ".join(sorted(IMAGE_EXTS)))
        sys.exit(1)

    print(f"  Scans found   : {len(image_files)}")

    # ---- output folder ------------------------------------------------------ #
    checked_dir = os.path.join(exam_dir, "scan_checked")
    os.makedirs(checked_dir, exist_ok=True)

    # ---- grade each scan ---------------------------------------------------- #
    print()
    print(f"  {'FILE':<30} {'ROLL':<14} {'SET':<5} {'C':>4} {'X':>4} {'U':>4} {'MARKS':>7}  STATUS")
    print("  " + "-" * 78)

    results = []
    t0 = time.time()

    for img_path in image_files:
        fname = os.path.basename(img_path)
        try:
            res, annot = grade_file(
                img_path, template, key_path,
                marks_correct=marks_correct,
                marks_incorrect=marks_incorrect,
                marks_unattempted=marks_unattempted,
            )
        except Exception as exc:
            print(f"  {fname:<30} ERROR: {exc}")
            results.append({
                "file": fname, "roll": "", "set": "", "correct": "",
                "incorrect": "", "unattempted": "", "total_marks": "",
                "status": f"ERROR: {exc}",
            })
            continue

        status = "OK" if res["ok"] else f"FAIL: {res.get('error', '?')}"
        print(f"  {fname:<30} {str(res['roll']):<14} {str(res.get('set','')):<5}"
              f" {res['correct']:>4} {res['incorrect']:>4} {res['unattempted']:>4}"
              f" {res['total_marks']:>7.2f}  {status}")

        # save annotated image
        out_name = os.path.splitext(fname)[0] + "_checked.jpg"
        cv2.imwrite(os.path.join(checked_dir, out_name), annot,
                    [cv2.IMWRITE_JPEG_QUALITY, 92])

        results.append({
            "file": fname,
            "serial": res.get("SERIAL", ""),
            "roll": res["roll"],
            "set": res.get("set", ""),
            "correct": res["correct"],
            "incorrect": res["incorrect"],
            "unattempted": res["unattempted"],
            "total_marks": res["total_marks"],
            "status": status,
        })

    elapsed = time.time() - t0
    print()
    print(f"  Processed {len(image_files)} sheets in {elapsed:.1f}s")

    # ---- export results ----------------------------------------------------- #
    try:
        import pandas as pd
        df = pd.DataFrame(results)
        xlsx_path = os.path.join(exam_dir, "results.xlsx")
        csv_path  = os.path.join(exam_dir, "results.csv")
        df.to_excel(xlsx_path, index=False)
        df.to_csv(csv_path, index=False)
        print(f"  Results saved : {xlsx_path}")
        print(f"                  {csv_path}")
    except ImportError:
        # pandas not installed — write CSV manually
        import csv
        csv_path = os.path.join(exam_dir, "results.csv")
        if results:
            with open(csv_path, "w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
                writer.writeheader()
                writer.writerows(results)
        print(f"  Results saved : {csv_path}  (install pandas for .xlsx support)")

    print(f"  Checked images: {checked_dir}")
    print()

    # ---- summary stats ------------------------------------------------------ #
    ok_rows = [r for r in results if r["status"] == "OK"]
    if ok_rows:
        marks_list = [r["total_marks"] for r in ok_rows if r["total_marks"] != ""]
        if marks_list:
            print(f"  Students graded : {len(ok_rows)}")
            print(f"  Average marks   : {sum(marks_list)/len(marks_list):.2f}")
            print(f"  Highest marks   : {max(marks_list):.2f}")
            print(f"  Lowest marks    : {min(marks_list):.2f}")
    failed = [r for r in results if r["status"] != "OK"]
    if failed:
        print(f"  Failed to grade : {len(failed)}")
        for r in failed:
            print(f"    {r['file']}: {r['status']}")
    print()


if __name__ == "__main__":
    main()
