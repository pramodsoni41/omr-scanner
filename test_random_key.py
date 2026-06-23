# -*- coding: utf-8 -*-
"""
Random-key test: build a random answer key + random student responses, fill a
sheet, fake a phone photo, grade against the random key, and verify the
reader's tally matches ground truth computed independently.
"""
import os
import random
import cv2

from omr_generator import generate_omr
from omr_reader import load_template, grade, save_key
from test_loop import fill_sheet, fake_photo

OUT = "test_out"
N_Q = 100
OPTIONS = "ABCD"
SEED = random.randrange(1_000_000)      # fresh each run; printed for repeatability


def main():
    random.seed(SEED)
    os.makedirs(OUT, exist_ok=True)
    print(f"seed = {SEED}")

    info = generate_omr(n_questions=N_Q, n_options=4, roll_digits=10, n_sets=4,
                        serial="00000777", out_dir=OUT,
                        title="IIT (BHU) - OMR ANSWER SHEET")
    template = load_template(info["template"])

    # ---- random answer key for ALL sets, saved to xlsx + csv -------------- #
    set_label = random.choice("ABCD")
    keys_by_set = {s: {q: random.choice(OPTIONS) for q in range(1, N_Q + 1)}
                   for s in "ABCD"}
    key = keys_by_set[set_label]                 # the set this student used

    key_xlsx = os.path.join(OUT, "KEY_00000777.xlsx")
    key_csv = os.path.join(OUT, "KEY_00000777.csv")
    save_key(key_xlsx, keys_by_set, N_Q)
    save_key(key_csv, keys_by_set, N_Q)
    print(f"key saved : {key_xlsx}  (+ .csv)")

    # ---- random student responses + independent ground truth -------------- #
    student = {}
    exp_correct = exp_incorrect = exp_blank = 0
    for q in range(1, N_Q + 1):
        roll = random.random()
        if roll < 0.05:                              # 5% blank
            exp_blank += 1
            continue
        if roll < 0.80:                              # 75% mark the key
            student[q] = key[q]
            exp_correct += 1
        else:                                        # 20% mark a wrong option
            wrong = random.choice([o for o in OPTIONS if o != key[q]])
            student[q] = wrong
            exp_incorrect += 1

    roll_no = "".join(random.choice("0123456789") for _ in range(10))

    filled = fill_sheet(info["png"], template, roll_no, set_label, student)
    photo = fake_photo(filled)

    # grade straight from the saved xlsx; set is auto-detected from the sheet
    res, annot = grade(photo, template, key=key_xlsx,
                       marks_correct=1, marks_incorrect=-0.25, marks_unattempted=0)
    cv2.imwrite(os.path.join(OUT, "graded_random.jpg"), annot)

    exp_marks = exp_correct - 0.25 * exp_incorrect
    print("\n=== RANDOM-KEY RESULT ===")
    print(f"roll      : {res['roll']}   (expected {roll_no})")
    print(f"set       : {res['set']}   (expected {set_label})")
    print(f"correct   : {res['correct']:3d}   (expected {exp_correct})")
    print(f"incorrect : {res['incorrect']:3d}   (expected {exp_incorrect})")
    print(f"blank     : {res['unattempted']:3d}   (expected {exp_blank})")
    print(f"marks     : {res['total_marks']}   (expected {exp_marks})")

    ok = (res["roll"] == roll_no and res["set"] == set_label and
          res["correct"] == exp_correct and res["incorrect"] == exp_incorrect and
          res["unattempted"] == exp_blank and
          abs(res["total_marks"] - exp_marks) < 1e-6)
    print("\nPASS" if ok else "\nFAIL")
    return ok


if __name__ == "__main__":
    main()
