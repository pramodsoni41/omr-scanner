# -*- coding: utf-8 -*-
"""
Parametric OMR sheet generator (fiducial-marker based).

We GENERATE the sheet, so we KNOW every bubble's location exactly.  Four ArUco
fiducial markers are printed in the corners (the OMR registration standard).  At
read time the reader detects those markers, computes a homography, warps the
photo onto this template frame, and samples each known bubble centre -- no
HoughCircles, no KMeans, no per-sheet tuning.

Outputs (per design):
    <out>/<name>.png             printable image (A4 @ dpi)
    <out>/<name>.pdf             same, ready to print
    <out>/<name>.template.json   every bubble + marker coordinate (template frame)

Deps:  numpy, opencv (with aruco), qrcode, Pillow
"""

import os
import json
import shutil
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

try:
    import qrcode
    _HAVE_QR = True
except Exception:
    _HAVE_QR = False

A4_MM = (210.0, 297.0)
ARUCO_DICT_ID = cv2.aruco.DICT_4X4_50

INK = (0, 0, 0)
PANEL = (90, 90, 90)          # panel border
HEADER_BG = (228, 228, 228)   # section header bar
LABEL_GRAY = (120, 120, 120)  # faint option letters inside bubbles
SHADE = (245, 245, 245)       # alternate answer-row shading


# --------------------------------------------------------------------------- #
# ArUco compatibility shim
# --------------------------------------------------------------------------- #
def _get_aruco_dict():
    if hasattr(cv2.aruco, "getPredefinedDictionary"):
        return cv2.aruco.getPredefinedDictionary(ARUCO_DICT_ID)
    return cv2.aruco.Dictionary_get(ARUCO_DICT_ID)


def _make_marker(marker_id, side_px):
    d = _get_aruco_dict()
    if hasattr(cv2.aruco, "generateImageMarker"):
        return cv2.aruco.generateImageMarker(d, marker_id, side_px)
    img = np.zeros((side_px, side_px), dtype=np.uint8)
    return cv2.aruco.drawMarker(d, marker_id, side_px, img)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def mm(value_mm, dpi):
    return int(round(value_mm / 25.4 * dpi))


def _font(size):
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_centered(draw, cx, cy, text, font, fill):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (r - l) / 2 - l, cy - (b - t) / 2 - t), text, font=font, fill=fill)


def _bubble(draw, cx, cy, r, label, font):
    """Thin circle; optional faint centred label (None = plain oval)."""
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=INK, width=max(1, r // 11))
    if label:
        _text_centered(draw, cx, cy, label, font, LABEL_GRAY)


def _panel(draw, box, title, font, dpi):
    """Bordered panel with a shaded title bar; returns inner content top-y."""
    x0, y0, x1, y1 = box
    draw.rectangle(box, outline=PANEL, width=max(1, mm(0.3, dpi)))
    bar_h = mm(6, dpi)
    draw.rectangle([x0, y0, x1, y0 + bar_h], fill=HEADER_BG, outline=PANEL,
                   width=max(1, mm(0.3, dpi)))
    draw.text((x0 + mm(2, dpi), y0 + bar_h / 2 -
               (draw.textbbox((0, 0), title, font=font)[3]) / 2),
              title, font=font, fill=INK)
    return y0 + bar_h


# --------------------------------------------------------------------------- #
# Renderer (geometry + drawing) -- shared by single and batch generation
# --------------------------------------------------------------------------- #
def _build_sheet(
        n_questions,
        n_options=4,
        roll_digits=10,
        n_sets=4,
        questions_per_column=25,
        roll_label="inside",          # "inside" -> digit in every bubble (ABCD style)
        serial="00000001",            # "side"   -> digit labelled once on the left
        title="OMR ANSWER SHEET",
        name=None,
        dpi=300):
    """Render one sheet. Returns (PIL image, template dict, meta dict).

    Geometry is identical for a given design; only the QR/serial changes
    between sheets, so a whole batch can share one template.json.
    """
    name = name or f"OMR_{n_questions}q_{roll_digits}r_{serial}"
    option_labels = [chr(ord('A') + i) for i in range(n_options)]
    set_labels = [chr(ord('A') + i) for i in range(n_sets)]

    W, H = mm(A4_MM[0], dpi), mm(A4_MM[1], dpi)
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    margin = mm(8, dpi)
    bubble_r = mm(2.2, dpi)
    f_tiny = _font(mm(2.4, dpi))
    f_small = _font(mm(2.7, dpi))
    f_hdr = _font(mm(3.2, dpi))
    f_title = _font(mm(6.2, dpi))

    template = {
        "schema": "omr-template/v1", "name": name, "serial": str(serial),
        "canvas": {"width": W, "height": H, "dpi": dpi},
        "params": {"n_questions": n_questions, "n_options": n_options,
                   "roll_digits": roll_digits, "n_sets": n_sets,
                   "option_labels": option_labels, "set_labels": set_labels},
        "bubble_radius": bubble_r,
        "markers": [], "qr": None, "roll": [], "sets": [], "questions": [],
    }

    # ---- outer content frame ---------------------------------------------- #
    draw.rectangle([margin, margin, W - margin, H - margin],
                   outline=PANEL, width=max(1, mm(0.3, dpi)))

    # ---- 1. ArUco corner markers ------------------------------------------ #
    m_side = mm(13, dpi)
    mpad = margin + mm(2, dpi)
    corners = {0: (mpad, mpad), 1: (W - mpad - m_side, mpad),
               2: (mpad, H - mpad - m_side), 3: (W - mpad - m_side, H - mpad - m_side)}
    for mid, (mx, my) in corners.items():
        img.paste(Image.fromarray(_make_marker(mid, m_side)).convert("RGB"), (mx, my))
        template["markers"].append({
            "id": mid, "center": [mx + m_side / 2, my + m_side / 2],
            "corners": [[mx, my], [mx + m_side, my],
                        [mx + m_side, my + m_side], [mx, my + m_side]],
            "side": m_side})

    inner_l = mpad + m_side + mm(4, dpi)
    inner_r = W - mpad - m_side - mm(4, dpi)

    # ---- 2. Title + QR ---------------------------------------------------- #
    draw.text((inner_l, mpad + mm(1, dpi)), title, font=f_title, fill=INK)

    qr_side = mm(24, dpi)
    qr_x, qr_y = inner_r - qr_side, mpad
    if _HAVE_QR:
        payload = json.dumps({"serial": str(serial), "name": name,
                              "q": n_questions, "o": n_options,
                              "r": roll_digits, "s": n_sets},
                             separators=(",", ":"))
        qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(payload); qr.make(fit=True)
        qimg = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        img.paste(qimg.resize((qr_side, qr_side), Image.NEAREST), (qr_x, qr_y))
        _text_centered(draw, qr_x + qr_side / 2, qr_y + qr_side + mm(2, dpi),
                       f"SN {serial}", f_tiny, INK)
        template["qr"] = {"bbox": [qr_x, qr_y, qr_x + qr_side, qr_y + qr_side],
                          "data": payload}

    top = mpad + m_side + mm(3, dpi)

    # ---- 3. Roll-number panel (digits labelled once on the left) ---------- #
    col_gap = mm(6.0, dpi)
    row_gap = mm(5.4, dpi)
    lab_gutter = mm(5.5, dpi)
    box_h = mm(6.5, dpi)
    pad = mm(3, dpi)

    roll_w = lab_gutter + roll_digits * col_gap + pad
    roll_h = mm(6, dpi) + box_h + mm(2, dpi) + 10 * row_gap + pad
    roll_box = [inner_l, top, inner_l + roll_w, top + roll_h]
    c_top = _panel(draw, roll_box, "ROLL NUMBER", f_hdr, dpi)

    grid_x0 = inner_l + lab_gutter + col_gap / 2
    box_y0 = c_top + mm(2, dpi)
    grid_y0 = box_y0 + box_h + mm(3, dpi) + bubble_r
    # write-in boxes
    for d in range(roll_digits):
        cx = grid_x0 + d * col_gap
        draw.rectangle([cx - col_gap / 2 + mm(0.6, dpi), box_y0,
                        cx + col_gap / 2 - mm(0.6, dpi), box_y0 + box_h],
                       outline=PANEL, width=max(1, mm(0.25, dpi)))
    # bubble grid: digit either inside each bubble or labelled once on the left
    for v in range(10):
        cy = grid_y0 + v * row_gap
        if roll_label == "side":
            _text_centered(draw, inner_l + lab_gutter / 2 + mm(1, dpi), cy,
                           str(v), f_small, INK)
        for d in range(roll_digits):
            cx = grid_x0 + d * col_gap
            lab = str(v) if roll_label == "inside" else None
            _bubble(draw, cx, cy, bubble_r, lab, f_tiny)
            template["roll"].append({"digit": d, "value": v,
                                     "x": cx, "y": cy, "r": bubble_r})

    # ---- 4. SET panel (right of roll) ------------------------------------- #
    if n_sets > 0:
        set_box = [inner_l + roll_w + mm(5, dpi), top,
                   inner_l + roll_w + mm(5, dpi) + mm(18, dpi),
                   top + mm(6, dpi) + box_h + n_sets * row_gap + pad]
        s_top = _panel(draw, set_box, "SET", f_hdr, dpi)
        sx = (set_box[0] + set_box[2]) / 2
        for i, lab in enumerate(set_labels):
            cy = s_top + mm(4, dpi) + i * row_gap + bubble_r
            _bubble(draw, sx, cy, bubble_r, lab, f_small)
            template["sets"].append({"label": lab, "x": sx, "y": cy, "r": bubble_r})

    # ---- 5. Answers panel (adaptive: bubbles grow to fill the space) ------ #
    ans_top = max(roll_box[3], top + mm(70, dpi)) + mm(6, dpi)
    n_columns = int(np.ceil(n_questions / questions_per_column))
    rows = min(n_questions, questions_per_column)

    ans_box = [inner_l, ans_top, inner_r, H - mpad - mm(3, dpi)]
    a_top = _panel(draw, ans_box, "ANSWERS  (fill one bubble per question)", f_hdr, dpi)
    body_top = a_top + mm(4, dpi)
    body_bottom = ans_box[3] - mm(3, dpi)

    # divide the panel into a grid of cells; the bubble fills most of a cell
    col_w = (inner_r - inner_l) / n_columns
    row_h = (body_bottom - body_top) / rows
    qnum_w = min(mm(8, dpi), 0.18 * col_w)          # question-number gutter
    opt_slot = (col_w - qnum_w - mm(2, dpi)) / n_options
    cell = min(opt_slot, row_h)
    ans_r = int(np.clip(0.42 * cell, mm(1.9, dpi), mm(7.0, dpi)))
    f_ans = _font(int(np.clip(ans_r * 0.85, mm(2.0, dpi), mm(5.5, dpi))))

    for q in range(n_questions):
        col, row = q // questions_per_column, q % questions_per_column
        col_x = inner_l + col * col_w
        ry = body_top + row * row_h + row_h / 2     # vertical centre of the cell
        if row % 2 == 1:                            # zebra shading
            draw.rectangle([col_x + mm(1, dpi), ry - row_h / 2,
                            col_x + col_w - mm(1, dpi), ry + row_h / 2], fill=SHADE)
        _text_centered(draw, col_x + qnum_w / 2, ry, f"{q + 1}", f_ans, INK)
        opts = []
        for oi, lab in enumerate(option_labels):
            cx = col_x + qnum_w + opt_slot * (oi + 0.5)
            _bubble(draw, cx, ry, ans_r, lab, f_ans)
            opts.append({"label": lab, "x": cx, "y": ry, "r": ans_r})
        template["questions"].append({"q": q + 1, "options": opts})

    template["answer_bubble_radius"] = ans_r

    return img, template, {"name": name, "size_px": (W, H),
                           "n_columns": n_columns, "serial": str(serial)}


# --------------------------------------------------------------------------- #
# Public API: single sheet
# --------------------------------------------------------------------------- #
def generate_omr(n_questions, out_dir="omr_out", dpi=300, serial="00000001",
                 name=None, **design):
    """Generate ONE sheet -> png + pdf + template.json. Returns paths."""
    os.makedirs(out_dir, exist_ok=True)
    img, template, meta = _build_sheet(n_questions, serial=serial, name=name,
                                       dpi=dpi, **design)
    base = os.path.join(out_dir, meta["name"])
    img.save(base + ".png", "PNG", dpi=(dpi, dpi))
    img.save(base + ".pdf", "PDF", resolution=float(dpi))
    with open(base + ".template.json", "w") as fh:
        json.dump(template, fh, indent=2)
    return {"png": base + ".png", "pdf": base + ".pdf",
            "template": base + ".template.json",
            "size_px": meta["size_px"], "n_columns": meta["n_columns"]}


# --------------------------------------------------------------------------- #
# Public API: batch (one sheet per candidate, unique serial each)
# --------------------------------------------------------------------------- #
def generate_batch(n_sheets, n_questions, out_dir="omr_out", dpi=300,
                   start_serial=1, serial_width=8, batch_name="BATCH",
                   combined_pdf=True, save_pages=False, **design):
    """Generate `n_sheets` sheets that share one geometry but get unique serials.

    Writes:
        <out>/<batch_name>.template.json   one shared template (geometry)
        <out>/<batch_name>_all.pdf         all sheets, one multipage PDF to print
        <out>/<batch_name>_manifest.csv    serial <-> page index
        <out>/pages/<serial>.png           per-sheet PNGs   (only if save_pages)

    Returns a summary dict (counts + paths).
    """
    os.makedirs(out_dir, exist_ok=True)
    serials, template = [], None

    # Memory-safe: render one sheet at a time, write its page to a temp PDF, free
    # the (~26 MB) image immediately, and merge the pages with pypdf at the end.
    # This keeps peak RAM at ~one page instead of N pages (fits a 512 MB host).
    writer = None
    tmp_dir = os.path.join(out_dir, "_tmp_pages")
    if combined_pdf:
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        os.makedirs(tmp_dir, exist_ok=True)
    if save_pages:
        os.makedirs(os.path.join(out_dir, "pages"), exist_ok=True)

    for i in range(n_sheets):
        serial = f"{start_serial + i:0{serial_width}d}"
        img, template, _ = _build_sheet(n_questions, serial=serial,
                                         name=f"{batch_name}_{serial}",
                                         dpi=dpi, **design)
        serials.append(serial)
        if save_pages:
            img.save(os.path.join(out_dir, "pages", serial + ".png"), "PNG",
                     dpi=(dpi, dpi))
        if writer is not None:
            page_pdf = os.path.join(tmp_dir, serial + ".pdf")
            img.save(page_pdf, "PDF", resolution=float(dpi))
            writer.append(PdfReader(page_pdf))
        del img                     # release ~26 MB now, not at loop end

    # one shared template (geometry identical across the batch)
    template["serial"] = None
    template["serials"] = serials
    tmpl_path = os.path.join(out_dir, batch_name + ".template.json")
    with open(tmpl_path, "w") as fh:
        json.dump(template, fh, indent=2)

    # manifest
    manifest_path = os.path.join(out_dir, batch_name + "_manifest.csv")
    with open(manifest_path, "w") as fh:
        fh.write("page,serial\n")
        for idx, s in enumerate(serials, start=1):
            fh.write(f"{idx},{s}\n")

    out = {"template": tmpl_path, "manifest": manifest_path,
           "n_sheets": n_sheets, "serials": [serials[0], serials[-1]]}

    if writer is not None:
        pdf_path = os.path.join(out_dir, batch_name + "_all.pdf")
        with open(pdf_path, "wb") as fh:
            writer.write(fh)
        writer.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)
        out["combined_pdf"] = pdf_path
    return out


if __name__ == "__main__":
    # single sheet
    one = generate_omr(n_questions=100, n_options=4, roll_digits=10, n_sets=4,
                       questions_per_column=25, serial="00000001",
                       title="IIT (BHU) - OMR ANSWER SHEET", out_dir="omr_out")
    print("Single sheet:")
    for k, v in one.items():
        print(f"  {k}: {v}")

    # batch of 25 candidates (serials 1..25), one print-ready PDF
    batch = generate_batch(n_sheets=4, n_questions=100, n_options=4,
                           roll_digits=10, n_sets=4, questions_per_column=25,
                           start_serial=1, batch_name="EXAM20261",
                           title="IIT (BHU) - OMR ANSWER SHEET", out_dir="omr_out")
    print("\nBatch:")
    for k, v in batch.items():
        print(f"  {k}: {v}")
