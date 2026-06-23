# -*- coding: utf-8 -*-
"""
Prove QR-based template auto-selection:
put two different designs in one folder, photograph a filled sheet of ONE of
them, and grade by pointing only at the folder (no explicit template path).
"""
import os
import cv2

from omr_generator import generate_omr
from omr_reader import load_template, grade_file
from test_loop import fill_sheet, fake_photo

DIR = "auto_test"


def main():
    os.makedirs(DIR, exist_ok=True)
    # two distinct designs in the SAME folder
    a = generate_omr(n_questions=100, roll_digits=10, n_sets=4, serial="00000007",
                     out_dir=DIR, name="EXAM_A_100q")
    generate_omr(n_questions=40, roll_digits=8, n_sets=2, serial="00000007",
                 out_dir=DIR, name="EXAM_B_40q")

    # fill a 100q sheet (design A) and fake a phone photo
    tA = load_template(a["template"])
    roll, set_label = "0123456789", "C"
    answers = {q: "ABCD"[(q - 1) % 4] for q in range(1, 101)}
    photo = fake_photo(fill_sheet(a["png"], tA, roll, set_label, answers))
    photo_path = os.path.join(DIR, "scan_of_A.jpg")
    cv2.imwrite(photo_path, photo)

    key = {set_label: answers}
    # NOTE: we pass the DIRECTORY, not a specific template.json
    res, _ = grade_file(photo_path, DIR, key,
                        marks_correct=1, marks_incorrect=0)

    print("scan was design A (100q). Auto-resolution result:")
    print("  serial detected :", res.get("SERIAL"))
    print("  roll            :", res["roll"], "(expected 0123456789)")
    print("  set             :", res["set"], "(expected C)")
    print("  correct         :", res["correct"], "(expected 100)")
    ok = (res["roll"] == roll and res["set"] == set_label and res["correct"] == 100)
    print("\nPASS" if ok else "\nFAIL")


if __name__ == "__main__":
    main()
