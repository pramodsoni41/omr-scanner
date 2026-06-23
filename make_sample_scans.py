# -*- coding: utf-8 -*-
"""
make_sample_scans.py  -  Populate an exam's scans/ folder with fake but
realistic filled-OMR images (useful for demos and testing).

Usage:
    python make_sample_scans.py EXAM2026_T1

The script:
  1. Reads exam_config.json from the exam folder.
  2. Re-renders blank sheets using the same design parameters.
  3. Fills each sheet with a simulated student response:
       - unique roll number
       - randomly assigned set
       - answers drawn from the answer key with realistic accuracy
         (~70% correct, ~20% wrong, ~10% blank)
  4. Applies a mild perspective+rotation+blur to simulate a phone photo.
  5. Saves JPEG files to <exam_folder>/scans/student_NNNN.jpg
"""

import os, sys, json, random
import numpy as np
import cv2

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from omr_generator import _build_sheet
from omr_reader import load_key


# ---------------------------------------------------------------------------- #
def fill_sheet(img_bgr, template, roll_str, set_label, answers):
    """Paint solid dark circles at the chosen bubble positions."""
    img = img_bgr.copy()
    default_r = template.get("bubble_radius", 20)

    def mark(b):
        r = int(b.get("r", default_r) * 0.80)
        cv2.circle(img, (int(b["x"]), int(b["y"])), r, (18, 18, 18), -1)

    # roll number
    for b in template["roll"]:
        if str(roll_str[b["digit"]]) == str(b["value"]):
            mark(b)

    # set bubble
    for s in template["sets"]:
        if s["label"] == set_label:
            mark(s)

    # answers
    for q in template["questions"]:
        a = answers.get(q["q"], "")
        for o in q["options"]:
            if o["label"] in a:
                mark(o)

    return img


def fake_photo(img, seed=0):
    """Mild perspective warp + slight rotation + blur to mimic a phone scan."""
    rng = random.Random(seed)
    h, w = img.shape[:2]
    pad = int(h * 0.08)
    canvas = np.full((h + 2 * pad, w + 2 * pad, 3), 240, np.uint8)
    canvas[pad:pad + h, pad:pad + w] = img
    H2, W2 = canvas.shape[:2]

    # random mild perspective
    jx = rng.uniform(0.01, 0.045)
    jy = rng.uniform(0.01, 0.035)
    src = np.float32([[0, 0], [W2, 0], [W2, H2], [0, H2]])
    dst = np.float32([
        [W2 * jx,         H2 * jy * 0.5],
        [W2 * (1 - jy),   H2 * jx * 0.4],
        [W2 * (1 - jx),   H2 * (1 - jy * 0.4)],
        [W2 * jy * 0.5,   H2 * (1 - jx)],
    ])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(canvas, M, (W2, H2), borderValue=(240, 240, 240))

    # small rotation
    angle = rng.uniform(-3.0, 3.0)
    Rm = cv2.getRotationMatrix2D((W2 / 2, H2 / 2), angle, 1.0)
    rotated = cv2.warpAffine(warped, Rm, (W2, H2), borderValue=(240, 240, 240))

    # slight blur + brightness jitter
    blurred = cv2.GaussianBlur(rotated, (3, 3), 0)
    bright = rng.uniform(0.88, 1.08)
    out = np.clip(blurred.astype(np.float32) * bright, 0, 255).astype(np.uint8)
    return out


def simulate_student(truth_key, accuracy=0.70, blank_rate=0.10, rng=None):
    """
    Build a student answer dict.
      - blank_rate : fraction of questions left unattempted
      - accuracy   : fraction of attempted questions answered correctly
    Returns {question_int: "A"/"B"/"C"/"D" or ""}  (empty string = blank)
    """
    if rng is None:
        rng = random.Random()
    all_options = ["A", "B", "C", "D"]
    student = {}
    for q, correct in truth_key.items():
        r = rng.random()
        if r < blank_rate:
            continue                         # skip -> unattempted
        if r < blank_rate + accuracy:
            student[q] = correct             # correct
        else:
            # pick a wrong option
            wrong_opts = [o for o in all_options if o != correct]
            student[q] = rng.choice(wrong_opts)
    return student


# ---------------------------------------------------------------------------- #
def main():
    if len(sys.argv) < 2:
        print("Usage: python make_sample_scans.py <exam_folder_name>")
        print("  e.g. python make_sample_scans.py EXAM2026_T1")
        sys.exit(1)

    exam_name = sys.argv[1]
    exam_dir  = os.path.join(_HERE, exam_name)
    if not os.path.isdir(exam_dir):
        print(f"ERROR: Folder not found: {exam_dir}")
        sys.exit(1)

    # load exam config
    cfg_path = os.path.join(exam_dir, "exam_config.json")
    with open(cfg_path) as fh:
        config = json.load(fh)

    n_questions          = config["n_questions"]
    n_options            = config["n_options"]
    n_sets               = config["n_sets"]
    n_sheets             = config["n_sheets"]
    roll_digits          = config["roll_digits"]
    questions_per_column = config["questions_per_column"]
    title                = config["title"]
    dpi                  = config["dpi"]

    set_labels = [chr(ord('A') + i) for i in range(max(n_sets, 1))]

    # load answer key for all sets
    key_path = os.path.join(exam_dir, config.get("key", "answer_key.xlsx"))
    opts = [chr(ord('A') + i) for i in range(n_options)]
    truth_keys = {}
    key_was_blank = False
    for s in set_labels:
        try:
            k = load_key(key_path, set_label=s)
        except Exception:
            k = {}
        if not k:
            key_was_blank = True
            rng_key = random.Random(100 + ord(s))
            k = {q: rng_key.choice(opts) for q in range(1, n_questions + 1)}
        truth_keys[s] = k

    # if the key was blank, fill answer_key.xlsx with our generated answers
    if key_was_blank:
        from omr_reader import save_key
        save_key(key_path, truth_keys, n_questions)
        print(f"  Answer key was blank — generated random key and saved to:")
        print(f"  {key_path}")
        print()

    scans_dir = os.path.join(exam_dir, "scans")
    os.makedirs(scans_dir, exist_ok=True)

    print(f"Generating {n_sheets} sample scans for {exam_name} ...")
    print(f"  Questions : {n_questions}   Options : {n_options}   Sets : {set_labels}")
    print(f"  Output    : {scans_dir}")
    print()

    for i in range(n_sheets):
        rng = random.Random(42 + i)

        # unique 10-digit roll number (leading digit 1-9, rest random)
        roll_int = rng.randint(10 ** (roll_digits - 1), 10 ** roll_digits - 1)
        roll_str = str(roll_int).zfill(roll_digits)[:roll_digits]

        # random set
        set_label = rng.choice(set_labels)

        # simulate student accuracy: vary slightly per student
        accuracy   = rng.uniform(0.50, 0.95)
        blank_rate = rng.uniform(0.05, 0.20)
        answers    = simulate_student(truth_keys[set_label],
                                      accuracy=accuracy,
                                      blank_rate=blank_rate, rng=rng)

        # render a blank sheet (serial not important for demo)
        serial = f"{i + 1:08d}"
        pil_img, template, _ = _build_sheet(
            n_questions=n_questions,
            n_options=n_options,
            roll_digits=roll_digits,
            n_sets=n_sets,
            questions_per_column=questions_per_column,
            title=title,
            serial=serial,
            dpi=dpi,
        )

        # PIL -> OpenCV BGR
        img_bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        # fill bubbles
        filled = fill_sheet(img_bgr, template, roll_str, set_label, answers)

        # fake phone photo distortion
        photo = fake_photo(filled, seed=42 + i)

        # save
        out_path = os.path.join(scans_dir, f"student_{i + 1:04d}.jpg")
        cv2.imwrite(out_path, photo, [cv2.IMWRITE_JPEG_QUALITY, 90])

        # count what we expect
        n_attempted = len(answers)
        n_blank     = n_questions - n_attempted
        n_correct   = sum(1 for q, a in answers.items()
                          if truth_keys[set_label].get(q, "") == a)
        n_wrong     = n_attempted - n_correct

        print(f"  [{i+1:2d}/{n_sheets}] student_{i+1:04d}.jpg  "
              f"roll={roll_str}  set={set_label}  "
              f"C={n_correct:3d} X={n_wrong:3d} U={n_blank:3d}  "
              f"acc={accuracy:.0%}")

    print(f"\nDone. {n_sheets} sample images saved to {scans_dir}")


if __name__ == "__main__":
    main()
