# Demo video

```bash
make demo-video        # -> build/demo/demo-720p.mp4
```

A side-by-side walkthrough: two browser sessions, four users, one recording,
downscaled to 1280×720. The runner is `demo/runner.py`; it runs entirely inside
the Playwright container, which also carries the app's runtime.

The committed copy is [`docs/assets/demo-720p.mp4`](../../docs/assets/demo-720p.mp4),
with a still per beat in `docs/assets/`.

## The storyline

| Beat | Left | Right |
|---|---|---|
| 1 | *Two sessions, two lawyers* | |
| 2 | `lawyer-001` signs in | `lawyer-002` signs in |
| 3 | searches `indemnification` | searches `governing law` |
| 4 | opens a contract | opens a contract |
| 5 | signs out | signs out |
| 6 | *Admin and auditor* | `admin` signs in | `auditor` signs in |
| 7 | the user list | (Reports) |
| 8 | runs a search | Logins report |
| 9 | | Searches report |
| 10 | | Documents report |
| 11 | | Activity feed |

The banner in the header is also the narration, so there is no voiceover.

## Why it is built this way

**One page, one recording.** Both sessions are iframes inside a single
2560×1440 page, so there is exactly one video. There is no compositing step and
the two panes cannot drift apart.

The obvious alternative — two browser contexts, two recordings, `ffmpeg hstack`
— looks simpler and is not: each recording starts and stops independently, so it
needs beat-level re-synchronisation to stop the left pane signing in while the
right pane is already reading a document.

**Recorded at 1440p, delivered at 720p.** Each pane gets ~1270px of real layout
width, so the app renders comfortably and the stills stay legible.

**Never use CSS `zoom` to fit the app into a narrow pane.** Chromium reports
element boxes unzoomed, so click coordinates come out wrong by the zoom factor.
It appears to work near the top-left corner and misses everywhere else.

## Running it

```bash
make demo-video
```

Requires Docker, a working `.env`, and `credentials.txt` (`make users`).

Two things it does that you should know about:

- **It clears `ACCESS_LOG` first**, so the auditor's report narrates only the
  video rather than accumulated history. That needs `ACCOUNTADMIN`, so it uses
  `.env`, not the service identity.
- **It reads `credentials.txt` at runtime.** Passwords rotate on every rebuild,
  so hardcoded ones would silently break. Passwords render masked in the UI, so
  they do not leak into the video.

## Outputs

| File | What |
|---|---|
| `demo-720p.mp4` | 1280×720 h264, the deliverable |
| `demo.webm` | raw 2560×1440 recording |
| `gallery/*.png` | a still at each beat |
| `FAIL.txt`, `FAIL-*.png` | written only when a beat fails |
| `streamlit-*.log` | app logs, for when a beat fails |

The failure diagnostics are worth keeping: when a beat fails the runner dumps
each frame's URL and body text, which is how the `aria-label="Open"` collision
was found.

## Tuning

`TARGET_SECONDS` pads the recording to a duration; the runner takes roughly 48s
of storyline as scripted, and the waits (not the holds) dominate — the first
sign-in pair alone is ~11s on a cold app.

Edit the beats at the bottom of `demo/runner.py`. Each `beats.banner(...)` is
both a step and its narration, so changing one changes the video.
