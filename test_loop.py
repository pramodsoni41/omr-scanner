# -*- coding: utf-8 -*-
"""
End-to-end self test: generate -> fill -> distort (fake phone photo) -> grade.
Proves the fiducial+template pipeline with no real scan needed.
"""
import os
import json
import numpy as np
import cv2

from omr_generator import generate_omr
from omr_reader import load_template, grade

OUT = "test_out"


def fill_sheet(png_path, template, roll, set_label, answers):
    """Draw solid marks onto a clean sheet at known template coordinates."""
    img = cv2.imread(png_path)
    default_r = template.get("bubble_radius", 20)

    def fill(b):                       # fill at the bubble's own radius
        r = int(b.get("r", default_r) * 0.82)
        cv2.circle(img, (int(b["x"]), int(b["y"])), r, (20, 20, 20), -1)

    for b in template["roll"]:
        if str(roll[b["digit"]]) == str(b["value"]):
            fill(b)
    for s in template["sets"]:
        if s["label"] == set_label:
            fill(s)
    for q in template["questions"]:
        a = answers.get(q["q"])
        if not a:
            continue
        for o in q["options"]:
            if o["label"] in a:
                fill(o)
    return img


def fake_photo(img):
    """Mild perspective + rotation + blur to imitate a phone capture."""
    h, w = img.shape[:2]
    canvas = np.full((int(h * 1.12), int(w * 1.12), 3), 255, np.uint8)
    oy, ox = (canvas.shape[0] - h) // 2, (canvas.shape[1] - w) // 2
    canvas[oy:oy + h, ox:ox + w] = img
    h2, w2 = canvas.shape[:2]
    src = np.float32([[0, 0], [w2, 0], [w2, h2], [0, h2]])
    j = 0.04
    dst = np.float32([[w2 * j, h2 * 0.02], [w2 * (1 - 0.015), h2 * j],
                      [w2 * (1 - j), h2 * (1 - 0.02)], [w2 * 0.02, h2 * (1 - j)]])
    M = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(canvas, M, (w2, h2), borderValue=(255, 255, 255))
    Rm = cv2.getRotationMatrix2D((w2 / 2, h2 / 2), 2.5, 1.0)
    out = cv2.warpAffine(out, Rm, (w2, h2), borderValue=(255, 255, 255))
    return cv2.GaussianBlur(out, (3, 3), 0)


def main():
    os.makedirs(OUT, exist_ok=True)
    info = generate_omr(n_questions=100, n_options=4, roll_digits=10, n_sets=4,
                        serial="00000042", out_dir=OUT,
                        title="IIT (BHU) - OMR ANSWER SHEET")
    template = load_template(info["template"])

    roll = "0123456789"
    set_label = "B"
    # truth answers, cycle A,B,C,D
    truth = {q: "ABCD"[(q - 1) % 4] for q in range(1, 101)}
    # student answers = truth but 12 deliberately wrong + 5 left blank
    student = dict(truth)
    for q in range(5, 5 + 12 * 4, 4):          # 12 wrong
        student[q] = "ABCD"[q % 4]
    for q in (90, 92, 94, 96, 98):             # 5 blank
        student.pop(q, None)

    filled = fill_sheet(info["png"], template, roll, set_label, student)
    photo = fake_photo(filled)
    photo_path = os.path.join(OUT, "fake_scan.jpg")
    cv2.imwrite(photo_path, photo)

    res, annot = grade(photo, template, key={set_label: truth},
                       marks_correct=1, marks_incorrect=-0.25, marks_unattempted=0,
                       set_label=set_label)
    cv2.imwrite(os.path.join(OUT, "graded.jpg"), annot)

    # expected
    exp_wrong = sum(1 for q in truth if q in student and student[q] != truth[q])
    exp_blank = sum(1 for q in truth if q not in student)
    exp_correct = 100 - exp_wrong - exp_blank

    print("=== RESULT ===")
    print("roll detected :", res["roll"], "(expected 0123456789)")
    print("set  detected :", res["set"], "(expected B)")
    print(f"correct  : {res['correct']:3d}  (expected {exp_correct})")
    print(f"incorrect: {res['incorrect']:3d}  (expected {exp_wrong})")
    print(f"blank    : {res['unattempted']:3d}  (expected {exp_blank})")
    print("marks    :", res["total_marks"])

    okroll = res["roll"] == roll
    okset = res["set"] == set_label
    okscore = (res["correct"] == exp_correct and res["incorrect"] == exp_wrong
               and res["unattempted"] == exp_blank)
    print("\nPASS" if (okroll and okset and okscore) else "\nFAIL",
          "| roll", okroll, "| set", okset, "| score", okscore)


if __name__ == "__main__":
    main()
