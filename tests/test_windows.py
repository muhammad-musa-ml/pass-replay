import pytest

from passreplay.frames import ASM, build_frame
from passreplay.pipeline import Pipeline

FRAME_LEN = 128
SECOND = 1_000_000_000
MS = 1_000_000


class Link:
    """Feeds one frame per chunk on channel 0, with a controllable counter step."""

    def __init__(self):
        self.pipeline = Pipeline(FRAME_LEN)
        self.count = 0

    def window(self, w, step=1, frames=10, offset_ms=0):
        for k in range(frames):
            self.count = (self.count + step) % 256
            frame = ASM + build_frame(1, 0, 0, self.count, bytes(FRAME_LEN - 8), FRAME_LEN)
            self.pipeline.feed(w * SECOND + (offset_ms + k) * MS, frame)

    def report(self, **kwargs):
        return self.pipeline.finish(**kwargs)


def test_frames_are_counted_in_the_window_of_their_chunk():
    link = Link()
    link.window(0)
    link.window(1, frames=4)
    windows = link.report()["windows"]
    assert [w["index"] for w in windows] == [0, 1]
    assert [w["ok"] for w in windows] == [10, 4]


def test_loss_inside_one_window_is_charged_to_that_window():
    link = Link()
    link.window(0)
    link.window(1, step=2)  # each of 10 frames skips one count
    windows = link.report()["windows"]
    # the first skip happened between the last frame of window 0 and the first of window 1
    assert (windows[0]["ok"], windows[0]["lost"]) == (10, 1)
    assert (windows[1]["ok"], windows[1]["lost"], windows[1]["loss_ppm"]) == (10, 9, 473_684)


def test_loss_ratio_rounds_down_to_whole_ppm():
    link = Link()
    link.window(0, frames=10)
    link.count += 2  # two frames missing before the next one
    link.window(0, frames=1, offset_ms=10)
    w = link.report()["windows"][0]
    # 11 ok and 2 lost in the window: 2 / 13 = 153846.15 ppm
    assert (w["ok"], w["lost"], w["loss_ppm"]) == (11, 2, 153_846)


def test_a_window_at_exactly_the_threshold_is_degraded():
    link = Link()
    for w in (0, 1, 2):
        link.window(w, frames=1)
        link.count += 1
        link.window(w, frames=3, offset_ms=1)  # 4 ok and 1 lost: exactly 200000 ppm
    report = link.report()
    assert [x["loss_ppm"] for x in report["windows"]] == [200_000] * 3
    assert report["alerts"] == [{"start": 0, "end": 2, "peak_loss_ppm": 200_000}]


def test_a_gap_is_spread_over_the_time_it_covers():
    link = Link()
    link.window(4, frames=3)
    link.count += 100
    link.window(7, frames=2)
    windows = link.report()["windows"]
    assert [w["index"] for w in windows] == [4, 5, 6, 7]
    assert [w["lost"] for w in windows] == [33, 33, 33, 1]
    assert sum(w["lost"] for w in windows) == 100


def test_an_outage_is_not_charged_again_to_the_window_where_the_link_returns():
    link = Link()
    link.window(0, frames=50)
    link.count += 100
    link.window(3, frames=50)
    windows = link.report()["windows"]
    assert windows[1]["lost"] > 0 and windows[2]["lost"] > 0
    # only the rounding remainder (at most one frame per window crossed) lands where the link returned
    assert windows[3]["lost"] <= 3 and windows[3]["loss_ppm"] < 100_000


def test_a_window_with_no_frames_is_the_worst_case():
    link = Link()
    link.window(0)
    link.window(3)
    windows = link.report()["windows"]
    assert [w["index"] for w in windows] == [0, 1, 2, 3]
    assert [w["silent"] for w in windows] == [False, True, True, False]
    assert windows[1]["loss_ppm"] == 1_000_000


def test_a_window_with_only_a_bad_frame_is_the_worst_case():
    link = Link()
    link.window(0)
    bad = bytearray(ASM + build_frame(1, 0, 0, 77, bytes(FRAME_LEN - 8), FRAME_LEN))
    bad[30] ^= 1
    link.pipeline.feed(1 * SECOND, bytes(bad))
    w = link.report()["windows"][1]
    assert (w["bad"], w["silent"], w["loss_ppm"]) == (1, False, 1_000_000)


def test_two_degraded_windows_do_not_alert():
    link = Link()
    link.window(0)
    link.window(1, step=2)
    link.window(2, step=2)
    link.window(3)
    assert link.report()["alerts"] == []


def test_three_degraded_windows_in_a_row_alert_once():
    link = Link()
    link.window(0)
    for w in (1, 2, 3):
        link.window(w, step=2)
    link.window(4)
    assert link.report()["alerts"] == [{"start": 1, "end": 3, "peak_loss_ppm": 500_000}]


def test_a_good_window_splits_two_runs():
    link = Link()
    link.window(0)
    for w in (1, 2, 3):
        link.window(w, step=2)
    link.window(4)
    for w in (5, 6, 7):
        link.window(w, step=2)
    alerts = link.report()["alerts"]
    assert [(a["start"], a["end"]) for a in alerts] == [(1, 3), (5, 7)]


def test_a_run_that_lasts_to_the_end_of_the_pass_alerts():
    link = Link()
    link.window(0)
    for w in (1, 2, 3):
        link.window(w, step=2)
    assert [(a["start"], a["end"]) for a in link.report()["alerts"]] == [(1, 3)]


def test_silent_windows_count_toward_an_alert():
    link = Link()
    link.window(0)
    link.window(4)
    alerts = link.report()["alerts"]
    assert alerts == [{"start": 1, "end": 3, "peak_loss_ppm": 1_000_000}]


def test_silence_before_and_after_the_frames_shows_when_the_pass_length_is_given():
    link = Link()
    link.window(4, frames=50)
    report = link.report(start_ns=0, end_ns=10 * SECOND - 1)
    assert [w["silent"] for w in report["windows"]] == [True] * 4 + [False] + [True] * 5
    assert [(a["start"], a["end"]) for a in report["alerts"]] == [(0, 3), (5, 9)]


def test_without_the_pass_length_only_the_span_of_the_chunks_is_covered():
    link = Link()
    link.window(4, frames=50)
    assert [w["index"] for w in link.report()["windows"]] == [4]


def test_an_empty_stream_has_no_windows():
    report = Pipeline(FRAME_LEN).finish()
    assert report["windows"] == []
    assert report["alerts"] == []


def test_an_empty_stream_with_a_known_pass_length_is_all_silence():
    report = Pipeline(FRAME_LEN).finish(start_ns=0, end_ns=3 * SECOND - 1)
    assert [w["silent"] for w in report["windows"]] == [True] * 3
    assert len(report["alerts"]) == 1


def test_chunk_times_that_go_backwards_are_refused():
    p = Pipeline(FRAME_LEN)
    p.feed(10, b"")
    with pytest.raises(ValueError):
        p.feed(5, b"")


def test_an_alert_needs_at_least_one_window():
    with pytest.raises(ValueError):
        Pipeline(FRAME_LEN, degraded_windows=0)
