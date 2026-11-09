import hashlib

from .frames import ASM, FECF_LEN, HEADER_LEN, check_fecf, parse_header

COUNTER_MOD = 256
HALF = COUNTER_MOD // 2


class Pipeline:
    """Finds frames in a byte stream and tracks the virtual channel counters."""

    def __init__(self, frame_len=128):
        self.frame_len = frame_len
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
        self.digest = hashlib.sha256()

    def feed(self, ts_ns, chunk):
        self.totals["bytes_in"] += len(chunk)
        self.totals["chunks_in"] += 1
        self.buf += chunk
        self._drain(ts_ns)

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
                del buf[:asm_len]

    def _accept(self, frame, ts_ns):
        h = parse_header(frame)
        ch = self.channels.get(h.vcid)
        if ch is None:
            ch = self.channels[h.vcid] = {"last": None, "ok": 0, "lost": 0, "dup": 0, "late": 0}
        if ch["last"] is None:
            delta = 1
        else:
            delta = (h.vc_count - ch["last"]) % COUNTER_MOD
        if delta == 0:
            ch["dup"] += 1
            self.totals["frames_dup"] += 1
            return
        if delta > HALF:
            # With an 8-bit counter a jump of more than half the range looks the same
            # as an old frame arriving late, so it is counted as late.
            ch["late"] += 1
            self.totals["frames_late"] += 1
            return
        lost = delta - 1
        ch["last"] = h.vc_count
        ch["ok"] += 1
        ch["lost"] += lost
        self.totals["frames_ok"] += 1
        self.totals["frames_lost"] += lost
        self.digest.update(bytes([h.vcid]) + frame[HEADER_LEN:-FECF_LEN])

    def finish(self):
        return {
            "totals": dict(self.totals, trailing_bytes=len(self.buf)),
            "channels": {
                str(vcid): {k: v for k, v in ch.items() if k != "last"}
                for vcid, ch in sorted(self.channels.items())
            },
            "data_sha256": self.digest.hexdigest(),
        }
