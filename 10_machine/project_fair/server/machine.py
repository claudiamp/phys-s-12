"""The one connection to the plotter.

Everything that talks to the ESP32 goes through here: one WebSocket for
commands, plain HTTP for the file. Nothing else in the project opens a socket
to the machine.

The firmware reports *endings*, not progress: it pushes "done", "stopped" or
"aborted" when a job finishes, and "homed" when homing completes. Nothing
arrives while a job is running -- for that, watch the pen.

Everything else here reports what was *sent*, not what the machine did.
"""

import threading
import time

import requests
import websocket

RECONNECT_DELAY = 2.0     # seconds between reconnect attempts
RECV_TIMEOUT = 3.0
UPLOAD_TIMEOUT = 30.0

# A WebSocket to a board that has rebooted is not detectably dead: writes go
# into a half-open TCP connection, succeed locally, and vanish. The server
# happily reports "connected" while every command falls on the floor -- and
# uploads keep working, because each one is a fresh HTTP connection. That
# combination is very confusing to debug from the outside.
#
# So: ping, and expect an answer. ESPAsyncWebServer replies to pings on its
# own, so silence means the board is gone.
PING_EVERY = 4.0
DEAD_AFTER = 12.0


class MachineOffline(Exception):
    """No WebSocket to the plotter right now."""


class MachineError(Exception):
    """The plotter answered, but not the way we expected."""


class Machine:
    """One plotter, addressed by hostname (plotter.local) or raw IP."""

    def __init__(self, host, limits=None, on_event=None):
        self.host = host
        # Called from the reader thread with each line the board sends.
        # The firmware announces how a job ended -- done / stopped / aborted --
        # and when homing finishes. Everything else it says is chatter.
        self.on_event = on_event
        # Measured travel in mm. The firmware bounds-checks a running job, but
        # nothing checks a jog -- without this, one fat-fingered number drives
        # the gantry into the frame at full speed.
        self.limits = limits
        self._ws = None
        self._lock = threading.Lock()
        self._connected = False
        self._last_error = None
        threading.Thread(target=self._keep_connected, daemon=True).start()

    # ------------------------------------------------------------------
    # connection
    # ------------------------------------------------------------------

    @property
    def ws_url(self):
        return f"ws://{self.host}/ws"

    @property
    def http_url(self):
        return f"http://{self.host}"

    def status(self):
        return {
            "host": self.host,
            "connected": self._connected,
            "error": self._last_error,
        }

    def _keep_connected(self):
        """Hold one WebSocket open, forever, reconnecting when it drops.

        Runs in a daemon thread. A fair is several hours long and the access
        point will blip at least once.
        """
        while True:
            ws = None
            try:
                ws = websocket.create_connection(self.ws_url, timeout=RECV_TIMEOUT)
                with self._lock:
                    self._ws = ws
                self._connected = True
                self._last_error = None

                last_heard = time.monotonic()
                last_ping = 0.0

                while True:
                    try:
                        opcode, data = ws.recv_data(control_frame=True)
                        last_heard = time.monotonic()   # pongs count too
                        if opcode == websocket.ABNF.OPCODE_TEXT and self.on_event:
                            try:
                                self.on_event(data.decode("utf-8", "replace").strip())
                            except Exception as exc:
                                # A bad handler must not take the connection
                                # down with it; the machine link matters more.
                                self._last_error = f"event handler: {exc}"
                    except websocket.WebSocketTimeoutException:
                        pass              # quiet is the normal case

                    now = time.monotonic()
                    if now - last_ping >= PING_EVERY:
                        ws.ping()
                        last_ping = now
                    if now - last_heard > DEAD_AFTER:
                        raise ConnectionError(
                            "no reply from the board; reconnecting"
                        )
            except Exception as exc:
                self._last_error = str(exc)
            finally:
                self._connected = False
                with self._lock:
                    self._ws = None
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass
            time.sleep(RECONNECT_DELAY)

    # ------------------------------------------------------------------
    # commands
    # ------------------------------------------------------------------

    def send(self, command):
        """Send one raw command string. The firmware never replies."""
        with self._lock:
            if self._ws is None:
                raise MachineOffline(f"not connected to {self.host}")
            self._ws.send(command)

    def home(self):
        """Seek both limit switches and zero the position.

        Slow -- roughly 7mm/s -- so a full-length seek is close to a minute.
        Home once per sheet, not once per drawing.
        """
        self.send("h")

    def pen_up(self):
        self.send("u")

    def pen_down(self):
        self.send("d")

    def test_circle(self):
        self.send("c")

    def stop(self):
        """Abort the running job.

        This one works even mid-plot: runFile() blocks loop(), but the
        WebSocket handler runs on a separate task and sets the flag that
        runFile() checks on every line.
        """
        self.send("s")

    def jog(self, x_mm, y_mm):
        """Move to an absolute position in mm.

        Whole millimetres only, and no negatives: the firmware's coordinate
        parser reads digits and nothing else.
        """
        x, y = int(x_mm), int(y_mm)
        if x < 0 or y < 0:
            raise ValueError("the firmware cannot parse negative coordinates")
        if self.limits:
            max_x, max_y = self.limits
            if x > max_x or y > max_y:
                raise ValueError(
                    f"{x},{y} is outside the machine ({int(max_x)}x{int(max_y)})"
                )
        self.send(f"{x},{y}")

    # ------------------------------------------------------------------
    # files
    # ------------------------------------------------------------------

    def upload(self, gcode_path):
        """Send a .gcode to the board's flash, replacing whatever was there."""
        with open(gcode_path, "rb") as f:
            reply = requests.post(
                f"{self.http_url}/upload",
                files={"file": f},
                timeout=UPLOAD_TIMEOUT,
            )

        if reply.status_code == 409:
            raise MachineError("the machine is busy drawing; stop it first")
        reply.raise_for_status()

        if reply.text.strip() != "stored":
            raise MachineError(f"unexpected reply to upload: {reply.text!r}")

    def plot(self, gcode_path):
        """Upload, then start drawing.

        The wait for "stored" is not optional. The upload opens /job.gcode with
        FILE_WRITE and replaces it, so starting a job on a half-written file
        plots a truncated drawing.
        """
        self.upload(gcode_path)
        self.send("g")
