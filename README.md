# pass-replay

I built a small test bench for the data path of a satellite ground station. A simulator writes
recordings of passes, a pipeline finds telemetry frames in the recorded bytes, and a check replays
every recording and compares the result with a stored known-good report. Then I measured what that
replay catches that my unit tests do not.

Python 3.10 or newer, standard library only. pytest is needed to run the tests.

## Why

Software on a ground station has to be tested against passes it has already seen, not only against
inputs written by hand. The Platform Engineering posting at Northwood Space lists simulated ground
stations and tools that replay recorded data among its work. This is my own small version of both.
It has no connection to their code.

## What is in it

- `passreplay/frames.py`, `crc.py`: a fixed-length frame with a 4-byte sync marker, a 6-byte header
  (2-bit version, 10-bit spacecraft id, 3-bit virtual channel id, 1-bit control flag, two 8-bit
  counters, 16-bit status), a payload and a 2-byte CRC-16 (polynomial 0x1021, start value 0xFFFF).
  The layout follows the CCSDS telemetry transfer frame in outline. I left out the secondary header,
  the operational control field, coding and randomizing.
- `passreplay/pipeline.py`: finds markers across chunk boundaries, checks each frame, tracks each
  virtual channel's 8-bit counter (loss, duplicates, late frames, resync after a long outage), and
  turns the counts into one-second windows. Three windows in a row with 20% loss or more, or with
  nothing usable, raise a degraded-link alert.
- `passreplay/simulate.py`: a seeded simulator of one 20-second pass at 100 frames per second on two
  channels. Profiles add loss near the horizon, bit errors, a truncated frame, duplicates, swapped
  neighbours, outages and the marker inside a payload. The output is cut into random chunks.
- `passreplay/replay.py`, `check.py`: a replay uses the recorded receive times and never the clock,
  so it gives the same report every run. `check` compares a whole report, including a hash of the
  delivered payload bytes, with the golden report in `goldens/`.
- `tools/mutate.py`: the measurement below.

## Run it

```
python -m pytest -q                      # 55 tests
python -m passreplay check               # replay the 7 recordings in corpus/ and compare with goldens/
python -m passreplay simulate --seed 3 --profile fade --out fade.passrec
python -m passreplay replay fade.passrec
python tools/mutate.py                   # about two minutes; rewrites results/mutation.md
```

## Results

The recordings in `corpus/` are simulated, one per profile. This is `results/corpus.md`, made by
`python -m passreplay summary`:

| recording | seed | frames ok | lost | bad check | duplicate | late | channel resyncs | degraded-link alerts |
|---|---|---|---|---|---|---|---|---|
| asm-in-payload | 16 | 1961 | 39 | 41 | 0 | 0 | 0 | 0 |
| clean | 11 | 2000 | 0 | 0 | 0 | 0 | 0 | 0 |
| fade | 12 | 1664 | 330 | 0 | 0 | 0 | 0 | 2 |
| noisy | 13 | 1866 | 134 | 101 | 38 | 17 | 0 | 0 |
| outage-long | 15 | 1698 | 82 | 0 | 0 | 2 | 1 | 1 |
| outage-short | 14 | 1900 | 100 | 0 | 0 | 0 | 0 | 0 |
| truncated | 17 | 1944 | 56 | 56 | 0 | 0 | 0 | 0 |

The 3-second outage in `outage-long` showed a flaw in my first pipeline. On the busier channel every
later frame looked "late" until the 8-bit counter came round again, so 37 good frames were dropped as
late and one as a duplicate (I replayed this recording through the code from before the fix). The
resync rule and its tests came from that.

To see what each kind of test notices, `tools/mutate.py` applies 19 one-line changes to the code, one
at a time, to a temporary copy. Each is a bug a release could plausibly carry, such as loss counted
wrongly across the counter wrap or a window index that rounds instead of truncating. For each change
it runs the 49 unit tests that do not read the corpus, and it runs `check` against the golden
reports. `results/mutation.md` has the full table. The summary:

- Unit tests caught 13 of 19. Replay caught 13 of 19. Both caught 11.
- Only the unit tests caught 2: the leftover-bytes count at the end of a pass (the corpus always
  ends on a frame boundary) and the spacecraft id mask (the pipeline never reads it).
- Only replay caught 2: skipping a whole candidate frame after a failed check, and rounding the window
  index to the nearest second. My unit tests have no case that makes either one visible.
- Neither caught 4: a jump of 129 to 192 counts treated as loss instead of late, a window at exactly
  the threshold, a virtual channel id read as 2 bits (the corpus uses channels 0 and 1, and the one
  header I parse in a unit test is on channel 3), and a streak reset that I believe changes nothing
  because the next line clears the same state.
- Everything replay caught, it caught on all 5 corpora (the committed one and four more built from
  seeds shifted by 1 to 4). Everything it missed, it missed on all 5.
- Two controls check the runner: a change that edits nothing survives, and one that breaks every call
  is caught by both.

## What this does not show

- The recordings are simulated, not captured from a satellite, and the frame layout is not checked
  against captured frames. The numbers say nothing about real links.
- The 19 changes are ones I chose from reading the code. I wrote the list before the first run and did
  not change it after. They are not a sample of real bugs, so 13 of 19 is not a detection rate.
- Replay only sees what the recordings exercise. The corpus has no virtual channel above 1, and in
  each of the five corpora none of about 13,000 counter steps is a jump of 129 to 192.
- An 8-bit counter cannot tell a gap of more than 128 frames from an old frame arriving late. After
  such an outage the pipeline resyncs and does not count the gap as loss. A swapped pair of frames
  counts as one lost and one late.
- A replay checks results, not timing. It does not wait for the recorded times.
- It is Python and I did not measure its speed.

## License

MIT, see `LICENSE`.
