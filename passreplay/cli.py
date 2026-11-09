import argparse
import json
import sys

from . import recording
from .check import check
from .corpus import write_corpus
from .replay import replay
from .simulate import PROFILES, simulate
from .summary import corpus_table


def _print_summary(report):
    t = report["totals"]
    print("frames ok %d, lost %d, bad check %d, duplicate %d, late %d, channel resyncs %d" % (
        t["frames_ok"], t["frames_lost"], t["frames_bad_fecf"], t["frames_dup"],
        t["frames_late"], t["channel_resyncs"]))
    print("bytes discarded while searching for a marker: %d, left over at the end: %d" % (
        t["sync_discarded_bytes"], t["trailing_bytes"]))
    for vcid, ch in report["channels"].items():
        print("channel %s: ok %d, lost %d, duplicate %d, late %d, resyncs %d" % (
            vcid, ch["ok"], ch["lost"], ch["dup"], ch["late"], ch["resyncs"]))
    for alert in report["alerts"]:
        print("degraded link: seconds %d to %d, worst window lost %.1f%%" % (
            alert["start"], alert["end"], alert["peak_loss_ppm"] / 10_000))
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

    cor = sub.add_parser("corpus", help="write the standard set of simulated passes")
    cor.add_argument("--out", default="corpus")
    cor.add_argument("--seed-offset", type=int, default=0)

    chk = sub.add_parser("check", help="replay every recording and compare with its golden report")
    chk.add_argument("--corpus", default="corpus")
    chk.add_argument("--golden", default="goldens")
    chk.add_argument("--update", action="store_true", help="write the golden reports from this build")

    smy = sub.add_parser("summary", help="markdown table of what each recording looks like")
    smy.add_argument("--corpus", default="corpus")
    smy.add_argument("--out", help="write to this file instead of printing")
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
    if args.command == "corpus":
        write_corpus(args.out, args.seed_offset)
        print("wrote the corpus to %s" % args.out)
        return 0
    if args.command == "check":
        ok, lines = check(args.corpus, args.golden, update=args.update)
        print("\n".join(lines))
        print("OK" if ok else "FAILED")
        return 0 if ok else 1
    if args.command == "summary":
        table = corpus_table(args.corpus)
        if args.out:
            with open(args.out, "w", encoding="ascii", newline="\n") as f:
                f.write(table)
        else:
            print(table, end="")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
