# -*- coding: utf-8 -*-
"""
generate_exam.py  -  Step 1 of the OMR workflow.

Run this script to set up a new exam:
    python generate_exam.py

It will ask for exam parameters, then create an exam folder with:
    <EXAM_NAME>/
        scans/                  <- paste student scan photos here
        scan_checked/           <- graded annotated images (auto-created at check time)
        <EXAM_NAME>.template.json
        <EXAM_NAME>_all.pdf     <- print-ready multi-page PDF
        answer_key.xlsx         <- fill in the correct answers before checking
        exam_config.json        <- all parameters (for reference)

After printing and collecting sheets, paste student photos into scans/, fill in
answer_key.xlsx, then run check_omr.py from inside the exam folder.
"""

import os
import sys
import json
import shutil

# ---- locate omr_generator (same folder as this script) ---------------------- #
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from omr_generator import generate_batch
from omr_reader import save_key


# ----------------------------------------------------------------------------- #
def _ask(prompt, default=None, cast=str, choices=None):
    """Simple interactive prompt with optional default and cast."""
    hint = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{hint}: ").strip()
        if raw == "" and default is not None:
            return default
        try:
            val = cast(raw)
        except (ValueError, TypeError):
            print(f"  Invalid input, expected {cast.__name__}. Try again.")
            continue
        if choices and val not in choices:
            print(f"  Must be one of: {choices}")
            continue
        return val


def _yn(prompt, default="y"):
    ans = _ask(prompt + " (y/n)", default=default).lower()
    return ans.startswith("y")


# ----------------------------------------------------------------------------- #
def main():
    print("=" * 60)
    print("  OMR Exam Generator")
    print("=" * 60)

    exam_name   = _ask("Exam name (used as folder name, no spaces)", default="EXAM2026",
                       cast=lambda s: s.strip().replace(" ", "_"))
    n_questions = _ask("Number of questions", default=100, cast=int)
    n_options   = _ask("Number of options per question (e.g. 4 for A-D)", default=4, cast=int)
    n_sets      = _ask("Number of question-paper sets (0 to disable)", default=4, cast=int)
    n_sheets    = _ask("Number of OMR sheets to generate (= number of students)", default=50, cast=int)
    roll_digits = _ask("Number of roll-number digits", default=10, cast=int)
    questions_per_column = _ask("Questions per column in the answer grid", default=25, cast=int)
    title       = _ask("Sheet title", default="IIT (BHU) - OMR ANSWER SHEET")
    dpi         = _ask("Print resolution (DPI)", default=300, cast=int)

    print()
    print("Marking scheme:")
    marks_correct     = _ask("  Marks for correct answer",     default=1.0,   cast=float)
    marks_incorrect   = _ask("  Marks for incorrect answer",   default=0.0,   cast=float)
    marks_unattempted = _ask("  Marks for unattempted",        default=0.0,   cast=float)

    out_dir = os.path.join(_HERE, exam_name)
    if os.path.exists(out_dir):
        if not _yn(f"\nFolder '{exam_name}' already exists. Overwrite?", default="n"):
            print("Aborted.")
            return

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "scans"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "scan_checked"), exist_ok=True)

    print(f"\nGenerating {n_sheets} sheets ... (this may take a moment)")
    info = generate_batch(
        n_sheets=n_sheets,
        n_questions=n_questions,
        n_options=n_options,
        roll_digits=roll_digits,
        n_sets=n_sets,
        questions_per_column=questions_per_column,
        title=title,
        dpi=dpi,
        batch_name=exam_name,
        out_dir=out_dir,
        combined_pdf=True,
        save_pages=False,
    )

    # ---- blank answer key --------------------------------------------------- #
    set_labels = [chr(ord('A') + i) for i in range(max(n_sets, 1))]
    blank_key  = {s: {q: "" for q in range(1, n_questions + 1)} for s in set_labels}
    key_path   = os.path.join(out_dir, "answer_key.xlsx")
    save_key(key_path, blank_key, n_questions)

    # ---- exam config JSON --------------------------------------------------- #
    config = {
        "exam_name": exam_name,
        "n_questions": n_questions,
        "n_options": n_options,
        "n_sets": n_sets,
        "n_sheets": n_sheets,
        "roll_digits": roll_digits,
        "questions_per_column": questions_per_column,
        "title": title,
        "dpi": dpi,
        "marking_scheme": {
            "marks_correct": marks_correct,
            "marks_incorrect": marks_incorrect,
            "marks_unattempted": marks_unattempted,
        },
        "template": os.path.basename(info["template"]),
        "pdf": os.path.basename(info.get("combined_pdf", "")),
        "key": "answer_key.xlsx",
    }
    config_path = os.path.join(out_dir, "exam_config.json")
    with open(config_path, "w") as fh:
        json.dump(config, fh, indent=2)

    # ---- copy check_omr.py into the exam folder ----------------------------- #
    checker_src = os.path.join(_HERE, "check_omr.py")
    checker_dst = os.path.join(out_dir, "check_omr.py")
    if os.path.exists(checker_src):
        shutil.copy2(checker_src, checker_dst)

    # ---- summary ------------------------------------------------------------ #
    print()
    print("=" * 60)
    print(f"  Exam folder ready: {out_dir}")
    print("=" * 60)
    print(f"  Print-ready PDF : {info.get('combined_pdf', 'N/A')}")
    print(f"  Template JSON   : {info['template']}")
    print(f"  Answer key      : {key_path}  <-- fill this in!")
    print(f"  Exam config     : {config_path}")
    print()
    print("Next steps:")
    print("  1. Print the PDF and distribute to students.")
    print(f"  2. After the exam, copy scanned photos into:  {os.path.join(out_dir, 'scans')}")
    print(f"  3. Fill in the correct answers in answer_key.xlsx")
    print(f"  4. Run:  python check_omr.py  (from inside {out_dir})")


if __name__ == "__main__":
    main()
