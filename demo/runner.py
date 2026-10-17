#!/usr/bin/env python3
"""Build the side-by-side demo video.

Runs entirely inside the Playwright container: starts two Streamlit instances
(one per pane), serves a synthetic showcase page with both sessions in iframes,
drives four users through a scripted storyline, records one video, downscales
to 1280x720.

One page, one context, one recording. Both panes are in the same frame, so the
two sessions cannot drift apart - there is no compositing step.

Deliverables in /artifacts:
  demo.webm        raw recording
  demo-720p.mp4    1280x720 h264, the thing you would post
  gallery/*.png    a still at each beat
  FAIL.txt, FAIL-*.png   diagnostics, only when a beat fails
  streamlit-*.log  app logs
"""
from __future__ import annotations

import http.server
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
ARTIFACTS = Path(os.environ.get("ARTIFACTS_DIR", "/artifacts"))
GALLERY = ARTIFACTS / "gallery"

LEFT_PORT = int(os.environ.get("LEFT_PORT", "8501"))
RIGHT_PORT = int(os.environ.get("RIGHT_PORT", "8502"))
SHOWCASE_PORT = int(os.environ.get("SHOWCASE_PORT", "4173"))

# Recorded at 1440p and downscaled to 720p, so each pane gets ~1270px of real
# layout width: the app renders at a comfortable size and Playwright's
# coordinate-based clicks stay accurate.
#
# Do NOT try to fit the app into a narrow pane with CSS `zoom`. Chromium
# reports element boxes unzoomed, so click coordinates come out wrong by the
# zoom factor - it appears to work near the top-left corner and silently misses
# everywhere else.
RECORD_W, RECORD_H = 2560, 1440
DELIVER_W, DELIVER_H = 1280, 720
SCALE = RECORD_W / 1280  # chrome typography, sized to survive the downscale

TARGET_SECONDS = float(os.environ.get("TARGET_SECONDS", "34"))
APP = "app/streamlit_app.py"


# --- showcase page -----------------------------------------------------------

def showcase_html() -> str:
    s = int
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<title>CUAD Contract Review - side by side</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: {RECORD_W}px; height: {RECORD_H}px; overflow: hidden;
    background: radial-gradient(circle at 50% 0%, #172033 0%, #0b0f17 75%);
    color: #f3f4f6; display: flex; flex-direction: column; gap: {s(12*SCALE)}px;
    padding: {s(16*SCALE)}px {s(20*SCALE)}px {s(18*SCALE)}px;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }}
  header {{
    display: flex; align-items: center; justify-content: space-between;
    padding: {s(12*SCALE)}px {s(20*SCALE)}px; background: rgba(17,24,39,0.9);
    border: 1px solid rgba(56,189,248,0.28); border-radius: {s(12*SCALE)}px;
  }}
  .brand {{ display: flex; align-items: baseline; gap: {s(14*SCALE)}px; }}
  .brand h1 {{ font-size: {s(21*SCALE)}px; font-weight: 700; }}
  .brand span {{ font-size: {s(15*SCALE)}px; color: #9ca3af; }}
  #stage {{
    font-size: {s(15*SCALE)}px; font-weight: 600;
    padding: {s(7*SCALE)}px {s(16*SCALE)}px; border-radius: 999px;
    background: rgba(16,185,129,0.16); color: #34d399;
    border: 1px solid rgba(16,185,129,0.4);
  }}
  .grid {{ flex: 1; display: grid; grid-template-columns: 1fr 1fr;
           gap: {s(16*SCALE)}px; min-height: 0; }}
  .card {{
    display: flex; flex-direction: column; background: #fff;
    border-radius: {s(12*SCALE)}px; overflow: hidden;
    border: 2px solid rgba(148,163,184,0.3);
    box-shadow: 0 14px 32px rgba(0,0,0,0.45); min-height: 0;
  }}
  .card.a {{ border-color: rgba(56,189,248,0.55); }}
  .card.b {{ border-color: rgba(167,139,250,0.55); }}
  .chrome {{
    display: flex; align-items: center; justify-content: space-between;
    padding: {s(9*SCALE)}px {s(14*SCALE)}px; background: #111827;
    color: #e5e7eb; font-size: {s(13*SCALE)}px;
  }}
  .left {{ display: flex; align-items: center; gap: {s(10*SCALE)}px; font-weight: 700; }}
  .dots i {{ width: {s(10*SCALE)}px; height: {s(10*SCALE)}px; border-radius: 50%;
             display: inline-block; margin-right: {s(4*SCALE)}px; }}
  .dots i:nth-child(1) {{ background: #ef4444; }}
  .dots i:nth-child(2) {{ background: #f59e0b; }}
  .dots i:nth-child(3) {{ background: #10b981; }}
  .tag {{ padding: {s(3*SCALE)}px {s(9*SCALE)}px; border-radius: 6px;
          font-size: {s(12*SCALE)}px; font-weight: 700; }}
  .a .tag {{ background: rgba(56,189,248,0.2); color: #38bdf8; }}
  .b .tag {{ background: rgba(167,139,250,0.2); color: #c4b5fd; }}
  .origin {{
    font-family: ui-monospace, Menlo, monospace; font-size: {s(12*SCALE)}px;
    color: #9ca3af; background: #1f2937;
    padding: {s(3*SCALE)}px {s(9*SCALE)}px; border-radius: 5px;
  }}
  iframe {{ flex: 1; width: 100%; border: 0; background: #fff; }}
</style></head>
<body>
  <header>
    <div class="brand"><h1>CUAD Contract Review</h1>
      <span>510 contracts &middot; 41 clause categories &middot; 3 roles</span></div>
    <div id="stage">1 &middot; Two sessions, two lawyers</div>
  </header>
  <div class="grid">
    <section class="card a">
      <div class="chrome"><div class="left">
        <span class="dots"><i></i><i></i><i></i></span>
        <span>BROWSER A</span><span class="tag" id="tag-a">lawyer-001</span></div>
        <span class="origin">localhost:{LEFT_PORT}</span></div>
      <iframe id="frame-a" src="http://127.0.0.1:{LEFT_PORT}/"></iframe>
    </section>
    <section class="card b">
      <div class="chrome"><div class="left">
        <span class="dots"><i></i><i></i><i></i></span>
        <span>BROWSER B</span><span class="tag" id="tag-b">lawyer-002</span></div>
        <span class="origin">localhost:{RIGHT_PORT}</span></div>
      <iframe id="frame-b" src="http://127.0.0.1:{RIGHT_PORT}/"></iframe>
    </section>
  </div>
</body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = showcase_html().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def start_showcase_server() -> http.server.HTTPServer:
    server = http.server.HTTPServer(("127.0.0.1", SHOWCASE_PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# --- app processes -----------------------------------------------------------

def start_app(port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env.setdefault("CUAD_ENV_FILE", ".env")
    log = (ARTIFACTS / f"streamlit-{port}.log").open("w")
    return subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", APP,
         "--server.port", str(port),
         "--server.address", "127.0.0.1",
         "--server.headless", "true"],
        cwd=WORKSPACE, env=env, stdout=log, stderr=subprocess.STDOUT,
    )


def wait_for_app(port: int, timeout: float = 90) -> None:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/_stcore/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.read().strip() == b"ok":
                    return
        except (urllib.error.URLError, OSError, ConnectionError):
            pass
        time.sleep(0.5)
    raise RuntimeError(
        f"app on {port} never became healthy; see {ARTIFACTS}/streamlit-{port}.log"
    )


# --- credentials and audit reset ---------------------------------------------

def read_credentials() -> dict[str, str]:
    path = WORKSPACE / "credentials.txt"
    if not path.exists():
        raise SystemExit("credentials.txt not found; run `make users` first")
    found: dict[str, str] = {}
    for line in path.read_text().splitlines():
        match = re.match(r"^(\S+)\s+(\S+)\s+(\S+)\s+", line)
        if match:
            found[match.group(1)] = match.group(3)
    return found


def clear_audit_log() -> None:
    """Start from an empty audit log so the report narrates only this video."""
    sys.path.insert(0, str(WORKSPACE / "scripts"))
    from sf import connect  # noqa: PLC0415

    with connect(env_file=os.environ.get("CUAD_ENV_FILE", ".env"),
                 database="CUAD_DB", schema="CORPUS") as conn:
        conn.cursor().execute("DELETE FROM ACCESS_LOG")
    print("  cleared ACCESS_LOG")


# --- beats -------------------------------------------------------------------

class Beats:
    def __init__(self, page, left, right):
        self.page = page
        self.left = left
        self.right = right
        self.started = time.time()

    def elapsed(self) -> float:
        return time.time() - self.started

    def banner(self, text, left_tag=None, right_tag=None) -> None:
        self.page.evaluate(
            """([text, lt, rt]) => {
                document.getElementById('stage').textContent = text;
                if (lt) document.getElementById('tag-a').textContent = lt;
                if (rt) document.getElementById('tag-b').textContent = rt;
            }""",
            [text, left_tag, right_tag],
        )
        print(f"  [{self.elapsed():5.1f}s] {text}")

    def hold(self, seconds: float) -> None:
        time.sleep(seconds)

    def shot(self, name: str) -> None:
        self.page.screenshot(path=str(GALLERY / f"{name}.png"))


def sign_in(frame, user: str, password: str, expect: str) -> None:
    frame.locator('input[placeholder="lawyer-001"]').fill(user)
    frame.locator('input[type="password"]').fill(password)
    frame.get_by_role("button", name="Sign in").click()
    frame.get_by_text(expect, exact=False).first.wait_for(timeout=30000)


def sign_out(frame) -> None:
    frame.get_by_role("button", name="Sign out").click()
    frame.get_by_text("Sign in", exact=False).first.wait_for(timeout=30000)


def search(frame, term: str) -> None:
    frame.locator('input[placeholder="title, counterparty, clause"]').fill(term)
    frame.get_by_role("button", name="Search").first.click()
    frame.get_by_text("Clause text matches", exact=False).first.wait_for(timeout=30000)


def open_first_document(frame) -> None:
    frame.get_by_text("Clause text matches", exact=False).first.wait_for(timeout=30000)
    # exact=True matters. get_by_role matches accessible names as substrings by
    # default, so name="Open" also matches Streamlit's "Open sidebar" button -
    # which is first in the DOM. The click silently toggles the sidebar instead
    # of opening a document.
    # Scope to the main content. Streamlit's own facet dropdowns in the sidebar
    # carry aria-label="Open" and come first in DOM order, so an unscoped
    # get_by_role(name="Open") resolves to a dropdown toggle and the click
    # silently opens a multiselect instead of a document.
    main = frame.locator('[data-testid="stMain"]')
    button = main.get_by_role("button", name="Open", exact=True).first
    button.scroll_into_view_if_needed()
    button.click()
    frame.get_by_text("Related contracts", exact=False).first.wait_for(timeout=30000)


# --- diagnostics -------------------------------------------------------------

def diagnose(page, left, right) -> None:
    """Dump what is actually on screen when a beat fails."""
    print("  --- diagnostics ---")
    try:
        for frame in page.frames:
            print(f"  frame url: {frame.url}")
        page.screenshot(path=str(GALLERY / "FAIL-page.png"))
        chunks = ["frame urls: " + " | ".join(f.url for f in page.frames)]
        for name, frame in (("left", left), ("right", right)):
            chunks.append(f"===== {name} =====")
            try:
                chunks.append(frame.locator("body").inner_text(timeout=5000))
            except Exception as exc:  # noqa: BLE001
                chunks.append(f"(unreadable: {exc})")
            try:
                frame.screenshot(path=str(GALLERY / f"FAIL-{name}.png"))
            except Exception:  # noqa: BLE001
                pass
        (ARTIFACTS / "FAIL.txt").write_text("\n".join(chunks))
        print(f"  wrote {ARTIFACTS}/FAIL.txt")
    except Exception as exc:  # noqa: BLE001
        print(f"  diagnostics failed: {exc}")


# --- storyline ---------------------------------------------------------------

def storyline(beats, left, right, creds) -> None:
    for frame in (left, right):
        frame.get_by_text("Sign in", exact=False).first.wait_for(timeout=30000)
    beats.started = time.time()

    beats.banner("1 · Two sessions, two lawyers")
    beats.hold(1.5)

    beats.banner("2 · Signing in")
    sign_in(left, "lawyer-001", creds["lawyer-001"], "510 contracts")
    sign_in(right, "lawyer-002", creds["lawyer-002"], "510 contracts")
    beats.hold(1.5)
    beats.shot("01-two-lawyers-signed-in")

    beats.banner("3 · Searching clause text")
    search(left, "indemnification")
    search(right, "governing law")
    beats.hold(1.5)
    beats.shot("02-clause-search")

    beats.banner("4 · Opening a contract")
    open_first_document(left)
    open_first_document(right)
    beats.hold(2.5)
    beats.shot("03-document-and-related")

    beats.banner("5 · Signing out")
    sign_out(left)
    sign_out(right)
    beats.hold(1.0)

    beats.banner("6 · Admin and auditor", "admin", "auditor")
    sign_in(left, "admin", creds["admin"], "Contracts")
    sign_in(right, "auditor", creds["auditor"], "Access reports")
    beats.hold(1.0)

    beats.banner("7 · Who has access")
    left.get_by_role("button", name="Admin").click()
    left.get_by_text("Create user", exact=False).first.wait_for(timeout=30000)
    beats.hold(3.0)
    beats.shot("04-admin-users")

    beats.banner("8 · Every login, audited")
    right.get_by_text("Logins", exact=True).first.click()
    beats.hold(3.0)
    beats.shot("05-audit-logins")

    beats.banner("9 · Searches, by user and term")
    search(left, "governing law")
    right.get_by_text("Searches", exact=True).first.click()
    beats.hold(3.0)
    beats.shot("06-audit-searches")

    beats.banner("10 · Every document opened")
    right.get_by_text("Documents", exact=True).first.click()
    beats.hold(3.0)
    beats.shot("07-audit-documents")

    beats.banner("11 · The whole trail")
    right.get_by_text("Activity", exact=True).first.click()
    beats.hold(3.0)
    beats.shot("08-audit-activity")

    remaining = TARGET_SECONDS - beats.elapsed()
    if remaining > 0:
        beats.hold(remaining)
    print(f"  [{beats.elapsed():5.1f}s] storyline complete")


# --- main --------------------------------------------------------------------

def run(creds: dict[str, str]) -> None:
    from playwright.sync_api import sync_playwright

    server = start_showcase_server()
    apps = [start_app(LEFT_PORT), start_app(RIGHT_PORT)]
    try:
        print("waiting for both Streamlit instances...")
        for port in (LEFT_PORT, RIGHT_PORT):
            wait_for_app(port)
            print(f"  {port} healthy")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": RECORD_W, "height": RECORD_H},
                record_video_dir=str(ARTIFACTS),
                record_video_size={"width": RECORD_W, "height": RECORD_H},
            )
            page = context.new_page()
            page.goto(f"http://127.0.0.1:{SHOWCASE_PORT}/", wait_until="domcontentloaded")

            left = page.frame_locator("#frame-a")
            right = page.frame_locator("#frame-b")
            beats = Beats(page, left, right)

            try:
                storyline(beats, left, right, creds)
            except Exception:
                diagnose(page, left, right)
                raise

            video = page.video  # property, not a method
            context.close()  # flushes the recording
            browser.close()

            raw = Path(video.path())
            target = ARTIFACTS / "demo.webm"
            shutil.copyfile(raw, target)
            if raw != target:
                raw.unlink()
            print(f"  raw recording: {target}")
    finally:
        for app in apps:
            app.terminate()
        server.shutdown()


def encode() -> None:
    src = ARTIFACTS / "demo.webm"
    out = ARTIFACTS / "demo-720p.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src),
         "-vf", f"scale={DELIVER_W}:{DELIVER_H}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-r", "30", str(out)],
        check=True, capture_output=True,
    )
    print(f"  delivered: {out}")


def main() -> int:
    GALLERY.mkdir(parents=True, exist_ok=True)
    if not (WORKSPACE / APP).exists():
        raise SystemExit(f"{WORKSPACE / APP} not found; mount the repo at {WORKSPACE}")

    print(f"credentials from {WORKSPACE}/credentials.txt")
    creds = read_credentials()
    missing = [u for u in ("lawyer-001", "lawyer-002", "admin", "auditor")
               if u not in creds]
    if missing:
        raise SystemExit(f"credentials.txt is missing: {', '.join(missing)}; run `make users`")

    clear_audit_log()
    run(creds)
    encode()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
