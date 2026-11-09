MASK = (1 << 64) - 1


class Rng:
    """SplitMix64. I wrote it so a seed gives the same recording on every Python version."""

    def __init__(self, seed):
        self.state = seed & MASK

    def u64(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        return z ^ (z >> 31)

    def random(self):
        return (self.u64() >> 11) / (1 << 53)

    def below(self, n):
        return self.u64() % n

    def bytes(self, n):
        out = bytearray()
        while len(out) < n:
            out += self.u64().to_bytes(8, "little")
        return bytes(out[:n])
