# -*- coding: utf-8 -*-
"""
OMR Evaluation — offline desktop launcher.

Runs the OMR engine as a local web server (127.0.0.1) and opens it in a native
app window. Fully offline. When packaged with PyInstaller it becomes a single
Windows app you can run from a USB stick; exams are stored next to the .exe in
an "OMR_data" folder, so your data travels with the USB.
"""
import os
import sys
import time
import socket
import threading


def _frozen():
    return getattr(sys, "frozen", False)


def app_dir():
    """Folder the user launched from (next to the .exe), for data storage."""
    if _frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_dir():
    """Folder holding bundled code/data (PyInstaller _MEIPASS, else project root)."""
    if _frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # OMR_APP


# ---- configure the server BEFORE importing it --------------------------------
RES = resource_dir()
os.environ.setdefault("OMR_DATA_DIR", os.path.join(app_dir(), "OMR_data"))
os.environ.setdefault("OMR_STATIC_DIR", os.path.join(RES, "static"))
sys.path.insert(0, RES)                       # omr_generator / omr_reader
sys.path.insert(0, os.path.join(RES, "backend"))  # server


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


PORT = int(os.environ.get("OMR_PORT") or free_port())
URL = f"http://127.0.0.1:{PORT}/"


def run_server():
    import asyncio
    import uvicorn
    from server import app
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    asyncio.run(server.serve())           # uvicorn skips signal handlers off-main-thread


def wait_until_up(timeout=30):
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(URL + "health", timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def main():
    threading.Thread(target=run_server, daemon=True).start()
    if not wait_until_up():
        print("ERROR: server did not start", flush=True)
        return
    if os.environ.get("OMR_HEADLESS"):          # test/verify mode: no window
        print("READY", URL, flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return
    try:
        import webview
        webview.create_window("OMR Evaluation (offline)", URL,
                              width=1150, height=850, min_size=(800, 600))
        webview.start()                    # blocks until the window is closed
    except Exception:
        # fallback: open in the default browser and keep the server alive
        import webbrowser
        webbrowser.open(URL)
        print("OMR Evaluation is running at", URL)
        print("Keep this window open while using the app. Close it to quit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
