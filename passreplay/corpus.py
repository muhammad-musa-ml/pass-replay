from pathlib import Path

from . import recording
from .simulate import simulate

# One pass per profile. The seeds are arbitrary; they are fixed so the files can be checked in.
CORPUS = [
    ("clean", 11),
    ("fade", 12),
    ("noisy", 13),
    ("outage-short", 14),
    ("outage-long", 15),
    ("asm-in-payload", 16),
    ("truncated", 17),
]


def write_corpus(directory, seed_offset=0):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for profile, seed in CORPUS:
        header, chunks = simulate(seed + seed_offset, profile)
        recording.write(directory / (profile + ".passrec"), header, chunks)
