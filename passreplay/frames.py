from collections import namedtuple

from .crc import crc16

# Every frame on the wire is ASM + frame, and every frame has the same length.
ASM = bytes.fromhex("1ACFFC1D")
HEADER_LEN = 6
FECF_LEN = 2

Header = namedtuple("Header", "version scid vcid ocf mc_count vc_count status")


def build_frame(scid, vcid, mc_count, vc_count, data, frame_len, status=0):
    body_len = frame_len - HEADER_LEN - FECF_LEN
    if len(data) != body_len:
        raise ValueError("data must be %d bytes, got %d" % (body_len, len(data)))
    word = ((scid & 0x3FF) << 4) | ((vcid & 0x7) << 1)
    body = (
        word.to_bytes(2, "big")
        + bytes([mc_count & 0xFF, vc_count & 0xFF])
        + status.to_bytes(2, "big")
        + data
    )
    return body + crc16(body).to_bytes(2, "big")


def parse_header(frame):
    word = int.from_bytes(frame[0:2], "big")
    return Header(
        version=word >> 14,
        scid=(word >> 4) & 0x3FF,
        vcid=(word >> 1) & 0x7,
        ocf=word & 1,
        mc_count=frame[2],
        vc_count=frame[3],
        status=int.from_bytes(frame[4:6], "big"),
    )


def check_fecf(frame):
    return int.from_bytes(frame[-FECF_LEN:], "big") == crc16(frame[:-FECF_LEN])
