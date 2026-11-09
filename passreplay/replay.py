from . import recording
from .pipeline import Pipeline


def replay(path, **config):
    """Feeds a recording through the pipeline using the recorded receive times, never the clock."""
    header, chunks = recording.read(path)
    pipeline = Pipeline(frame_len=header["frame_len"], **config)
    for ts_ns, data in chunks:
        pipeline.feed(ts_ns, data)
    report = pipeline.finish()
    report["recording"] = {
        "profile": header["profile"],
        "seed": header["seed"],
        "synthetic": header["synthetic"],
    }
    return report
