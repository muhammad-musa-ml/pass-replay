import json
import struct

MAGIC = b"PASSREC1\n"
_RECORD = struct.Struct("<QI")  # receive time in ns, byte count


def write(path, header, chunks):
    with open(path, "wb") as f:
        f.write(MAGIC)
        f.write(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n")
        for ts_ns, data in chunks:
            f.write(_RECORD.pack(ts_ns, len(data)))
            f.write(data)


def read(path):
    with open(path, "rb") as f:
        if f.readline() != MAGIC:
            raise ValueError("%s is not a pass recording" % path)
        header = json.loads(f.readline())
        chunks = []
        while True:
            raw = f.read(_RECORD.size)
            if not raw:
                break
            if len(raw) < _RECORD.size:
                raise ValueError("%s ends inside a record header" % path)
            ts_ns, size = _RECORD.unpack(raw)
            data = f.read(size)
            if len(data) != size:
                raise ValueError("%s ends inside a record" % path)
            chunks.append((ts_ns, data))
    return header, chunks
