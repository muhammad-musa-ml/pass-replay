import argparse
import json
import sys

from . import recording
from .replay import replay
from .simulate import PROFILES, simulate


def _print_summary(report):
    t = report["totals"]
    print("frames ok %d, lost %d, bad check %d, duplicate %d, late %d" % (
        t["frames_ok"], t["frames_lost"], t["frames_bad_fecf"], t["frames_dup"], t["frames_late"]))
    print("bytes discarded while searching for a marker: %d, left over at the end: %d" % (
        t["sync_discarded_bytes"], t["trailing_bytes"]))
    for vcid, ch in report["channels"].items():
        print("channel %s: ok %d, lost %d, duplicate %d, late %d" % (
            vcid, ch["ok"], ch["lost"], ch["dup"], ch["late"]))
    print("payload sha256 %s" % report["data_sha256"])


def build_parser():
    parser = argparse.ArgumentParser(prog="passreplay")
    sub = parser.add_subparsers(dest="command", required=True)

    sim = sub.add_parser("simulate", help="write a simulated pass to a recording file")
    sim.add_argument("--seed", type=int, required=True)
    sim.add_argument("--profile", choices=sorted(PROFILES), default="clean")
    sim.add_argument("--duration", type=int, default=20, help="seconds")
    sim.add_argument("--fps", type=int, default=100, help="frames per second")
    sim.add_argument("--out", required=True)

    rep = sub.add_parser("replay", help="replay a recording through the pipeline")
    rep.add_argument("recording")
    rep.add_argument("--json", action="store_true", help="print the full report")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "simulate":
        header, chunks = simulate(args.seed, args.profile, duration_s=args.duration, fps=args.fps)
        recording.write(args.out, header, chunks)
        print("wrote %s: %d chunks" % (args.out, len(chunks)))
        return 0
    if args.command == "replay":
        report = replay(args.recording)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            _print_summary(report)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
