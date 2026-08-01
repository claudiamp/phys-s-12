"""Phase 1 — the server drives the machine.

One Flask app. For now it serves only the operator console; the kiosk arrives
in phase 3 and shares this process.

Run it:

    python app.py

then open http://localhost:5050/console
"""

import os
import socket
import threading
import time

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))

# Loaded BEFORE importing pipeline, and that ordering matters: gcode.py reads
# PEN_UP_CMD / PEN_DOWN_CMD / PEN_DELAY_MS into module constants at import
# time. Load the .env after that import and those settings silently do
# nothing, which is a maddening thing to debug.
load_dotenv(os.path.join(HERE, ".env"))
# The OpenAI key already lives in the week 10 pipeline's .env. Reuse it rather
# than keeping a second copy; anything set here or in the environment wins.
load_dotenv(os.path.join(HERE, "..", "..", "src", ".env"), override=False)

from flask import Flask, jsonify, render_template, request, send_from_directory  # noqa: E402

import pipeline                                            # noqa: E402
from jobs import JobStore                                   # noqa: E402
from machine import Machine, MachineError, MachineOffline   # noqa: E402

PLOTTER_HOST = os.environ.get("PLOTTER_HOST", "plotter.local")
GCODE_DIR = os.path.abspath(
    os.environ.get("GCODE_DIR", os.path.join(HERE, "..", "..", "src", "output"))
)
JOBS_DIR = os.path.abspath(os.environ.get("JOBS_DIR", os.path.join(HERE, "jobs")))
PORT = int(os.environ.get("PORT", "5050"))

BED = tuple(float(v) for v in os.environ.get("BED_MM", "100x100").lower().split("x"))
# Measured travel, and where the usable area starts. The first 30mm of Y are
# not trustworthy on this machine, so drawings begin above it -- the head can
# still be jogged down there, it just is not drawn on.
MACHINE = tuple(float(v) for v in os.environ.get("MACHINE_MM", "350x250").lower().split("x"))
ORIGIN = tuple(float(v) for v in os.environ.get("ORIGIN_MM", "0x30").lower().split("x"))
# Blank space between drawings, so there is somewhere to put the scissors.
# The G-code's own 5mm margin already leaves 10mm between neighbours; this is
# on top of that.
GAP = tuple(float(v) for v in os.environ.get("GAP_MM", "20x0").lower().split("x"))

app = Flask(__name__)
# Jinja caches compiled templates for the life of the process when debug is
# off, so an edit to kiosk.html would not show up until a restart -- and the
# stale page looks exactly like a change that did not work.
app.config["TEMPLATES_AUTO_RELOAD"] = True

store = JobStore(JOBS_DIR)
machine = Machine(PLOTTER_HOST, limits=MACHINE,
                  on_event=lambda msg: on_machine_event(msg))

# What the console believes is on the machine right now. The firmware never
# says "finished" -- it prints "file done" to serial and nothing else -- so
# this is set on PLAY and cleared when the operator marks the job done. It is
# a note to the operator, not a fact about the hardware.
#
# started/estimate exist so the console can say "this should have finished by
# now" instead of showing "drawing" forever and looking stuck.
current = {"id": None, "slot": None, "started": None, "estimate": None}


def _clear_current():
    current.update(id=None, slot=None, started=None, estimate=None)


def on_machine_event(message):
    """The board telling us how a job ended. Runs on the reader thread.

    Only "done" means the whole file was drawn. "stopped" is the operator
    hitting stop, "aborted" is a move landing off the bed -- neither of those
    is a finished drawing, so they go back to the queue rather than being
    filed as done with a slot they never really occupied.
    """
    job = store.get(current["id"]) if current["id"] else None
    elapsed = (int(time.monotonic() - current["started"])
               if current["started"] is not None else None)

    if message == "done":
        if job is not None and job.state == "queue":
            data = job.meta()
            store.move(job, "done",
                       sheet=data.get("sheet", store.sheet()),
                       slot=data.get("slot", current["slot"]),
                       # What it really took, against what we predicted. This
                       # is what ESTIMATE_SCALE gets re-derived from.
                       plot_seconds=elapsed,
                       predicted_seconds=current["estimate"])
        _clear_current()

    elif message in ("stopped", "aborted"):
        if job is not None:
            job.update(error=("stopped by the operator" if message == "stopped"
                              else "a move landed off the bed"),
                       slot=None)
        _clear_current()

    # "homed", "New client: 3", and anything else is chatter.


def slot_grid():
    """The sheet as a grid of drawing-sized cells, bottom-left origin.

    Only whole drawings fit, so the grid is the usable area divided down and
    the remainder left as margin. Measured 350x250 with the bottom 30mm of Y
    skipped gives 350x220 usable; at 100x100 with a 20mm cutting gap in X that
    is 3 across and 2 up: six portraits between paper changes.
    """
    usable_w = MACHINE[0] - ORIGIN[0]
    usable_h = MACHINE[1] - ORIGIN[1]

    # Drawings sit on a pitch of their own size plus the gap. The last one in a
    # row needs no gap after it, hence the +GAP on both sides of the divide.
    pitch_x, pitch_y = BED[0] + GAP[0], BED[1] + GAP[1]
    cols = max(1, int((usable_w + GAP[0]) // pitch_x))
    rows = max(1, int((usable_h + GAP[1]) // pitch_y))

    used = store.slots_used()
    cells = []
    for row in range(rows - 1, -1, -1):          # top row first, for display
        for col in range(cols):
            x = int(ORIGIN[0] + col * pitch_x)
            y = int(ORIGIN[1] + row * pitch_y)
            name = f"{x},{y}"
            cells.append({"slot": name, "x": x, "y": y, "used_by": used.get(name)})

    return {
        "sheet": store.sheet(), "cols": cols, "rows": rows, "cells": cells,
        "machine": f"{int(MACHINE[0])}x{int(MACHINE[1])}",
        "origin": f"{int(ORIGIN[0])},{int(ORIGIN[1])}",
        "gap": f"{int(GAP[0])},{int(GAP[1])}",
    }


# ----------------------------------------------------------------------
# The console is operator-only
# ----------------------------------------------------------------------
#
# No auth code: the console answers on 127.0.0.1 only, so it is reachable from
# this laptop and from nowhere else. The kiosk (phase 3) will be served on the
# same port to everyone, and there is no path from one to the other.

def _is_local(remote):
    return remote in ("127.0.0.1", "::1")


CONSOLE_PREFIXES = ("/console", "/api/machine", "/api/gcodes", "/api/console")


@app.before_request
def guard_console():
    path = request.path
    if path.startswith(CONSOLE_PREFIXES) and not _is_local(request.remote_addr):
        return jsonify(error="console is local-only"), 403
    return None


# ----------------------------------------------------------------------
# Errors from the machine become useful JSON instead of a 500
# ----------------------------------------------------------------------

@app.errorhandler(MachineOffline)
def _offline(exc):
    return jsonify(ok=False, error=str(exc)), 503


@app.errorhandler(MachineError)
def _machine_error(exc):
    return jsonify(ok=False, error=str(exc)), 409


@app.errorhandler(ValueError)
def _bad_value(exc):
    return jsonify(ok=False, error=str(exc)), 400


@app.errorhandler(pipeline.PipelineError)
def _pipeline_error(exc):
    return jsonify(ok=False, error=str(exc)), 400


# ----------------------------------------------------------------------
# Kiosk
# ----------------------------------------------------------------------
#
# Served to everyone, at the root, because that is what someone types on the
# iPad: http://<laptop>.local:5050

@app.get("/")
def kiosk():
    return render_template("kiosk.html")


# ----------------------------------------------------------------------
# Console
# ----------------------------------------------------------------------

@app.get("/console")
def console():
    return render_template(
        "console.html",
        host=PLOTTER_HOST,
        gcode_dir=GCODE_DIR,
        styles=pipeline.ALL_STYLES,
        plot_rotate=pipeline.ROTATE_180,
    )


@app.get("/api/machine/status")
def machine_status():
    now = dict(current)
    if now["started"] is not None:
        now["elapsed"] = int(time.monotonic() - now["started"])
        now["overdue"] = bool(now["estimate"] and now["elapsed"] > now["estimate"])
    now.pop("started", None)
    return jsonify(dict(machine.status(), current=now))


@app.post("/api/machine/<action>")
def machine_action(action):
    actions = {
        "home": machine.home,
        "pen_up": machine.pen_up,
        "pen_down": machine.pen_down,
        "circle": machine.test_circle,
        "stop": machine.stop,
    }
    if action not in actions:
        return jsonify(ok=False, error=f"unknown action {action!r}"), 404
    actions[action]()
    if action == "stop":
        # runFile() breaks out of the file, so nothing is drawing any more.
        _clear_current()
    return jsonify(ok=True, sent=action)


@app.post("/api/machine/jog")
def machine_jog():
    body = request.get_json(silent=True) or {}
    machine.jog(body.get("x", 0), body.get("y", 0))
    return jsonify(ok=True, sent=f"{int(body.get('x', 0))},{int(body.get('y', 0))}")


# ----------------------------------------------------------------------
# G-code files
# ----------------------------------------------------------------------
#
# Phase 1 plots files that already exist. Phase 2 replaces this with jobs
# generated from a photo.

@app.get("/api/gcodes")
def list_gcodes():
    if not os.path.isdir(GCODE_DIR):
        return jsonify(dir=GCODE_DIR, files=[], error="directory not found")
    names = sorted(n for n in os.listdir(GCODE_DIR) if n.endswith(".gcode"))
    return jsonify(dir=GCODE_DIR, files=names)


def _resolve_gcode(name):
    """Turn a filename into a path inside GCODE_DIR, and nothing outside it."""
    path = os.path.abspath(os.path.join(GCODE_DIR, name))
    if os.path.dirname(path) != GCODE_DIR or not path.endswith(".gcode"):
        raise ValueError(f"not a G-code file in {GCODE_DIR}: {name!r}")
    if not os.path.isfile(path):
        raise ValueError(f"no such file: {name!r}")
    return path


@app.post("/api/gcodes/<name>/plot")
def plot_gcode(name):
    path = _resolve_gcode(name)
    machine.plot(path)
    return jsonify(ok=True, plotting=name)


# ----------------------------------------------------------------------
# Jobs
# ----------------------------------------------------------------------
#
# Generation runs at capture time, in a background thread, so the slow part
# (OpenAI, 10-30s) overlaps with the queue wait and PLAY starts the machine
# straight away. The kiosk polls; it never holds a request open, because Safari
# suspends backgrounded pages and a locked iPad would kill it.

def _generate(job, photo_name, style):
    """Runs off the request thread. Ends with the job in queue/ or failed/.

    Straight into the queue, with no stop for approval: the visitor never sees
    the drawing before it is made, the same way you do not watch a caricature
    artist work. The operator is the only reviewer, and does it from the
    console while the machine is busy with the previous job.
    """
    try:
        pipeline.generate_line_art(job.path(photo_name), job.path("line_art.png"), style)
        stats = pipeline.trace(
            job.path("line_art.png"), job.path("job.gcode"), job.path("preview.svg"),
            bed=BED,
        )
        job.update(stats=stats, estimate=pipeline.estimate_text(stats))
        store.move(job, "queue")
    except Exception as exc:
        job.update(error=str(exc))
        store.move(job, "failed", reason="generation failed")


def _queue_position(job):
    ids = [j.id for j in store.list("queue")]
    return ids.index(job.id) + 1 if job.id in ids else None


@app.post("/api/capture")
def capture():
    """Kiosk: photo in, job number out."""
    photo = request.files.get("photo")
    if photo is None or not photo.filename:
        raise ValueError("no photo uploaded")

    style = (request.form.get("style") or "").strip()
    if style not in pipeline.KIOSK_STYLES:
        raise ValueError(
            f"style must be one of {', '.join(pipeline.KIOSK_STYLES)}"
        )

    # Whatever iOS sent us: keep the extension so PIL and OpenAI can sniff it.
    ext = os.path.splitext(photo.filename)[1].lower() or ".jpg"
    photo_name = f"photo{ext}"

    job = store.new(style=style, photo=photo_name)
    photo.save(job.path(photo_name))

    threading.Thread(
        target=_generate, args=(job, photo_name, style), daemon=True
    ).start()

    return jsonify(ok=True, id=job.id, state=job.state)


@app.get("/api/job/<job_id>")
def job_status(job_id):
    job = store.get(job_id)
    if job is None:
        return jsonify(ok=False, error=f"no job {job_id}"), 404
    summary = job.summary()
    if job.state == "queue":
        summary["position"] = _queue_position(job)
    return jsonify(summary)


@app.get("/api/job/<job_id>/file/<name>")
def job_file(job_id, name):
    job = store.get(job_id)
    if job is None:
        return jsonify(ok=False, error=f"no job {job_id}"), 404
    if name not in ("line_art.png", "preview.svg", "job.gcode") and not name.startswith("photo."):
        raise ValueError(f"not a job file: {name!r}")
    if not job.has(name):
        return jsonify(ok=False, error=f"{name} not ready"), 404
    return send_from_directory(job.dir, name)


@app.get("/api/queue")
def queue():
    return jsonify(
        queue=[j.summary() for j in store.list("queue")],
        working=[j.summary() for j in store.list("working")],
    )


# ----------------------------------------------------------------------
# Jobs, operator side
# ----------------------------------------------------------------------

@app.get("/api/console/jobs")
def console_jobs():
    return jsonify({state: [j.summary() for j in store.list(state)]
                    for state in ("queue", "working", "done", "failed")})


@app.get("/api/console/sheet")
def console_sheet():
    return jsonify(slot_grid())


@app.post("/api/console/sheet/new")
def console_new_sheet():
    """Fresh paper: every slot is free again."""
    number = store.new_sheet()
    return jsonify(ok=True, sheet=number)


@app.post("/api/console/slot/<slot>/go")
def console_slot_go(slot):
    """Jog to a slot. Whatever position the head is in when a job starts
    becomes that drawing's origin, which is what puts it in the right cell."""
    x, _, y = slot.partition(",")
    machine.jog(int(x), int(y))
    return jsonify(ok=True, sent=slot)


@app.post("/api/console/job/<job_id>/plot")
def console_plot(job_id):
    job = store.get(job_id)
    if job is None:
        return jsonify(ok=False, error=f"no job {job_id}"), 404
    if not job.has("job.gcode"):
        raise ValueError(f"job {job.id} has no G-code")

    body = request.get_json(silent=True) or {}
    slot = body.get("slot")

    # Do NOT rely on the firmware's busy check. Its upload handler sends
    # "409 busy" from the upload callback, but the completion callback sends
    # "200 stored" unconditionally -- so the client is told the file landed
    # when nothing was written, and the second job silently never draws.
    # Verified against the board: plotting during a job returns 200 and does
    # nothing. The server knows what it started, so it refuses here.
    if current["id"] and current["id"] != job.id:
        raise MachineError(
            f"#{int(current['id'])} is still drawing — stop it or mark it done first"
        )

    machine.plot(job.path("job.gcode"))

    stats = job.meta().get("stats") or {}
    current.update(id=job.id, slot=slot, started=time.monotonic(),
                   estimate=stats.get("estimated_seconds"))
    job.update(sheet=store.sheet(), slot=slot)
    return jsonify(ok=True, plotting=job.id, slot=slot)


@app.post("/api/console/job/<job_id>/done")
def console_done(job_id):
    """The operator is the completion signal -- the firmware never says so."""
    job = store.get(job_id)
    if job is None:
        return jsonify(ok=False, error=f"no job {job_id}"), 404

    body = request.get_json(silent=True) or {}
    data = job.meta()
    store.move(
        job, "done",
        sheet=body.get("sheet", data.get("sheet", store.sheet())),
        slot=body.get("slot", data.get("slot")),
    )
    if current["id"] == job.id:
        _clear_current()
    return jsonify(ok=True, id=job.id)


@app.post("/api/console/job/<job_id>/retrace")
def console_retrace(job_id):
    """Re-run steps 2 and 3 harder. No API call, a few seconds, free.

    This is the answer to a 400-stroke generation: fewer points per stroke and
    a higher noise floor, without paying for a new image.
    """
    job = store.get(job_id)
    if job is None:
        return jsonify(ok=False, error=f"no job {job_id}"), 404
    if not job.has("line_art.png"):
        raise ValueError(f"job {job.id} has no line art")

    body = request.get_json(silent=True) or {}
    stats = pipeline.trace(
        job.path("line_art.png"), job.path("job.gcode"), job.path("preview.svg"),
        bed=BED,
        simplify=float(body.get("simplify", 3.0)),
        min_points=int(body.get("min_points", 20)),
    )
    job.update(stats=stats, estimate=pipeline.estimate_text(stats))
    return jsonify(ok=True, id=job.id, stats=stats)


@app.post("/api/console/job/<job_id>/regenerate")
def console_regenerate(job_id):
    """New AI roll, in any of the five styles. Costs an API call."""
    job = store.get(job_id)
    if job is None:
        return jsonify(ok=False, error=f"no job {job_id}"), 404

    body = request.get_json(silent=True) or {}
    style = body.get("style") or job.meta().get("style")
    if style not in pipeline.ALL_STYLES:
        raise ValueError(f"style must be one of {', '.join(pipeline.ALL_STYLES)}")

    photo_name = job.meta().get("photo", "photo.jpg")
    if not job.has(photo_name):
        raise ValueError(f"job {job.id} has no photo to regenerate from")

    job.update(style=style, error=None)
    if job.state != "working":
        store.move(job, "working")
    threading.Thread(
        target=_generate, args=(job, photo_name, style), daemon=True
    ).start()
    return jsonify(ok=True, id=job.id, style=style)


@app.delete("/api/console/job/<job_id>")
def console_delete(job_id):
    job = store.get(job_id)
    if job is None:
        return jsonify(ok=False, error=f"no job {job_id}"), 404
    store.delete(job)
    return jsonify(ok=True, deleted=job_id)


if __name__ == "__main__":
    # HTTPS if certs/ has been filled in by certs.sh. It is not about secrecy
    # -- getUserMedia simply does not exist outside a secure context, so the
    # iPad cannot show a live camera preview over plain http. Without certs the
    # kiosk still works; it falls back to the native camera sheet.
    cert = os.path.join(HERE, "certs", "cert.pem")
    key = os.path.join(HERE, "certs", "key.pem")
    secure = os.path.isfile(cert) and os.path.isfile(key)
    scheme = "https" if secure else "http"

    print(f"plotter:  {PLOTTER_HOST}")
    print(f"gcode:    {GCODE_DIR}")
    print(f"jobs:     {JOBS_DIR}")
    print(f"console:  {scheme}://localhost:{PORT}/console")
    print(f"kiosk:    {scheme}://{socket.gethostname()}:{PORT}/")
    if not secure:
        print("          (no certs -- kiosk will use the native camera sheet;")
        print("           run ./certs.sh for the live viewfinder)")

    # threaded so the status poll does not queue behind a 30s upload
    app.run(host="0.0.0.0", port=PORT, threaded=True,
            ssl_context=(cert, key) if secure else None)
