# pass-replay

I wrote a small version of the frame-handling code that sits behind a ground station's modem, and a
test bench for it. The code finds telemetry frames in the received bytes and counts what was lost;
when the link degrades it raises an alert. A simulator writes recordings of passes, and a check
replays each one and compares the result with a stored report. Then I measured what the replay
notices that my unit tests do not.

I ran it on Python 3.13 only. It uses the standard library; pytest is needed to run the tests.

## Why

Test inputs written by hand only cover the cases I thought of, and a recorded pass holds others. The
posting for Northwood Space's Platform engineering role lists simulated ground stations and tools that
replay recorded data. This is my small version of both; it is not based on their code. Here,
simulated passes stand in for recorded ones.

## What is in it

- `passreplay/frames.py`, `crc.py`: a fixed-length frame with a 4-byte attached sync marker (ASM), a
  6-byte header (2-bit version, 10-bit spacecraft id, 3-bit virtual channel id, 1-bit control flag, two
  8-bit counters, 16-bit status), a payload and a 2-byte CRC-16 (polynomial 0x1021, start value
  0xFFFF). The layout follows the CCSDS telemetry transfer frame in outline. I left out the secondary
  header, the operational control field, coding and randomizing.
- `passreplay/pipeline.py`: finds markers across chunk boundaries and checks each frame. For each
  virtual channel it follows the 8-bit counter and counts lost, duplicate and late frames. A repeated
  count is a duplicate, a count up to 128 ahead of the last accepted frame means the frames in
  between were lost, and any other count is a frame from behind, which is late. The exception is the
  third of three frames in a row with consecutive counts, each more than 16 behind the last accepted
  frame: it restarts the counter, which is how a channel comes back after losing 128 to 236 frames in
  a row.
  The counts become one-second windows: lost frames are spread over the time the gap covers, and three
  windows in a row with 20% loss or more, or with nothing usable, raise a degraded-link alert.
- `passreplay/simulate.py`: a seeded simulator of one 20-second pass at 100 frames per second on two
  channels. Profiles add loss near the horizon, bit errors, truncated frames, duplicates, swapped
  neighbours, outages and the marker inside a payload. The output is cut into random chunks.
- `passreplay/replay.py`, `check.py`: a replay uses the recorded receive times, never the clock, and
  when the recording gives the pass length it counts silence at either end. `check` compares a whole
  report, including a hash of the delivered payload bytes, with the stored report in `goldens/`.
- `tools/mutate.py`: the measurement below.

## Run it

```
python -m pytest -q                      # 69 tests
python -m passreplay check               # replay the 7 recordings in corpus/ and compare with goldens/
python -m passreplay simulate --seed 3 --profile fade --out fade.passrec
python -m passreplay replay fade.passrec
python tools/mutate.py                   # about two minutes; rewrites results/mutation.md
```

## Results

The recordings in `corpus/` are simulated, one per profile. This is `results/corpus.md`, made by
`python -m passreplay summary`:

| recording | seed | frames ok | lost | failed CRC | duplicate | late | channel resyncs | degraded-link alerts |
|---|---|---|---|---|---|---|---|---|
| asm-in-payload | 16 | 1961 | 39 | 41 | 0 | 0 | 0 | 0 |
| clean | 11 | 2000 | 0 | 0 | 0 | 0 | 0 | 0 |
| fade | 12 | 1664 | 330 | 0 | 0 | 0 | 0 | 2 |
| noisy | 13 | 1866 | 134 | 101 | 38 | 17 | 0 | 0 |
| outage-long | 15 | 1698 | 82 | 0 | 0 | 2 | 1 | 1 |
| outage-short | 14 | 1900 | 100 | 0 | 0 | 0 | 0 | 0 |
| truncated | 17 | 1944 | 56 | 56 | 0 | 0 | 0 | 0 |

The 3-second outage in `outage-long` showed a flaw in my first pipeline. On the busier channel every
later frame looked late until the 8-bit counter came round again, so the pipeline from before the fix
dropped 37 good frames as late and one as a duplicate on this recording. A channel now restarts its
counter on the third of three frames in a row with consecutive counts, each more than 16 behind the
last accepted frame.

To see what each kind of test notices, `tools/mutate.py` applies small changes to the code, one at a
time, to a temporary copy. Each is a bug a release could plausibly carry, such as loss counted wrongly
across the counter wrap or a window index that rounds instead of truncating. For each change it runs
the unit tests (everything in `tests/` except `test_corpus.py`) and `check` against the stored reports.

- First run (`results/mutation-first-run.md`): 19 changes against 49 unit tests. The unit tests caught
  13 and replay caught 13; both caught 11, only the unit tests 2, only replay 2, neither 4.
- A review of the code then found real problems, fixed in the next commit: silence at the ends of a
  pass was invisible, a gap was charged to the window where the link came back, and three reordered
  frames started a false resync. I replaced one change that turned out to be equivalent (it removed a
  line that did nothing), added four for the new code, and added tests for three changes that no test
  had caught and a plain test could: a counter jump of 150 (counted as a late frame), a window at
  exactly 20% loss, and a channel id of 4 or more, which needs the third bit. The fix also rebuilt the
  `fade`, `outage-long` and `outage-short` recordings, so the two runs replay slightly different
  corpora.
- Now (`results/mutation.md`): 23 changes against 63 unit tests. The unit tests caught 22 and replay
  caught 14; both caught 13, only the unit tests 9, only replay 1, neither 0.
- Replay caught 14 with no test written for any of them. The one change only it catches skips a
  whole candidate frame after a failed check. On a frame with flipped bits, the skip only changes the
  count of discarded bytes, which no unit test checked. On a false marker or a cut frame, it also
  loses the next frame. Replay misses 9 changes that the unit tests catch. For three of them the reason is plain:
  every stored report ends with 0 leftover bytes, only channels 0 and 1 occur, and the pipeline never
  reads the spacecraft id.
- The replay result was the same on all 5 corpora (the committed one and four more built from seeds
  shifted by 1 to 4), except for the change at exactly 20% loss, which one of the shifted
  corpora happens to contain. They share seeds across profiles, so they are not independent samples.
- Two controls check the runner: a change that edits nothing survives, and one that breaks every call
  is caught by both.

## What this does not show

- The recordings are simulated, not captured from a satellite, and the frame layout is not checked
  against captured frames. The numbers say nothing about real links.
- The changes are ones I chose from reading the code. I wrote the first 19 before the first run, and
  the list changed afterwards as described above. They are not a sample of real bugs, so 22 of 23 is
  not a detection rate. I extended the unit tests after seeing what the first run missed and did not
  tune the stored reports, so the comparison is uneven.
- The stored reports are what this code printed when I ran `check --update`. A match only shows that
  nothing changed since then; I have no independent check of the numbers. The simulator drops 336
  frames from `fade` and the report counts 330 lost, because frames lost before a channel's first
  frame or after its last cannot be counted. In `outage-long` the gap on the busier channel is not
  counted at all, because the counter restarts.
- An 8-bit counter cannot tell a loss of 237 to 255 frames in a row from late frames and a duplicate,
  or a loss from one 256 frames longer. Three old frames with consecutive counts also restart a
  channel, so a burst of three repeated old frames looks like the end of an outage, and the next
  current frame then counts every number in between as lost. When two frames swap, the earlier one
  counts as lost when the later one arrives and counts again as late when it arrives itself. Late
  frames, and the first two of the three frames that restart a channel, are not delivered.
- A frame is counted in the window of the chunk that completed it, which can be a later window than
  the frame's own time.
- A replay does not wait for the recorded times, so it says nothing about how fast the code runs.

## License

MIT, see `LICENSE`.
