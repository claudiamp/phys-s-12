"""The job store. The filesystem is the database.

One folder per job, and the parent folder is the state:

    jobs/
      working/   generating right now
      queue/     generated, waiting for the operator to plot it
      done/      plotted
      failed/    generation failed

Like a caricature artist, the visitor never sees the drawing before it is
made -- so a finished generation goes straight to the queue and the operator
is the only one who reviews it.

Changing state is os.rename of the folder -- atomic on one filesystem, so a job
can never end up half-moved. There is no index file to drift out of sync with
the files, and anything can be fixed by dragging folders in Finder: drag one
from done/ back to queue/ to plot it again.
"""

import json
import os
import re
import threading
import time

STATES = ("working", "queue", "done", "failed")

_NUMBERED = re.compile(r"^\d+$")


class Job:
    """One job folder. The number is also the ticket number the kiosk shows."""

    def __init__(self, root, state, number):
        self.root = root
        self.state = state
        self.number = number

    @property
    def id(self):
        return f"{self.number:04d}"

    @property
    def dir(self):
        return os.path.join(self.root, self.state, self.id)

    def path(self, name):
        return os.path.join(self.dir, name)

    def has(self, name):
        return os.path.isfile(self.path(name))

    # --- metadata -----------------------------------------------------

    def meta(self):
        try:
            with open(self.path("job.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def update(self, **fields):
        data = self.meta()
        data.update(fields)
        # Write beside the target and rename, so a crash mid-write cannot
        # leave a truncated job.json behind.
        tmp = self.path("job.json.tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path("job.json"))
        return data

    def summary(self):
        """What both UIs need to render a job without reading its files."""
        data = self.meta()
        return {
            "id": self.id,
            "state": self.state,
            "style": data.get("style"),
            "created": data.get("created"),
            "error": data.get("error"),
            "reason": data.get("reason"),
            "sheet": data.get("sheet"),
            "slot": data.get("slot"),
            "stats": data.get("stats"),
            "has_line_art": self.has("line_art.png"),
            "has_preview": self.has("preview.svg"),
            "has_gcode": self.has("job.gcode"),
        }


class JobStore:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self._lock = threading.Lock()
        for state in STATES:
            os.makedirs(os.path.join(self.root, state), exist_ok=True)
        self._migrate_ready()
        self._sweep_working()

    def _migrate_ready(self):
        """Jobs used to wait in ready/ for the visitor to keep or retake.

        The kiosk no longer shows anyone their drawing, so generation moves
        them straight to queue/. Anything left in ready/ from before that
        change belongs in the queue, not orphaned on disk.
        """
        legacy = os.path.join(self.root, "ready")
        if not os.path.isdir(legacy):
            return
        for name in sorted(os.listdir(legacy)):
            if _NUMBERED.match(name):
                os.rename(os.path.join(legacy, name),
                          os.path.join(self.root, "queue", name))
        try:
            os.rmdir(legacy)
        except OSError:
            pass          # something else in there; leave it alone

    def _sweep_working(self):
        """Anything caught mid-generation by a restart is junk.

        Its OpenAI call is gone and nothing is coming back for it, so move it
        out of the way rather than leaving it to sit in working/ forever.
        """
        for job in self.list("working"):
            job.update(error="server restarted during generation")
            self.move(job, "failed", reason="interrupted")

    # --- reading ------------------------------------------------------

    def list(self, state):
        folder = os.path.join(self.root, state)
        if not os.path.isdir(folder):
            return []
        names = sorted(n for n in os.listdir(folder) if _NUMBERED.match(n))
        return [Job(self.root, state, int(n)) for n in names]

    def all(self):
        return [job for state in STATES for job in self.list(state)]

    def get(self, job_id):
        try:
            number = int(job_id)
        except (TypeError, ValueError):
            return None
        for state in STATES:
            job = Job(self.root, state, number)
            if os.path.isdir(job.dir):
                return job
        return None

    # --- writing ------------------------------------------------------

    def new(self, **meta):
        """Create the next job folder in working/."""
        with self._lock:
            number = self._next_number()
            job = Job(self.root, "working", number)
            os.makedirs(job.dir, exist_ok=False)
        job.update(created=time.strftime("%Y-%m-%d %H:%M:%S"), **meta)
        return job

    def _next_number(self):
        """Highest folder number anywhere, plus one. No counter file to lose."""
        highest = 0
        for state in STATES:
            for job in self.list(state):
                highest = max(highest, job.number)
        return highest + 1

    def move(self, job, state, **fields):
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}")
        if fields:
            job.update(**fields)
        target = Job(self.root, state, job.number)
        os.makedirs(os.path.dirname(target.dir), exist_ok=True)
        os.rename(job.dir, target.dir)
        job.state = state
        return job

    def delete(self, job):
        for name in os.listdir(job.dir):
            os.remove(os.path.join(job.dir, name))
        os.rmdir(job.dir)

    # --- the sheet of paper currently on the bed ----------------------
    #
    # Which slots are taken is derived from the done jobs on this sheet, so
    # there is nothing to keep in sync. Only the sheet number is stored, and
    # only because "I put fresh paper down" is not something we can infer.

    @property
    def _sheet_file(self):
        return os.path.join(self.root, "sheet.json")

    def sheet(self):
        try:
            with open(self._sheet_file) as f:
                return int(json.load(f).get("sheet", 1))
        except (OSError, ValueError, TypeError):
            return 1

    def new_sheet(self):
        number = self.sheet() + 1
        with open(self._sheet_file, "w") as f:
            json.dump({"sheet": number}, f)
        return number

    def slots_used(self, sheet=None):
        """{slot: job id} for everything already drawn on this sheet."""
        sheet = self.sheet() if sheet is None else sheet
        used = {}
        for job in self.list("done"):
            data = job.meta()
            if data.get("sheet") == sheet and data.get("slot"):
                used[data["slot"]] = job.id
        return used
