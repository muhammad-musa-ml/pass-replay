from passreplay.frames import ASM, build_frame
from passreplay.pipeline import Pipeline

FRAME_LEN = 128
SECOND = 1_000_000_000


class Link:
    """Feeds one frame per call on channel 0, with a controllable counter step."""

    def __init__(self):
        self.pipeline = Pipeline(FRAME_LEN)
        self.count = 0

    def window(self, w, step=1, frames=10):
        for k in range(frames):
            self.count = (self.count + step) % 256
            frame = ASM + build_frame(1, 0, 0, self.count, bytes(FRAME_LEN - 8), FRAME_LEN)
            self.pipeline.feed(w * SECOND + k * 1_000_000, frame)

    def report(self):
        return self.pipeline.finish()


def test_frames_are_counted_in_the_window_of_their_chunk():
    link = Link()
    link.window(0)
    link.window(1, frames=4)
    windows = link.report()["windows"]
    assert [w["index"] for w in windows] == [0, 1]
    assert [w["ok"] for w in windows] == [10, 4]


def test_loss_ratio_arithmetic_worked_by_hand():
    link = Link()
    link.window(0)
    link.window(1, step=2)  # each of 10 frames skips one: 10 ok, 10 lost
    w = link.report()["windows"][1]
    assert (w["ok"], w["lost"], w["loss_ppm"]) == (10, 10, 500_000)


def test_loss_ratio_rounds_down_to_whole_ppm():
    link = Link()
    link.window(0, frames=10)
    link.count += 2  # two frames missing before the next one
    link.window(1, frames=1)
    w = link.report()["windows"][1]
    # 1 ok and 2 lost in the window: 2 / 3 -> 666666 ppm
    assert (w["ok"], w["lost"], w["loss_ppm"]) == (1, 2, 666_666)


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


def test_an_empty_stream_has_no_windows():
    report = Pipeline(FRAME_LEN).finish()
    assert report["windows"] == []
    assert report["alerts"] == []
