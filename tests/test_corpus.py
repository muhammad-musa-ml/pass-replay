import json
import shutil
from pathlib import Path

from passreplay.check import check, diff
from passreplay.corpus import CORPUS, write_corpus
from passreplay.replay import replay

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"
GOLDEN_DIR = ROOT / "goldens"


def test_checked_in_recordings_are_what_the_seeds_produce(tmp_path):
    write_corpus(tmp_path)
    for profile, _ in CORPUS:
        name = profile + ".passrec"
        assert (tmp_path / name).read_bytes() == (CORPUS_DIR / name).read_bytes(), name


def test_the_checked_in_goldens_match_a_replay_of_the_checked_in_recordings():
    ok, lines = check(CORPUS_DIR, GOLDEN_DIR)
    assert ok, "\n".join(lines)


def test_what_each_recording_is_supposed_to_look_like():
    reports = {profile: replay(CORPUS_DIR / (profile + ".passrec")) for profile, _ in CORPUS}
    clean = reports["clean"]["totals"]
    assert (clean["frames_ok"], clean["frames_lost"], clean["frames_bad_fecf"]) == (2000, 0, 0)
    assert reports["clean"]["alerts"] == []
    fade = reports["fade"]["alerts"]
    assert len(fade) == 2
    assert fade[0]["start"] == 0 and fade[1]["end"] == 19
    assert reports["outage-short"]["totals"]["frames_lost"] == 100
    assert reports["outage-long"]["totals"]["channel_resyncs"] == 1
    assert len(reports["outage-long"]["alerts"]) == 1
    assert reports["noisy"]["totals"]["frames_dup"] > 0
    assert reports["noisy"]["totals"]["frames_late"] > 0
    assert reports["asm-in-payload"]["totals"]["frames_bad_fecf"] > 0
    assert reports["truncated"]["totals"]["frames_bad_fecf"] > 0


def test_check_reports_a_changed_number(tmp_path):
    goldens = tmp_path / "goldens"
    shutil.copytree(GOLDEN_DIR, goldens)
    path = goldens / "noisy.json"
    data = json.loads(path.read_text(encoding="ascii"))
    data["totals"]["frames_lost"] += 1
    path.write_text(json.dumps(data), encoding="ascii")
    ok, lines = check(CORPUS_DIR, goldens)
    assert not ok
    assert any("report.totals.frames_lost" in line for line in lines)


def test_check_reports_a_missing_golden_and_a_golden_with_no_recording(tmp_path):
    goldens = tmp_path / "goldens"
    shutil.copytree(GOLDEN_DIR, goldens)
    (goldens / "clean.json").unlink()
    shutil.copy(goldens / "noisy.json", goldens / "extra.json")
    ok, lines = check(CORPUS_DIR, goldens)
    assert not ok
    assert "clean: no golden report" in lines
    assert "extra: golden has no recording" in lines


def test_diff_walks_lists_and_nested_dicts():
    a = {"w": [{"x": 1}, {"x": 2}], "n": {"k": 1}}
    b = {"w": [{"x": 1}, {"x": 3}], "n": {"k": 1, "z": 0}}
    assert diff(a, b) == [
        "report.n.z: not in the golden",
        "report.w[1].x: 3, golden has 2",
    ]
