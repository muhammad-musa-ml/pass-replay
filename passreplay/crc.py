POLY = 0x1021


def _make_table():
    table = []
    for byte in range(256):
        crc = byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
        table.append(crc)
    return tuple(table)


_TABLE = _make_table()


def crc16(data, crc=0xFFFF):
    """CRC-16 with polynomial 0x1021, start value 0xFFFF, no reflection, no final xor."""
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ _TABLE[(crc >> 8) ^ byte]
    return crc
