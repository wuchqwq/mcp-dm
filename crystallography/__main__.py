"""User-invoked external companion, with machine-readable JSON on stdout."""
import argparse
import json
import sys

from .workflow import run, verify


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    analyse = commands.add_parser("run")
    analyse.add_argument("--request", required=True)
    analyse.add_argument("--output", required=True)
    analyse.add_argument("--request-id", required=True)
    check = commands.add_parser("verify")
    check.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        value = run(args.request, args.output, args.request_id) if args.command == "run" else verify(args.output)
        print(json.dumps(value, allow_nan=False))
        return 2 if value.get("state") == "NEEDS_REVIEW" else 0
    except Exception as error:
        print(json.dumps({"state": "ERROR", "error_type": type(error).__name__, "message": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
