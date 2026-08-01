# Server

One Flask app on the laptop. It serves the operator console, runs the pipeline,
holds the queue, and owns the only connection to the plotter.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # then check PLOTTER_HOST
.venv/bin/python app.py
```

Console at <http://localhost:5050/console>.

**Not port 5000** — macOS AirPlay Receiver holds that one, and it answers HTTP,
so a server that failed to start looks like a server returning strange replies.

The OpenAI key is read from `../../src/.env`, the same one the week 10 scripts
use. No second copy.

## The kiosk camera, and why HTTPS

The kiosk has two capture paths and picks one at runtime:

| | Needs | Gives you |
|---|---|---|
| live viewfinder | HTTPS | preview, oval framing guide, 3-2-1 countdown |
| native camera sheet | nothing | iOS takes the photo, hands it back |

`getUserMedia` only exists in a **secure context**, so over plain
`http://something.local:5050` Safari does not offer the camera at all — the
kiosk detects that and falls back to the sheet. Everything downstream is
identical either way.

To get the viewfinder, once:

```bash
brew install mkcert
mkcert -install          # asks for your password
./certs.sh
```

Then on the iPad, once:

1. AirDrop yourself `rootCA.pem` (the path is printed by `certs.sh`)
2. Open it → Settings shows *Profile Downloaded* → Install
3. **Settings → General → About → Certificate Trust Settings → turn the mkcert
   root ON**

Step 3 is the one people miss. Installing the profile is not enough; iOS keeps
the root untrusted until that switch is flipped, and Safari will just refuse
the page with no useful explanation.

`app.py` picks the certs up automatically if `certs/` exists, and says which
mode it started in.

## The iPad itself

- **Guided Access** (Settings → Accessibility) locks it into the one app so
  visitors cannot wander into Safari or your email. Triple-click to arm it.
- **Auto-lock off**, and keep it plugged in.
- **Add to Home Screen** → runs fullscreen with no browser chrome. The manifest
  and Apple meta tags are already in the page.
- The framing guide is not decoration. The pipeline wants head-and-shoulders on
  a plain background; a busy background turns into hundreds of stray strokes.

## Layout

| File | Does |
|---|---|
| `app.py` | routes, and nothing else |
| `machine.py` | the only thing that talks to the ESP32 |
| `pipeline.py` | the three steps as functions, importing `src/src` |
| `jobs.py` | the job store — folders are the state |

## Jobs

`jobs/` holds one folder per job, and the parent folder is the state:
`working` → `queue` → `done`, with `failed` off to the side.

Changing state is one `os.rename`, so nothing can end up half-moved, and there
is no index to drift out of sync. Anything can be fixed in Finder — drag a
folder from `done/` back to `queue/` to plot it again, delete one to drop it.

Job numbers are the ticket numbers the kiosk shows, and they never repeat: the
next one is the highest folder number anywhere, plus one.

On startup anything still in `working/` is swept to `failed/`. A job caught
mid-generation by a restart lost its API call and nothing is coming back for it.

`jobs/` is gitignored — it is a scratch directory that fills up at the fair.

## Endpoints

Kiosk (reachable from the iPad):

| Route | Does |
|---|---|
| `POST /api/capture` | photo + style in, job id out; generation starts in the background |
| `GET /api/job/<id>` | poll: state, stats, which files exist |
| `GET /api/job/<id>/file/<name>` | `line_art.png`, `preview.svg`, `job.gcode`, `photo.*` |
| `GET /api/queue` | what is waiting |

Generation moves a job straight into the queue — there is no keep-or-retake
step, because the kiosk never shows anyone their drawing.

Console (127.0.0.1 only — no auth code, just an address check):

| Route | Does |
|---|---|
| `GET /console` | the operator page |
| `GET /api/console/jobs` | every job, by state |
| `POST /api/console/job/<id>/plot` | upload to the board, then draw |
| `POST /api/console/job/<id>/done` | mark plotted by hand, if the board's message was missed |
| `GET /api/console/sheet` + `/sheet/new` + `/slot/<slot>/go` | the 3×2 grid, fresh paper, jog to a cell |
| `POST /api/console/job/<id>/retrace` | re-run steps 2–3 harder — free, no API call |
| `POST /api/console/job/<id>/regenerate` | new AI roll, any of the five styles — costs a call |
| `DELETE /api/console/job/<id>` | delete |
| `POST /api/machine/<action>` | `home`, `pen_up`, `pen_down`, `circle`, `stop` |
| `POST /api/machine/jog` | `{x, y}` in whole mm |
| `GET /api/gcodes` + `/<name>/plot` | plot a file from `src/output` — the phase 1 path |

The kiosk offers `chibi` and `pixar` only, and the server enforces it rather
than trusting the page. The console can use all five when regenerating.

## Things that are true and easy to forget

**The firmware reports endings, not progress.** It pushes `done`, `stopped` or
`aborted` when a job finishes and `homed` after homing, so the console clears
itself and files the drawing. Nothing arrives *during* a job — watch the pen.

Only `done` counts as a finished drawing. `runFile()` exits identically whether
the file ran out, the operator hit stop, or a move went off the bed, so the
other two put the job back in the queue with an error instead of claiming a
slot it never occupied. Mark done is still there for when a message is missed.

**Wait for `"stored"` before drawing.** `machine.plot()` does. The upload
replaces `/job.gcode` with `FILE_WRITE`, so starting a job on a half-written
file plots a truncated drawing.

**A server restart does not stop a drawing.** The G-code is already on the
board's flash. Coming back up just means the server no longer knows the job is
running.

**Never `from_photo=True`.** `vectorize.py` has an edge-detection path for
photos. It is not used here and should not be.
