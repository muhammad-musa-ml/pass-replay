import hashlib

from .frames import ASM, FECF_LEN, HEADER_LEN, check_fecf, parse_header

COUNTER_MOD = 256
HALF = COUNTER_MOD // 2
REORDER_WINDOW = 16
RESYNC_AFTER = 3
PPM = 1_000_000


class Pipeline:
    """Finds frames in a byte stream, tracks the virtual channel counters and
    turns the counts into one-second link-quality windows and degraded-link alerts."""

    def __init__(self, frame_len=128, window_ns=1_000_000_000, degraded_ppm=200_000, degraded_windows=3):
        if degraded_windows < 1:
            raise ValueError("degraded_windows must be at least 1")
        self.frame_len = frame_len
        self.window_ns = window_ns
        self.degraded_ppm = degraded_ppm
        self.degraded_windows = degraded_windows
        self.buf = bytearray()
        self.totals = {
            "bytes_in": 0,
            "chunks_in": 0,
            "frames_ok": 0,
            "frames_bad_fecf": 0,
            "frames_lost": 0,
            "frames_dup": 0,
            "frames_late": 0,
            "channel_resyncs": 0,
            "sync_discarded_bytes": 0,
        }
        self.channels = {}
        self.windows = {}
        self.first_ts = None
        self.last_ts = None
        self.digest = hashlib.sha256()

    def feed(self, ts_ns, chunk):
        if self.last_ts is not None and ts_ns < self.last_ts:
            raise ValueError("chunk times must not go backwards")
        if self.first_ts is None:
            self.first_ts = ts_ns
        self.last_ts = ts_ns
        self.totals["bytes_in"] += len(chunk)
        self.totals["chunks_in"] += 1
        self.buf += chunk
        self._drain(ts_ns)

    def _window_at(self, index):
        win = self.windows.get(index)
        if win is None:
            win = self.windows[index] = {"ok": 0, "bad": 0, "lost": 0, "dup": 0, "late": 0}
        return win

    def _window(self, ts_ns):
        return self._window_at(ts_ns // self.window_ns)

    def _drain(self, ts_ns):
        buf = self.buf
        asm_len = len(ASM)
        need = asm_len + self.frame_len
        while True:
            at = buf.find(ASM)
            if at < 0:
                # a marker may start in the last bytes and finish in the next chunk
                drop = max(0, len(buf) - (asm_len - 1))
                self.totals["sync_discarded_bytes"] += drop
                del buf[:drop]
                return
            if at > 0:
                self.totals["sync_discarded_bytes"] += at
                del buf[:at]
            if len(buf) < need:
                return
            frame = bytes(buf[asm_len:need])
            if check_fecf(frame):
                del buf[:need]
                self._accept(frame, ts_ns)
            else:
                # Skip the marker only. If the marker was real, the next one is found
                # inside what is left; if it was a false match in a payload, nothing is lost.
                self.totals["frames_bad_fecf"] += 1
                self._window(ts_ns)["bad"] += 1
                del buf[:asm_len]

    def _late(self, ch, win):
        ch["late"] += 1
        win["late"] += 1
        self.totals["frames_late"] += 1

    def _spread_loss(self, lost, t0, t1):
        """Adds lost frames to the windows between the last accepted frame on the channel and
        this one, in proportion to the time in each, so the window where the link came back
        gets only its share of an outage, plus the rounding remainder."""
        w = self.window_ns
        first, last = t0 // w, t1 // w
        span = t1 - t0
        given = 0
        if span > 0:
            for index in range(first, last):
                part = min(t1, (index + 1) * w) - max(t0, index * w)
                share = lost * part // span
                self._window_at(index)["lost"] += share
                given += share
        self._window_at(last)["lost"] += lost - given

    def _accept(self, frame, ts_ns):
        h = parse_header(frame)
        win = self._window(ts_ns)
        ch = self.channels.get(h.vcid)
        if ch is None:
            ch = self.channels[h.vcid] = {
                "last": None, "last_ts": None, "pending": None, "streak": 0,
                "ok": 0, "lost": 0, "dup": 0, "late": 0, "resyncs": 0,
            }
        if ch["last"] is None:
            delta = 1
        else:
            delta = (h.vc_count - ch["last"]) % COUNTER_MOD
        if delta == 0:
            ch["dup"] += 1
            win["dup"] += 1
            self.totals["frames_dup"] += 1
            return
        if delta > HALF:
            # With an 8-bit counter a jump of more than half the range looks the same
            # as an old frame arriving late. A frame just behind the last one is late.
            if COUNTER_MOD - delta <= REORDER_WINDOW:
                self._late(ch, win)
                return
            # Further behind: after an outage of more than half the counter range the channel
            # comes back with consecutive counts, so a run of them restarts the counter here
            # and the size of the gap stays unknown. Anything else is a late frame.
            if ch["pending"] is not None and h.vc_count == (ch["pending"] + 1) % COUNTER_MOD:
                ch["streak"] += 1
            else:
                ch["streak"] = 1
            ch["pending"] = h.vc_count
            if ch["streak"] < RESYNC_AFTER:
                self._late(ch, win)
                return
            ch["resyncs"] += 1
            self.totals["channel_resyncs"] += 1
            delta = 1
        ch["pending"] = None
        lost = delta - 1
        if lost:
            self._spread_loss(lost, ch["last_ts"], ts_ns)
        ch["last"] = h.vc_count
        ch["last_ts"] = ts_ns
        ch["ok"] += 1
        ch["lost"] += lost
        win["ok"] += 1
        self.totals["frames_ok"] += 1
        self.totals["frames_lost"] += lost
        self.digest.update(bytes([h.vcid]) + frame[HEADER_LEN:-FECF_LEN])

    def _summarize(self, index, win):
        seen = win["ok"] + win["bad"] + win["dup"] + win["late"]
        expected = win["ok"] + win["lost"]
        silent = seen == 0
        # A window with nothing usable is the worst case, not a division by zero.
        if silent or expected == 0:
            loss_ppm = PPM
        else:
            loss_ppm = win["lost"] * PPM // expected
        return dict(win, index=index, silent=silent, loss_ppm=loss_ppm)

    def _alerts(self, windows):
        alerts = []
        run = []
        for win in windows + [None]:
            if win is not None and win["loss_ppm"] >= self.degraded_ppm:
                run.append(win)
                continue
            if len(run) >= self.degraded_windows:
                alerts.append({
                    "start": run[0]["index"],
                    "end": run[-1]["index"],
                    "peak_loss_ppm": max(w["loss_ppm"] for w in run),
                })
            run = []
        return alerts

    def finish(self, start_ns=None, end_ns=None):
        """start_ns and end_ns are the first and last instant of the pass, when known, so that
        silence before the first frame or after the last one shows up as silent windows."""
        lows = [t for t in (self.first_ts, start_ns) if t is not None]
        highs = [t for t in (self.last_ts, end_ns) if t is not None]
        windows = []
        if lows and highs:
            empty = {"ok": 0, "bad": 0, "lost": 0, "dup": 0, "late": 0}
            for index in range(min(lows) // self.window_ns, max(highs) // self.window_ns + 1):
                windows.append(self._summarize(index, self.windows.get(index, empty)))
        return {
            "config": {
                "frame_len": self.frame_len,
                "window_ns": self.window_ns,
                "degraded_ppm": self.degraded_ppm,
                "degraded_windows": self.degraded_windows,
            },
            "totals": dict(self.totals, trailing_bytes=len(self.buf)),
            "channels": {
                str(vcid): {k: ch[k] for k in ("ok", "lost", "dup", "late", "resyncs")}
                for vcid, ch in sorted(self.channels.items())
            },
            "windows": windows,
            "alerts": self._alerts(windows),
            "data_sha256": self.digest.hexdigest(),
        }
