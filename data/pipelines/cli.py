"""Pipeline commands.

python -m data.pipelines.cli run                      sync every source, then build the warehouse
python -m data.pipelines.cli replay                   rebuild the whole warehouse from raw
python -m data.pipelines.cli replay --from D --to D   recompute usage for a range of days
python -m data.pipelines.cli stall SOURCE [--hours N] make a source look stopped N hours ago
python -m data.pipelines.cli resume SOURCE
"""

import argparse
import sys
from datetime import date

from data.pipelines import runner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m data.pipelines.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run")
    replay = commands.add_parser("replay")
    replay.add_argument("--from", dest="start", type=date.fromisoformat)
    replay.add_argument("--to", dest="end", type=date.fromisoformat)
    stall = commands.add_parser("stall")
    stall.add_argument("source")
    stall.add_argument("--hours", type=float, default=48)
    commands.add_parser("resume").add_argument("source")
    args = parser.parse_args(argv)

    if args.command == "run":
        synced, built = runner.refresh()
        for source, outcome in synced.items():
            print(f"{source}: {outcome}")
        print("warehouse build:", "ok" if built else "FAILED, see meta.check_results")
        return 1 if runner.failed_sources(synced) or not built else 0

    with runner.connect() as conn:
        if args.command == "replay":
            if bool(args.start) != bool(args.end):
                parser.error("--from and --to go together")
            days = (args.start, args.end) if args.start else None
            built = runner.build(conn, full_refresh=days is None, replay=days)
            print("replay:", "ok" if built else "FAILED, see meta.check_results")
            return 0 if built else 1
        try:
            if args.command == "stall":
                runner.stall(conn, args.source, args.hours)
            else:
                runner.resume(conn, args.source)
        except ValueError as error:
            parser.error(str(error))
        print(f"{args.source}: {args.command} done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
