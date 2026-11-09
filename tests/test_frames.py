import pytest

from passreplay.frames import ASM, build_frame, check_fecf, parse_header


def test_asm_value():
    assert ASM.hex().upper() == "1ACFFC1D"


def test_header_bytes_worked_by_hand():
    # scid 0x123 -> bits 13..4, vcid 5 -> bits 3..1: 0x1230 | 0x000A = 0x123A
    frame = build_frame(0x123, 5, 7, 9, bytes(120), 128, status=0x0102)
    assert frame[:6].hex() == "123a07090102"


def test_header_round_trip():
    frame = build_frame(0x2A5, 3, 255, 0, bytes(120), 128)
    h = parse_header(frame)
    assert (h.version, h.scid, h.vcid, h.ocf, h.mc_count, h.vc_count) == (0, 0x2A5, 3, 0, 255, 0)


def test_good_frame_passes_fecf():
    assert check_fecf(build_frame(1, 0, 0, 0, bytes(range(120)), 128))


def test_one_flipped_bit_fails_fecf():
    frame = bytearray(build_frame(1, 0, 0, 0, bytes(range(120)), 128))
    frame[50] ^= 0x04
    assert not check_fecf(bytes(frame))


def test_wrong_data_length_is_refused():
    with pytest.raises(ValueError):
        build_frame(1, 0, 0, 0, bytes(10), 128)
