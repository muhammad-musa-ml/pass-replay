import hashlib

from .frames import ASM, FECF_LEN, HEADER_LEN, check_fecf, parse_header

COUNTER_MOD = 256
HALF = COUNTER_MOD // 2
PPM = 1_000_000


class Pipeline:
    """Finds frames in a byte stream, tracks the virtual channel counters and
    turns the counts into one-second link-quality windows and degraded-link alerts."""

    def __init__(self, frame_len=128, window_ns=1_000_000_000, degraded_ppm=200_000, degraded_windows=3):
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
            "sync_discarded_bytes": 0,
        }
        self.channels = {}
        self.windows = {}
        self.first_ts = None
        self.last_ts = None
        self.digest = hashlib.sha256()

    def feed(self, ts_ns, chunk):
        if self.first_ts is None:
            self.first_ts = ts_ns
        self.last_ts = ts_ns
        self.totals["bytes_in"] += len(chunk)
        self.totals["chunks_in"] += 1
        self.buf += chunk
        self._drain(ts_ns)

    def _window(self, ts_ns):
        index = ts_ns // self.window_ns
        win = self.windows.get(index)
        if win is None:
            win = self.windows[index] = {"ok": 0, "bad": 0, "lost": 0, "dup": 0, "late": 0}
        return win

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

    def _accept(self, frame, ts_ns):
        h = parse_header(frame)
        win = self._window(ts_ns)
        ch = self.channels.get(h.vcid)
        if ch is None:
            ch = self.channels[h.vcid] = {"last": None, "ok": 0, "lost": 0, "dup": 0, "late": 0}
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
            # as an old frame arriving late, so it is counted as late.
            ch["late"] += 1
            win["late"] += 1
            self.totals["frames_late"] += 1
            return
        lost = delta - 1
        ch["last"] = h.vc_count
        ch["ok"] += 1
        ch["lost"] += lost
        win["ok"] += 1
        win["lost"] += lost
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

    def finish(self):
        windows = []
        if self.first_ts is not None:
            first = self.first_ts // self.window_ns
            last = self.last_ts // self.window_ns
            empty = {"ok": 0, "bad": 0, "lost": 0, "dup": 0, "late": 0}
            for index in range(first, last + 1):
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
                str(vcid): {k: v for k, v in ch.items() if k != "last"}
                for vcid, ch in sorted(self.channels.items())
            },
            "windows": windows,
            "alerts": self._alerts(windows),
            "data_sha256": self.digest.hexdigest(),
        }
