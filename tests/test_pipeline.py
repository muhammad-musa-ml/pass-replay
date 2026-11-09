from passreplay.frames import ASM, build_frame
from passreplay.pipeline import Pipeline

FRAME_LEN = 128
BODY = FRAME_LEN - 8


def wire(vcid, vc_count, mc_count=0, fill=0x55):
    return ASM + build_frame(7, vcid, mc_count, vc_count, bytes([fill]) * BODY, FRAME_LEN)


def run(chunks):
    p = Pipeline(FRAME_LEN)
    for i, chunk in enumerate(chunks):
        p.feed(i * 10_000_000, chunk)
    return p.finish()


def test_clean_stream_has_no_loss():
    report = run([wire(0, n) for n in range(10)])
    assert report["totals"]["frames_ok"] == 10
    assert report["totals"]["frames_lost"] == 0
    assert report["channels"]["0"]["ok"] == 10


def test_missing_frames_are_counted_as_lost():
    report = run([wire(0, 0), wire(0, 1), wire(0, 5)])
    assert report["totals"]["frames_lost"] == 3
    assert report["channels"]["0"]["lost"] == 3


def test_counter_wraps_at_256_without_loss():
    report = run([wire(0, n % 256) for n in range(250, 262)])
    assert report["totals"]["frames_ok"] == 12
    assert report["totals"]["frames_lost"] == 0


def test_loss_across_the_wrap():
    report = run([wire(0, 254), wire(0, 2)])
    assert report["totals"]["frames_lost"] == 3


def test_channels_count_separately():
    report = run([wire(0, 0), wire(1, 40), wire(0, 1), wire(1, 41)])
    assert report["totals"]["frames_lost"] == 0
    assert report["channels"]["1"]["ok"] == 2


def test_duplicate_is_not_loss_and_not_delivered_twice():
    once = run([wire(0, 0), wire(0, 1)])
    twice = run([wire(0, 0), wire(0, 1), wire(0, 1)])
    assert twice["totals"]["frames_dup"] == 1
    assert twice["totals"]["frames_lost"] == 0
    assert twice["data_sha256"] == once["data_sha256"]


def test_old_frame_arriving_late_is_counted_late():
    report = run([wire(0, 10), wire(0, 11), wire(0, 9), wire(0, 12)])
    assert report["totals"]["frames_late"] == 1
    assert report["totals"]["frames_lost"] == 0


def test_frames_that_arrive_out_of_order_do_not_trigger_a_resync():
    report = run([wire(0, n) for n in (0, 4, 1, 2, 3, 5)])
    assert report["channels"]["0"]["resyncs"] == 0
    assert report["channels"]["0"]["late"] == 3
    # a reordered frame counts as lost when its successor arrives, and as late when it does
    assert report["totals"]["frames_lost"] == 3
    assert report["totals"]["frames_ok"] == 3


def test_an_in_order_frame_ends_a_run_of_late_frames():
    report = run([wire(0, n) for n in (200, 150, 201, 151, 202, 152)])
    assert report["channels"]["0"]["resyncs"] == 0
    assert report["channels"]["0"]["late"] == 3


def test_a_single_late_frame_does_not_resync():
    # 50 is 51 counts behind 101, past the reorder window, so it reaches the resync rule
    report = run([wire(0, n) for n in (100, 101, 50, 102)])
    assert report["channels"]["0"]["resyncs"] == 0
    assert report["channels"]["0"]["late"] == 1
    assert report["totals"]["frames_ok"] == 3


def test_late_frames_that_are_not_consecutive_do_not_resync():
    report = run([wire(0, n) for n in (100, 101, 50, 60, 70, 102)])
    assert report["channels"]["0"]["resyncs"] == 0
    assert report["channels"]["0"]["late"] == 3
    assert report["totals"]["frames_ok"] == 3


def test_after_an_outage_longer_than_half_the_counter_range_the_channel_resyncs():
    frames = [wire(0, n) for n in range(10)] + [wire(0, (210 + k) % 256) for k in range(20)]
    report = run(frames)
    assert report["channels"]["0"]["resyncs"] == 1
    assert report["channels"]["0"]["late"] == 2
    assert report["totals"]["frames_ok"] == 10 + 18
    assert report["totals"]["frames_lost"] == 0


def test_corrupted_frame_is_dropped_and_the_next_one_is_found():
    bad = bytearray(wire(0, 1))
    bad[40] ^= 0x01
    report = run([wire(0, 0), bytes(bad), wire(0, 2)])
    assert report["totals"]["frames_bad_fecf"] == 1
    assert report["totals"]["frames_ok"] == 2
    assert report["totals"]["frames_lost"] == 1


def test_marker_split_across_chunks_is_still_found():
    stream = wire(0, 0) + wire(0, 1)
    cut = len(wire(0, 0)) + 2
    report = run([stream[:cut], stream[cut:]])
    assert report["totals"]["frames_ok"] == 2


def test_frame_split_into_single_bytes():
    stream = wire(0, 0) + wire(0, 1)
    report = run([stream[i : i + 1] for i in range(len(stream))])
    assert report["totals"]["frames_ok"] == 2


def test_garbage_between_frames_is_discarded_and_counted():
    report = run([wire(0, 0), b"\x00" * 30, wire(0, 1)])
    assert report["totals"]["sync_discarded_bytes"] == 30
    assert report["totals"]["frames_ok"] == 2


def test_partial_frame_at_the_end_is_reported_not_delivered():
    stream = wire(0, 0) + wire(0, 1)[:50]
    report = run([stream])
    assert report["totals"]["frames_ok"] == 1
    assert report["totals"]["trailing_bytes"] == 50
