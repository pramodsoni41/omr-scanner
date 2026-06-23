# -*- coding: utf-8 -*-
"""
End-to-end test of the OMR backend, simulating what the phone app will do:
    generate -> download sheet -> upload key -> upload a (fake) scan -> get marks
"""
import io
import os
import sys
import cv2
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from omr_generator import generate_omr
from omr_reader import load_template, save_key
from test_loop import fill_sheet, fake_photo

BASE = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("OMR_BASE")
        or "http://127.0.0.1:8000").rstrip("/")
TMP = "client_tmp"


def main():
    os.makedirs(TMP, exist_ok=True)

    # 1) app user inputs exam settings -> server generates sheets
    params = dict(n_questions=100, n_options=4, roll_digits=10, n_sets=4,
                  questions_per_column=25, n_sheets=3, start_serial=1,
                  title="IIT (BHU) - OMR")
    r = requests.post(f"{BASE}/generate", json=params, timeout=60)
    r.raise_for_status()
    info = r.json()
    exam_id = info["exam_id"]
    print("1) generated exam:", exam_id, "| sheets:", info["n_sheets"])

    # 2) download the printable PDF (app would show/print/share it)
    pdf = requests.get(f"{BASE}{info['sheets_pdf']}", timeout=60)
    open(os.path.join(TMP, "sheets.pdf"), "wb").write(pdf.content)
    print("2) downloaded sheets.pdf:", len(pdf.content), "bytes")

    # 3) build + upload an answer key (all 4 sets)
    truth = {q: "ABCD"[(q - 1) % 4] for q in range(1, 101)}
    keys_by_set = {s: truth for s in "ABCD"}
    key_path = os.path.join(TMP, "key.xlsx")
    save_key(key_path, keys_by_set, 100)
    with open(key_path, "rb") as fh:
        r = requests.post(f"{BASE}/exams/{exam_id}/key",
                          files={"file": ("key.xlsx", fh)}, timeout=30)
    r.raise_for_status()
    print("3) uploaded key:", r.json())

    # 4) make a fake filled+photographed scan (same geometry as the server's sheet)
    local = generate_omr(n_questions=100, n_options=4, roll_digits=10, n_sets=4,
                         questions_per_column=25, serial="00000001",
                         out_dir=TMP, name="local_for_scan")
    tmpl = load_template(local["template"])
    student = dict(truth)
    for q in (10, 20, 30):              # 3 deliberately wrong
        student[q] = "ABCD"[q % 4]
    photo = fake_photo(fill_sheet(local["png"], tmpl, "0481234567", "C", student))
    ok, buf = cv2.imencode(".jpg", photo)

    # 5) upload scan -> grade
    r = requests.post(f"{BASE}/exams/{exam_id}/grade",
                      files={"files": ("scan1.jpg", io.BytesIO(buf.tobytes()), "image/jpeg")},
                      data={"marks_correct": 1, "marks_incorrect": -0.25},
                      timeout=60)
    r.raise_for_status()
    out = r.json()
    res = out["results"][0]
    print("5) graded -> roll:", res["roll"], "| set:", res["set"],
          "| correct:", res["correct"], "| incorrect:", res["incorrect"],
          "| marks:", res["total_marks"])
    print("   marksheet:", out["marksheet"], "| annotated:", res["graded_image"])

    expect_ok = (res["roll"] == "0481234567" and res["set"] == "C"
                 and res["correct"] == 97 and res["incorrect"] == 3)
    print("\nPASS" if expect_ok else "\nFAIL")


if __name__ == "__main__":
    main()
