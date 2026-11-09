"""Applies each mutant in tools/mutants.py to a temporary copy of the project and asks two
questions: do the unit tests notice, and does replaying the recorded passes notice?

    python tools/mutate.py              # writes results/mutation.md
"""
import concurrent.futures
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from mutants import MUTANTS  # noqa: E402

SEED_SETS = 5  # the committed corpus plus four more built from shifted seeds
COPIED = ("passreplay", "tests", "corpus", "goldens")


def python(args, cwd):
    return subprocess.run(
        [sys.executable] + args, cwd=cwd, capture_output=True, text=True, timeout=600,
        env=_env(),
    )


def _env():
    import os
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def copy_project(dst):
    for name in COPIED:
        shutil.copytree(ROOT / name, dst / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "conftest.py", dst / "conftest.py")


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def apply_mutant(work, m):
    path = work / m["file"]
    before = md5(path)
    text = path.read_text(encoding="utf-8", newline="")
    found = text.count(m["old"])
    if found != 1:
        raise SystemExit("%s: anchor occurs %d times in %s, need exactly 1" % (m["id"], found, m["file"]))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace(m["old"], m["new"]))
    changed = md5(path) != before
    if changed == (m["old"] == m["new"]):
        raise SystemExit("%s: the file did not change as expected" % m["id"])


def unit_tests(work):
    r = python(["-m", "pytest", "-q", "-p", "no:cacheprovider", "--ignore=tests/test_corpus.py"], work)
    out = r.stdout + r.stderr
    failed = sum(int(n) for n in re.findall(r"(\d+) (?:failed|error)", out))
    passed = sum(int(n) for n in re.findall(r"(\d+) passed", out))
    return {"killed": r.returncode != 0, "failed": failed, "passed": passed}


def replay_check(work, corpus, golden):
    r = python(["-m", "passreplay", "check", "--corpus", str(corpus), "--golden", str(golden)], work)
    differs = r.stdout.count(": DIFFERS")
    return {"killed": r.returncode != 0, "differs": differs, "crashed": "Traceback" in r.stderr}


def build_sets(base):
    sets = [(ROOT / "corpus", ROOT / "goldens")]
    for k in range(1, SEED_SETS):
        corpus = base / ("corpus%d" % k)
        golden = base / ("goldens%d" % k)
        r = python(["-m", "passreplay", "corpus", "--out", str(corpus), "--seed-offset", str(k)], ROOT)
        if r.returncode != 0:
            raise SystemExit("could not build corpus %d: %s" % (k, r.stderr))
        r = python(["-m", "passreplay", "check", "--update", "--corpus", str(corpus), "--golden", str(golden)], ROOT)
        if r.returncode != 0:
            raise SystemExit("could not build goldens %d: %s" % (k, r.stderr))
        sets.append((corpus, golden))
    return sets


def run_one(m, sets):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        work = Path(td)
        copy_project(work)
        if m is not None:
            apply_mutant(work, m)
        sets_here = [(work / "corpus", work / "goldens")] + sets[1:]
        return {
            "unit": unit_tests(work),
            "replay": [replay_check(work, c, g) for c, g in sets_here],
        }


def main():
    out_path = ROOT / "results" / "mutation.md"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as base_dir:
        sets = build_sets(Path(base_dir))
        baseline = run_one(None, sets)
        if baseline["unit"]["killed"] or any(r["killed"] for r in baseline["replay"]):
            raise SystemExit("the unmutated project does not pass its own checks: %r" % (baseline,))
        n_tests = baseline["unit"]["passed"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda m: run_one(m, sets), MUTANTS))

    rows = []
    unit_hits = replay_hits = both = only_unit = only_replay = neither = 0
    real = [(m, r) for m, r in zip(MUTANTS, results) if not m["id"].startswith("C")]
    for m, r in zip(MUTANTS, results):
        u = r["unit"]["killed"]
        p = r["replay"][0]
        sets_caught = sum(1 for x in r["replay"] if x["killed"])
        if u:
            n = r["unit"]["failed"]
            unit_text = "caught (%d test%s fail%s)" % (n, "" if n == 1 else "s", "s" if n == 1 else "")
        else:
            unit_text = "missed"
        if p["killed"]:
            replay_text = "caught (%s)" % ("crash" if p["crashed"] else "%d of 7 recordings differ" % p["differs"])
        else:
            replay_text = "missed"
        rows.append("| %s | %s | %s | %s | %s | %d of %d |" % (
            m["id"], m["file"].split("/")[-1], m["what"], unit_text, replay_text, sets_caught, SEED_SETS))
    for m, r in real:
        u = r["unit"]["killed"]
        p = r["replay"][0]["killed"]
        unit_hits += u
        replay_hits += p
        both += u and p
        only_unit += u and not p
        only_replay += p and not u
        neither += not u and not p
    total = len(real)
    lines = [
        "Generated by `python tools/mutate.py`. Each mutant is one change to the code, applied to a temporary copy.",
        "",
        "- Unit tests: pytest over `tests/` without `test_corpus.py` (%d tests, all passing on the unmutated code)." % n_tests,
        "- Replay: `passreplay check` over the 7 recordings in `corpus/` against `goldens/`.",
        "- Last column: the same replay check against %d corpora, the committed one and %d more built from seeds shifted by 1 to %d." % (
            SEED_SETS, SEED_SETS - 1, SEED_SETS - 1),
        "- C1 changes nothing and C2 breaks every call; they check the runner itself.",
        "",
        "| id | file | change | unit tests | replay | replay, corpora that caught it |",
        "|---|---|---|---|---|---|",
    ] + rows + [
        "",
        "Of %d mutants: unit tests caught %d, replay caught %d; both caught %d, only unit tests %d, only replay %d, neither %d." % (
            total, unit_hits, replay_hits, both, only_unit, only_replay, neither),
        "",
    ]
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
