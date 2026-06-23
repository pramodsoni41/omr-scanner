# Deploying the OMR webapp

Two pieces, two homes:

| Piece | Folder | Where it goes |
|-------|--------|---------------|
| **Frontend** (static webapp) | `webapp/` | your site — **pramodsoni.in/omr/** |
| **Backend** (Python engine) | `backend/` + `omr_generator.py`, `omr_reader.py` | a Python host (Render free tier) |

The frontend is plain HTML/JS, so any static host serves it. The backend is
Python+OpenCV, so it needs a Python runtime — pramodsoni.in (static) can't run it.

---

## Step 1 — Put the backend online (once)

**Option A: Render (free, recommended)**

1. Push this `OMR_APP` folder to a GitHub repo.
2. On https://render.com → **New → Web Service** → connect the repo.
3. Settings:
   - **Build command:** `pip install -r backend/requirements.txt`
   - **Start command:** `uvicorn backend.server:app --host 0.0.0.0 --port $PORT`
4. Deploy. You get a URL like `https://omr-api.onrender.com`.
5. Open `https://omr-api.onrender.com/health` — should say `{"status":"ok"}`.

Notes on the free tier:
- It **sleeps after ~15 min idle**; the first request then takes ~30–50 s to wake.
- Disk is **ephemeral** — generated sheets/keys are cleared on restart/redeploy.
  Fine for grade-in-one-session use. For permanent storage add a paid disk or a
  database later.

(Railway, Fly.io, PythonAnywhere work the same way — install `requirements.txt`,
run the uvicorn start command.)

**Optional — nicer URL:** point `api.pramodsoni.in` at the host with a CNAME, so
the app calls `https://api.pramodsoni.in` instead of the render.com address.

---

## Step 2 — Put the webapp on pramodsoni.in

1. Upload the **contents of `webapp/`** (`index.html`, `manifest.webmanifest`,
   `sw.js`, `icon.svg`) into a folder on your site, e.g. `/omr/`.
2. Visit **https://pramodsoni.in/omr/** on your phone.
3. Tap **⚙️ (top-right) → Backend URL**, paste your backend address
   (`https://omr-api.onrender.com`), tap **Save & test** → should show *Connected*.
4. Tap the browser menu → **Add to Home Screen** to install it like an app.

That's it. The URL is saved on the device, so you set it only once per phone.

---

## Daily use

1. **Setup tab** → enter questions/options/roll digits/sets/№ sheets → *Generate* →
   download & print the PDF.
2. **Key tab** → upload the answer key (`.xlsx`/`.csv`, one column per set).
3. **Scan tab** → photograph filled sheets (all 4 corner markers in frame) →
   *Grade* → see marks, download the Excel marksheet, view the checked sheet.

---

## Alternative: all-in-one (no split)

The backend can also serve the frontend itself (it already does, at `/`). So you
could just deploy `backend/` to Render and use `https://omr-api.onrender.com`
directly, linking to it from pramodsoni.in. Hosting the static frontend on your
own site (the split above) is only needed if you want the app to live under the
pramodsoni.in domain.

---

## HTTPS

Camera access and the service worker require **HTTPS**. pramodsoni.in and the
Render URL are both HTTPS, so this is already satisfied — just don't use a plain
`http://` backend address.
