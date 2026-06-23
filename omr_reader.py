# -*- coding: utf-8 -*-
"""
Deterministic OMR reader / grader.

Pipeline (no HoughCircles, no KMeans, no per-sheet tuning):
    1. detect the 4 ArUco fiducial markers in the photo
    2. homography from detected marker corners -> template marker corners
    3. warpPerspective the photo onto the exact template frame
    4. sample each known bubble centre from <name>.template.json
    5. Otsu-threshold the bubble darkness distribution -> marked / empty
    6. decode roll + set, score answers against the key, annotate, return result

Key format (flexible):
    * dict  {1: "A", 2: "C", 3: "AB", ...}                  (question -> answer)
    * dict per set {"A": {1:"A",...}, "B": {...}}           (per booklet set)
    * .xlsx / .csv  : rows = questions, columns = sets       (like the old KEY.xlsx)

Deps:  numpy, opencv (with aruco), pandas (only for xlsx/csv keys)
"""

import os
import glob
import json
import numpy as np
import cv2

ARUCO_DICT_ID = cv2.aruco.DICT_4X4_50


# --------------------------------------------------------------------------- #
# ArUco shim
# --------------------------------------------------------------------------- #
def _get_aruco_dict():
    if hasattr(cv2.aruco, "getPredefinedDictionary"):
        return cv2.aruco.getPredefinedDictionary(ARUCO_DICT_ID)
    return cv2.aruco.Dictionary_get(ARUCO_DICT_ID)


def _detect_markers(gray):
    d = _get_aruco_dict()
    if hasattr(cv2.aruco, "ArucoDetector"):                 # OpenCV >= 4.7
        params = cv2.aruco.DetectorParameters()
        corners, ids, _ = cv2.aruco.ArucoDetector(d, params).detectMarkers(gray)
    else:
        params = cv2.aruco.DetectorParameters_create()
        corners, ids, _ = cv2.aruco.detectMarkers(gray, d, parameters=params)
    return corners, ids


# --------------------------------------------------------------------------- #
# Template / key loading
# --------------------------------------------------------------------------- #
def load_template(path):
    with open(path) as fh:
        return json.load(fh)


def save_key(path, keys_by_set, n_questions, qcol="Q"):
    """Persist an answer key as csv/xlsx (rows = questions, columns = sets).

    keys_by_set : {set_label: {question_int: "A"/"AB"/...}}  e.g. {"A": {1:"C",..}}
    Format matches the old KEY.xlsx (a question column + one column per set), so
    it round-trips straight back through load_key().
    """
    import pandas as pd
    set_labels = list(keys_by_set.keys())
    data = {qcol: list(range(1, n_questions + 1))}
    for s in set_labels:
        km = {int(k): str(v).strip().upper() for k, v in keys_by_set[s].items()}
        data[s] = [km.get(q, "") for q in range(1, n_questions + 1)]
    df = pd.DataFrame(data)
    if str(path).lower().endswith(".csv"):
        df.to_csv(path, index=False)
    else:
        df.to_excel(path, index=False)
    return path


def load_key(key, set_label=None):
    """Normalise any supported key form into {question_int: "ABC..."}."""
    if isinstance(key, dict):
        # per-set dict?
        if key and all(isinstance(v, dict) for v in key.values()):
            chosen = key.get(set_label) or next(iter(key.values()))
            return {int(k): str(v).strip().upper() for k, v in chosen.items()}
        return {int(k): str(v).strip().upper() for k, v in key.items()}

    # path to xlsx / csv
    import pandas as pd
    df = pd.read_csv(key) if str(key).lower().endswith(".csv") else pd.read_excel(key)
    # choose the column for this set: by header letter, else positional
    col = None
    if set_label is not None:
        for c in df.columns:
            if str(c).strip().upper() == str(set_label).strip().upper():
                col = c
                break
    if col is None:
        # assume col 0 may be question numbers; first answer column otherwise
        col = df.columns[1] if df.shape[1] > 1 else df.columns[0]
    answers = {}
    for i, v in enumerate(df[col].tolist(), start=1):
        s = str(v).strip().upper()
        if s and s != "NAN":
            answers[i] = s
    return answers


# --------------------------------------------------------------------------- #
# Warp + sampling
# --------------------------------------------------------------------------- #
def warp_to_template(image_bgr, template):
    """Return (warped_bgr, ok). warped has the template's canvas size."""
    W = template["canvas"]["width"]
    H = template["canvas"]["height"]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    corners, ids = _detect_markers(gray)
    if ids is None or len(ids) < 4:
        return None, False

    tmpl_by_id = {m["id"]: np.array(m["corners"], dtype=np.float32)
                  for m in template["markers"]}
    src, dst = [], []
    for c, i in zip(corners, ids.flatten()):
        if int(i) in tmpl_by_id:
            src.append(c.reshape(4, 2))
            dst.append(tmpl_by_id[int(i)])
    if len(src) < 4:
        return None, False

    src = np.vstack(src).astype(np.float32)
    dst = np.vstack(dst).astype(np.float32)
    Hm, _ = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if Hm is None:
        return None, False
    warped = cv2.warpPerspective(image_bgr, Hm, (W, H),
                                 flags=cv2.INTER_LINEAR,
                                 borderValue=(255, 255, 255))
    return warped, True


def _fill_scores(gray, points, default_r):
    """Darkness score (0..1, higher=darker) per bubble.

    Each point is (x, y) or (x, y, r); the per-bubble radius is used when given,
    so the reader follows whatever size the generator stored in template.json.
    """
    scores = np.empty(len(points), dtype=np.float32)
    for k, p in enumerate(points):
        x, y = p[0], p[1]
        r = p[2] if len(p) > 2 else default_r
        rs = max(2, int(0.62 * r))
        x, y = int(round(x)), int(round(y))
        patch = gray[max(0, y - rs):y + rs, max(0, x - rs):x + rs]
        scores[k] = 0.0 if patch.size == 0 else (255.0 - float(patch.mean())) / 255.0
    return scores


def _pts(bubbles, default_r):
    """Build (x, y, r) tuples from template bubble dicts."""
    return [(b["x"], b["y"], b.get("r", default_r)) for b in bubbles]


def _otsu(scores):
    """Otsu threshold on the [0,1] score histogram."""
    s = (np.clip(scores, 0, 1) * 255).astype(np.uint8)
    if s.size < 2 or s.min() == s.max():
        return 0.45
    t, _ = cv2.threshold(s, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return max(t / 255.0, 0.30)        # floor avoids flagging faint print as marks


# --------------------------------------------------------------------------- #
# Grade
# --------------------------------------------------------------------------- #
def grade(image_bgr, template, key,
          marks_correct=1.0, marks_incorrect=0.0, marks_unattempted=0.0,
          set_label=None):
    """Grade one OMR photo. Returns (result_dict, annotated_bgr)."""
    result = {"ok": False, "roll": None, "set": None,
              "correct": 0, "incorrect": 0, "unattempted": 0,
              "total_marks": 0.0, "answers": {}, "error": None}

    warped, ok = warp_to_template(image_bgr, template)
    if not ok:
        result["error"] = "Could not detect the 4 corner markers."
        return result, image_bgr
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    r = template.get("bubble_radius", 20)           # fallback radius

    # global threshold from the answer bubbles (the bulk of the marks)
    all_ans_pts = [p for q in template["questions"] for p in _pts(q["options"], r)]
    thr = _otsu(_fill_scores(gray, all_ans_pts, r))

    # ---- roll number ------------------------------------------------------ #
    roll_digits = template["params"]["roll_digits"]
    by_digit = {d: [] for d in range(roll_digits)}
    for b in template["roll"]:
        by_digit[b["digit"]].append(b)
    roll = ""
    for d in range(roll_digits):
        cells = sorted(by_digit[d], key=lambda b: b["value"])
        sc = _fill_scores(gray, _pts(cells, r), r)
        if sc.max() >= thr and (sc >= thr).sum() == 1:
            roll += str(int(np.argmax(sc)))
        else:
            roll += "?"
    result["roll"] = roll

    # ---- set -------------------------------------------------------------- #
    if template["sets"]:
        sc = _fill_scores(gray, _pts(template["sets"], r), r)
        if sc.max() >= thr and (sc >= thr).sum() == 1:
            result["set"] = template["sets"][int(np.argmax(sc))]["label"]

    # ---- answers ---------------------------------------------------------- #
    keymap = load_key(key, set_label=result["set"] or set_label)
    annot = warped
    for q in template["questions"]:
        qn = q["q"]
        pts = _pts(q["options"], r)
        sc = _fill_scores(gray, pts, r)
        marked_idx = [i for i in range(len(sc)) if sc[i] >= thr]
        marked = "".join(q["options"][i]["label"] for i in marked_idx)
        result["answers"][qn] = marked

        correct_key = keymap.get(qn, "")
        if not correct_key:                      # not in key -> ignore
            continue
        if not marked:
            result["unattempted"] += 1
            verdict = "L"
        else:
            ok_q = all(ch in correct_key for ch in marked) and len(marked) >= 1
            if ok_q:
                result["correct"] += 1; verdict = "C"
            else:
                result["incorrect"] += 1; verdict = "X"
            color = (0, 170, 0) if ok_q else (0, 0, 255)
            for i in marked_idx:
                x, y, rr = int(pts[i][0]), int(pts[i][1]), pts[i][2]
                cv2.circle(annot, (x, y), int(rr * 1.25), color, max(2, int(rr * 0.18)))

    result["total_marks"] = (result["correct"] * marks_correct +
                             result["incorrect"] * marks_incorrect +
                             result["unattempted"] * marks_unattempted)
    result["ok"] = True

    cv2.putText(annot, f"Roll {roll}  Set {result['set']}  "
                       f"C={result['correct']} X={result['incorrect']} "
                       f"Marks={result['total_marks']:g}",
                (template["markers"][0]["side"] + 40, template["canvas"]["height"] - 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1.4, (200, 0, 0), 3, cv2.LINE_AA)
    return result, annot


# --------------------------------------------------------------------------- #
# QR decode + template auto-resolution
#
# Every sheet's QR encodes {serial, name, q, o, r, s}.  All sheets from the
# generator share identical marker AND QR positions, so we can warp with ANY
# template, read the QR, then pick the matching template by its design params.
# --------------------------------------------------------------------------- #
def read_qr(image_bgr, template=None):
    """Decode the sheet QR -> parsed dict (or None). Tries the raw photo, then
    a marker-warp if a template is supplied (QR sits at a fixed warped spot)."""
    det = cv2.QRCodeDetector()
    candidates = [image_bgr]
    if template is not None:
        warped, ok = warp_to_template(image_bgr, template)
        if ok:
            candidates.append(warped)
    for im in candidates:
        try:
            data, _, _ = det.detectAndDecode(im)
        except Exception:
            data = ""
        if data:
            try:
                return json.loads(data)
            except Exception:
                return {"raw": data}
    return None


def load_templates(templates_dir):
    """Load every *.template.json in a directory -> [(path, template), ...]."""
    out = []
    for p in sorted(glob.glob(os.path.join(templates_dir, "*.template.json"))):
        try:
            out.append((p, load_template(p)))
        except Exception:
            continue
    return out


def resolve_template(image_bgr, templates_dir):
    """Pick the right template for a scan by reading its QR.

    Returns (template, template_path, qr_dict). Falls back to the only template
    in the folder if the QR can't be read. Raises if it can't decide.
    """
    templates = load_templates(templates_dir)
    if not templates:
        raise FileNotFoundError(f"No *.template.json in {templates_dir}")

    # markers/QR are identical across designs -> warp with the first to read QR
    qr = None
    for _, t in templates:
        qr = read_qr(image_bgr, template=t)
        if qr:
            break
    if qr is None:
        qr = read_qr(image_bgr)

    if qr and all(k in qr for k in ("q", "o", "r", "s")):
        want = (qr["q"], qr["o"], qr["r"], qr["s"])
        matches = [(p, t) for p, t in templates
                   if (t["params"]["n_questions"], t["params"]["n_options"],
                       t["params"]["roll_digits"], t["params"]["n_sets"]) == want]
        if len(matches) == 1:
            return matches[0][1], matches[0][0], qr
        if len(matches) > 1 and qr.get("name"):     # disambiguate by name prefix
            for p, t in matches:
                if str(qr["name"]).startswith(str(t.get("name", ""))):
                    return t, p, qr
            return matches[0][1], matches[0][0], qr

    if len(templates) == 1:                          # only one option -> use it
        return templates[0][1], templates[0][0], qr
    raise ValueError("Could not resolve a unique template from the QR; "
                     f"{len(templates)} templates present, QR={qr}")


def grade_file(image_path, template, key, **kw):
    """Grade one scan. `template` may be:
        * a path to a .template.json            (explicit -- you choose)
        * a directory of *.template.json        (auto-pick via the sheet QR)
        * an already-loaded template dict
    """
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(image_path)

    serial = None
    if isinstance(template, dict):
        tmpl = template
    elif os.path.isdir(template):
        tmpl, _, qr = resolve_template(img, template)
        serial = (qr or {}).get("serial")
    else:
        tmpl = load_template(template)

    res, annot = grade(img, tmpl, key, **kw)
    res["FILENAME"] = os.path.basename(image_path)
    if serial:
        res["SERIAL"] = serial
    return res, annot
