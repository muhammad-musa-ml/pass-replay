import json
from pathlib import Path

from .replay import replay

MAX_LINES = 8


def diff(expected, got, path="report"):
    """Lists the places where two reports differ."""
    if isinstance(expected, dict) and isinstance(got, dict):
        lines = []
        for key in sorted(set(expected) | set(got)):
            if key not in got:
                lines.append("%s.%s: missing" % (path, key))
            elif key not in expected:
                lines.append("%s.%s: not in the golden" % (path, key))
            else:
                lines += diff(expected[key], got[key], "%s.%s" % (path, key))
        return lines
    if isinstance(expected, list) and isinstance(got, list):
        lines = []
        if len(expected) != len(got):
            lines.append("%s: %d entries, golden has %d" % (path, len(got), len(expected)))
        for i, (e, g) in enumerate(zip(expected, got)):
            lines += diff(e, g, "%s[%d]" % (path, i))
        return lines
    if expected != got:
        return ["%s: %r, golden has %r" % (path, got, expected)]
    return []


def write_golden(path, report):
    with open(path, "w", encoding="ascii", newline="\n") as f:
        json.dump(report, f, indent=1, sort_keys=True)
        f.write("\n")


def check(corpus_dir, golden_dir, update=False):
    """Replays every recording and compares it with its golden report.
    Returns (ok, lines)."""
    corpus_dir = Path(corpus_dir)
    golden_dir = Path(golden_dir)
    recordings = sorted(corpus_dir.glob("*.passrec"))
    lines = []
    ok = True
    if not recordings:
        return False, ["no recordings in %s" % corpus_dir]
    if update:
        golden_dir.mkdir(parents=True, exist_ok=True)
    names = set()
    for rec in recordings:
        names.add(rec.stem)
        report = replay(rec)
        golden_path = golden_dir / (rec.stem + ".json")
        if update:
            write_golden(golden_path, report)
            lines.append("%s: golden written" % rec.stem)
            continue
        if not golden_path.exists():
            ok = False
            lines.append("%s: no golden report" % rec.stem)
            continue
        with open(golden_path, encoding="ascii") as f:
            golden = json.load(f)
        found = diff(golden, report)
        if found:
            ok = False
            lines.append("%s: DIFFERS in %d places" % (rec.stem, len(found)))
            lines += ["    " + line for line in found[:MAX_LINES]]
            if len(found) > MAX_LINES:
                lines.append("    ... %d more" % (len(found) - MAX_LINES))
        else:
            lines.append("%s: same" % rec.stem)
    if not update:
        for golden in sorted(golden_dir.glob("*.json")):
            if golden.stem not in names:
                ok = False
                lines.append("%s: golden has no recording" % golden.stem)
    return ok, lines
