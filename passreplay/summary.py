from pathlib import Path

from .replay import replay


def corpus_table(corpus_dir):
    """A markdown table with one row per recording, built from replay reports."""
    rows = [
        "| recording | seed | frames ok | lost | bad check | duplicate | late | channel resyncs | degraded-link alerts |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for rec in sorted(Path(corpus_dir).glob("*.passrec")):
        report = replay(rec)
        t = report["totals"]
        rows.append("| %s | %d | %d | %d | %d | %d | %d | %d | %d |" % (
            report["recording"]["profile"], report["recording"]["seed"], t["frames_ok"],
            t["frames_lost"], t["frames_bad_fecf"], t["frames_dup"], t["frames_late"],
            t["channel_resyncs"], len(report["alerts"])))
    return "\n".join(rows) + "\n"
