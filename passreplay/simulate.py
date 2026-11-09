from .frames import ASM, FECF_LEN, HEADER_LEN, build_frame
from .rng import Rng

NS = 1_000_000_000

DEFAULTS = {
    "base_loss": 0.0,  # chance a frame never arrives, anywhere in the pass
    "edge_loss": 0.0,  # extra loss near the start and end of the pass, where the satellite is low
    "corrupt": 0.0,  # chance a frame arrives with 1 to 3 flipped bits
    "truncate": 0.0,  # chance the modem loses the end of a frame
    "dup": 0.0,  # chance a frame arrives twice
    "swap": 0.0,  # chance two neighbouring frames arrive in the wrong order
    "asm_in_payload": 0.0,  # chance the sync marker appears inside a payload
    "outage": None,  # (start_s, length_s): nothing arrives
}

PROFILES = {
    "clean": {},
    "fade": {"base_loss": 0.005, "edge_loss": 0.8},
    "noisy": {"base_loss": 0.01, "corrupt": 0.05, "dup": 0.02, "swap": 0.02},
    "outage-short": {"outage": (8, 1)},
    "outage-long": {"outage": (8, 3)},
    "asm-in-payload": {"asm_in_payload": 0.05, "corrupt": 0.02},
    "truncated": {"truncate": 0.03},
}


def _edge_weight(t_ns, duration_ns):
    # 1.0 at the ends of the pass, 0.0 in the middle; the same float steps on every platform
    x = abs(2 * t_ns - duration_ns) / duration_ns
    x2 = x * x
    return x2 * x2


def _flip_bits(rng, framed):
    flips = 1 + rng.below(3)
    seen = set()
    out = bytearray(framed)
    while len(seen) < flips:
        pos = len(ASM) + rng.below(len(framed) - len(ASM))
        bit = rng.below(8)
        if (pos, bit) in seen:
            continue
        seen.add((pos, bit))
        out[pos] ^= 1 << bit
    return bytes(out)


def simulate(seed, profile="clean", duration_s=20, fps=100, frame_len=128, scid=0x2A5, max_chunk=300):
    """Returns (header, chunks): a recording of one simulated pass, chunked like a modem would."""
    params = dict(DEFAULTS, **PROFILES[profile])
    rng = Rng(seed)
    period_ns = NS // fps
    duration_ns = duration_s * NS
    body_len = frame_len - HEADER_LEN - FECF_LEN

    sent = []
    mc_count = 0
    vc_counts = {0: 0, 1: 0}
    for i in range(duration_s * fps):
        vcid = 0 if rng.below(10) < 7 else 1
        data = rng.bytes(body_len)
        if rng.random() < params["asm_in_payload"]:
            at = rng.below(body_len - len(ASM) + 1)
            data = data[:at] + ASM + data[at + len(ASM) :]
        frame = build_frame(scid, vcid, mc_count, vc_counts[vcid], data, frame_len)
        mc_count = (mc_count + 1) % 256
        vc_counts[vcid] = (vc_counts[vcid] + 1) % 256
        sent.append((i * period_ns, ASM + frame))

    outage = params["outage"]
    received = []
    for t_ns, framed in sent:
        # the four yes/no draws happen for every frame in every profile, so changing one
        # rate does not change which frames the others pick
        drop = rng.random() < params["base_loss"] + params["edge_loss"] * _edge_weight(t_ns, duration_ns)
        corrupt = rng.random() < params["corrupt"]
        cut = rng.random() < params["truncate"]
        twice = rng.random() < params["dup"]
        if corrupt:
            framed = _flip_bits(rng, framed)
        if cut:
            framed = framed[: -(1 + rng.below(len(framed) // 2))]
        if drop or (outage and outage[0] * NS <= t_ns < (outage[0] + outage[1]) * NS):
            continue
        received.append((t_ns, framed))
        if twice:
            received.append((t_ns, framed))

    i = 0
    while i + 1 < len(received):
        if rng.random() < params["swap"]:
            (t0, a), (t1, b) = received[i], received[i + 1]
            received[i], received[i + 1] = (t0, b), (t1, a)
            i += 2
        else:
            i += 1

    stream = bytearray()
    ends = []
    for _, framed in received:
        stream += framed
        ends.append(len(stream))
    chunks = []
    pos = 0
    seg = 0
    while pos < len(stream):
        end = min(len(stream), pos + 1 + rng.below(max_chunk))
        while ends[seg] < end:
            seg += 1
        chunks.append((received[seg][0], bytes(stream[pos:end])))
        pos = end

    header = {
        "format": "passrec-1",
        "synthetic": True,
        "seed": seed,
        "profile": profile,
        "fps": fps,
        "duration_s": duration_s,
        "frame_len": frame_len,
        "scid": scid,
        "max_chunk": max_chunk,
    }
    return header, chunks
