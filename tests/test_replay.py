import pytest

from passreplay import recording
from passreplay.cli import main
from passreplay.pipeline import Pipeline
from passreplay.replay import replay
from passreplay.simulate import simulate


def test_recording_round_trip(tmp_path):
    header, chunks = simulate(4, "noisy", duration_s=3)
    path = tmp_path / "a.passrec"
    recording.write(path, header, chunks)
    assert recording.read(path) == (header, chunks)


def test_file_that_is_not_a_recording_is_refused(tmp_path):
    path = tmp_path / "bad.passrec"
    path.write_bytes(b"hello\n")
    with pytest.raises(ValueError):
        recording.read(path)


def test_cut_off_recording_is_refused(tmp_path):
    header, chunks = simulate(4, "clean", duration_s=2)
    path = tmp_path / "a.passrec"
    recording.write(path, header, chunks)
    path.write_bytes(path.read_bytes()[:-5])
    with pytest.raises(ValueError):
        recording.read(path)


def test_replay_matches_feeding_the_pipeline_directly(tmp_path):
    header, chunks = simulate(9, "noisy", duration_s=4)
    path = tmp_path / "a.passrec"
    recording.write(path, header, chunks)
    direct = Pipeline(header["frame_len"])
    for ts, data in chunks:
        direct.feed(ts, data)
    expected = direct.finish()
    got = replay(path)
    for key in expected:
        assert got[key] == expected[key]
    assert got["recording"]["seed"] == 9


def test_replay_twice_gives_the_same_report(tmp_path):
    header, chunks = simulate(9, "noisy", duration_s=4)
    path = tmp_path / "a.passrec"
    recording.write(path, header, chunks)
    assert replay(path) == replay(path)


def test_cli_simulate_then_replay(tmp_path, capsys):
    path = str(tmp_path / "a.passrec")
    assert main(["simulate", "--seed", "1", "--profile", "clean", "--duration", "2", "--out", path]) == 0
    assert main(["replay", path]) == 0
    out = capsys.readouterr().out
    assert "frames ok 200, lost 0" in out
