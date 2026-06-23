# OMR Scanner

Generate printable OMR answer sheets, then grade photographed sheets — driven by
ArUco fiducial markers and a per-exam `template.json` (deterministic: no
HoughCircles/KMeans tuning).

## Structure

```
omr_generator.py     parametric sheet + template.json generator
omr_reader.py        deterministic grader (markers -> homography -> sample -> score)
backend/             FastAPI service wrapping the engine (server.py)
webapp/              static PWA frontend (host on your website)
DEPLOY.md            step-by-step deployment
render.yaml          one-click Render blueprint for the backend
```

## Run locally

```bash
pip install -r backend/requirements.txt
uvicorn backend.server:app --reload --port 8000
# open http://127.0.0.1:8000  (backend also serves a copy of the UI)
```

## Deploy

See **[DEPLOY.md](DEPLOY.md)**. In short: backend → Render (free, via
`render.yaml`); frontend (`webapp/`) → your static site (e.g.
pramodsoni.in/omr/), then point it at the backend URL via the in-app ⚙️ settings.

## Tests

```bash
python test_loop.py          # generate -> fill -> distort -> grade
python test_random_key.py    # random key round-trip (xlsx)
python test_auto_template.py # QR-based template auto-selection
```
