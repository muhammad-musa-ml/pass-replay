from passreplay.crc import crc16


def test_catalogue_check_value():
    # The usual check input for CRC catalogues; this variant is CRC-16/IBM-3740.
    assert crc16(b"123456789") == 0x29B1


def test_empty_input_returns_start_value():
    assert crc16(b"") == 0xFFFF


def test_appending_the_crc_gives_zero():
    data = bytes(range(200))
    assert crc16(data + crc16(data).to_bytes(2, "big")) == 0
