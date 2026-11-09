from . import recording
from .pipeline import Pipeline

NS = 1_000_000_000


def replay(path, **config):
    """Feeds a recording through the pipeline using the recorded receive times, never the clock.
    Receive times are nanoseconds from the start of the pass, so a header that gives the pass
    length lets silence at either end of the pass show up."""
    header, chunks = recording.read(path)
    pipeline = Pipeline(frame_len=header["frame_len"], **config)
    for ts_ns, data in chunks:
        pipeline.feed(ts_ns, data)
    duration_s = header.get("duration_s")
    if duration_s:
        report = pipeline.finish(start_ns=0, end_ns=duration_s * NS - 1)
    else:
        report = pipeline.finish()
    report["recording"] = {
        "profile": header.get("profile"),
        "seed": header.get("seed"),
        "synthetic": header.get("synthetic"),
    }
    return report
