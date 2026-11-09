import hashlib

import pytest

from passreplay.frames import ASM
from passreplay.pipeline import Pipeline
from passreplay.rng import Rng
from passreplay.simulate import PROFILES, simulate


def run_pipeline(header, chunks):
    p = Pipeline(header["frame_len"])
    for ts, data in chunks:
        p.feed(ts, data)
    return p.finish()


def digest(chunks):
    h = hashlib.sha256()
    for ts, data in chunks:
        h.update(ts.to_bytes(8, "little") + data)
    return h.hexdigest()


def test_rng_first_output_for_seed_zero():
    assert Rng(0).u64() == 0xE220A8397B1DCDAF


def test_same_seed_gives_the_same_pass():
    a = simulate(5, "noisy", duration_s=4)
    b = simulate(5, "noisy", duration_s=4)
    assert a == b


def test_different_seed_gives_a_different_pass():
    a = simulate(5, "noisy", duration_s=4)
    b = simulate(6, "noisy", duration_s=4)
    assert digest(a[1]) != digest(b[1])


def test_timestamps_never_go_backwards():
    for name in PROFILES:
        _, chunks = simulate(3, name, duration_s=6)
        stamps = [ts for ts, _ in chunks]
        assert stamps == sorted(stamps), name


def test_clean_pass_decodes_every_frame_with_no_loss():
    header, chunks = simulate(1, "clean", duration_s=5)
    report = run_pipeline(header, chunks)
    assert report["totals"]["frames_ok"] == 5 * header["fps"]
    assert report["totals"]["frames_lost"] == 0
    assert report["totals"]["frames_bad_fecf"] == 0
    assert report["totals"]["trailing_bytes"] == 0


def test_chunks_cut_through_frames_and_through_markers():
    _, chunks = simulate(1, "clean", duration_s=5)
    assert any(not c.startswith(ASM) for _, c in chunks)
    assert any(len(c) < len(ASM) for _, c in chunks)


def test_a_one_second_outage_shows_up_as_100_lost_frames():
    header, chunks = simulate(2, "outage-short", duration_s=12)
    report = run_pipeline(header, chunks)
    sent = 12 * header["fps"]
    got = report["totals"]["frames_ok"]
    assert sent - got == 100
    assert report["totals"]["frames_lost"] == 100


def test_unknown_profile_is_refused():
    with pytest.raises(KeyError):
        simulate(1, "no-such-profile")
