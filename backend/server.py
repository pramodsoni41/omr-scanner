# -*- coding: utf-8 -*-
"""
OMR backend API  --  wraps omr_generator + omr_reader as a web service.

The phone app calls these endpoints; the server runs your Python unchanged
(ArUco + OpenCV install fine on a normal Linux host).  No PC needed by the user.

Run locally:
    cd OMR_APP/backend
    uvicorn server:app --host 0.0.0.0 --port 8000
Then open  http://<this-machine-ip>:8000/docs  for an interactive test page.

Endpoints
---------
GET  /                                health / info
POST /generate                        body -> create exam, returns sheet PDF url
GET  /exams/{id}/sheets.pdf           download printable sheets
GET  /exams/{id}/template.json        the geometry (debug)
POST /exams/{id}/key                  upload answer key (xlsx/csv)
POST /exams/{id}/grade               upload scan image(s) -> marks JSON
GET  /exams/{id}/graded/{name}       annotated sheet image
GET  /exams/{id}/marksheet.xlsx      consolidated marksheet
"""

import os
import sys
import uuid
import shutil

import cv2
import numpy as np
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# make the engine importable (it lives one level up)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import omr_generator as gen
import omr_reader as rdr

EXAMS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exams")
os.makedirs(EXAMS_DIR, exist_ok=True)

app = FastAPI(title="OMR Service", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


def _exam_dir(exam_id):
    d = os.path.join(EXAMS_DIR, exam_id)
    if not os.path.isdir(d):
        raise HTTPException(404, f"exam '{exam_id}' not found")
    return d


# --------------------------------------------------------------------------- #
# 1. Generate sheets
# --------------------------------------------------------------------------- #
class GenerateReq(BaseModel):
    n_questions: int = Field(100, ge=1, le=400)
    n_options: int = Field(4, ge=2, le=6)
    roll_digits: int = Field(10, ge=1, le=15)
    n_sets: int = Field(4, ge=0, le=6)
    questions_per_column: int = Field(25, ge=1, le=50)
    roll_label: str = "inside"
    n_sheets: int = Field(1, ge=1, le=2000)
    start_serial: int = 1
    title: str = "OMR ANSWER SHEET"


@app.post("/generate")
def generate(req: GenerateReq):
    exam_id = uuid.uuid4().hex[:10]
    d = os.path.join(EXAMS_DIR, exam_id)
    os.makedirs(d, exist_ok=True)
    info = gen.generate_batch(
        n_sheets=req.n_sheets, n_questions=req.n_questions,
        n_options=req.n_options, roll_digits=req.roll_digits, n_sets=req.n_sets,
        questions_per_column=req.questions_per_column, roll_label=req.roll_label,
        start_serial=req.start_serial, batch_name="SHEETS",
        title=req.title, out_dir=d)
    return {
        "exam_id": exam_id,
        "n_sheets": req.n_sheets,
        "serials": info["serials"],
        "sheets_pdf": f"/exams/{exam_id}/sheets.pdf",
        "template": f"/exams/{exam_id}/template.json",
        "next": f"upload your answer key to POST /exams/{exam_id}/key",
    }


@app.get("/exams/{exam_id}/sheets.pdf")
def sheets_pdf(exam_id):
    p = os.path.join(_exam_dir(exam_id), "SHEETS_all.pdf")
    if not os.path.exists(p):
        raise HTTPException(404, "no PDF for this exam")
    return FileResponse(p, media_type="application/pdf", filename=f"{exam_id}_sheets.pdf")


@app.get("/exams/{exam_id}/template.json")
def template_json(exam_id):
    return FileResponse(os.path.join(_exam_dir(exam_id), "SHEETS.template.json"),
                        media_type="application/json")


# --------------------------------------------------------------------------- #
# 2. Upload answer key
# --------------------------------------------------------------------------- #
@app.post("/exams/{exam_id}/key")
async def upload_key(exam_id, file: UploadFile = File(...)):
    d = _exam_dir(exam_id)
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".xlsx", ".csv"):
        raise HTTPException(400, "key must be .xlsx or .csv")
    dst = os.path.join(d, "key" + ext)
    with open(dst, "wb") as fh:
        shutil.copyfileobj(file.file, fh)
    # quick validation
    try:
        rdr.load_key(dst, set_label="A")
    except Exception as e:
        raise HTTPException(400, f"could not read key: {e}")
    return {"ok": True, "key": os.path.basename(dst)}


def _find_key(d):
    for name in ("key.xlsx", "key.csv"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


# --------------------------------------------------------------------------- #
# 3. Grade scans
# --------------------------------------------------------------------------- #
@app.post("/exams/{exam_id}/grade")
async def grade(exam_id,
                files: list[UploadFile] = File(...),
                marks_correct: float = Form(1.0),
                marks_incorrect: float = Form(0.0),
                marks_unattempted: float = Form(0.0)):
    d = _exam_dir(exam_id)
    template_path = os.path.join(d, "SHEETS.template.json")
    if not os.path.exists(template_path):
        raise HTTPException(400, "exam has no template")
    key = _find_key(d)
    if key is None:
        raise HTTPException(400, "no answer key uploaded yet (POST /exams/{id}/key)")
    template = rdr.load_template(template_path)
    graded_dir = os.path.join(d, "graded")
    os.makedirs(graded_dir, exist_ok=True)

    results = []
    for uf in files:
        data = np.frombuffer(await uf.read(), np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            results.append({"FILENAME": uf.filename, "error": "unreadable image"})
            continue
        res, annot = rdr.grade(img, template, key,
                               marks_correct=marks_correct,
                               marks_incorrect=marks_incorrect,
                               marks_unattempted=marks_unattempted)
        res["FILENAME"] = uf.filename
        tag = res.get("roll") or os.path.splitext(uf.filename)[0]
        annot_name = f"{tag}.jpg"
        cv2.imwrite(os.path.join(graded_dir, annot_name), annot)
        res["graded_image"] = f"/exams/{exam_id}/graded/{annot_name}"
        results.append(res)

    # consolidated marksheet
    cols = ["FILENAME", "roll", "set", "correct", "incorrect",
            "unattempted", "total_marks", "error"]
    df = pd.DataFrame(results)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    df[cols].to_excel(os.path.join(d, "marksheet.xlsx"), index=False)

    return JSONResponse({
        "exam_id": exam_id, "graded": len(results),
        "results": results,
        "marksheet": f"/exams/{exam_id}/marksheet.xlsx",
    })


@app.get("/exams/{exam_id}/graded/{name}")
def graded_image(exam_id, name):
    p = os.path.join(_exam_dir(exam_id), "graded", name)
    if not os.path.exists(p):
        raise HTTPException(404, "no such graded image")
    return FileResponse(p, media_type="image/jpeg")


@app.get("/exams/{exam_id}/marksheet.xlsx")
def marksheet(exam_id):
    p = os.path.join(_exam_dir(exam_id), "marksheet.xlsx")
    if not os.path.exists(p):
        raise HTTPException(404, "nothing graded yet")
    return FileResponse(
        p, filename=f"{exam_id}_marksheet.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/health")
def health():
    exams = sorted(os.listdir(EXAMS_DIR)) if os.path.isdir(EXAMS_DIR) else []
    return {"service": "OMR", "status": "ok", "exams": len(exams), "docs": "/docs"}


# ---- serve the PWA frontend ------------------------------------------------ #
@app.get("/", response_class=HTMLResponse)
def app_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(os.path.join(STATIC_DIR, "manifest.webmanifest"),
                        media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    # served from root so its scope covers the whole app
    return FileResponse(os.path.join(STATIC_DIR, "sw.js"),
                        media_type="application/javascript")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
