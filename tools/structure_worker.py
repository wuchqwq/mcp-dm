"""One bounded external structure request on stdin; no GMS Python dependency."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crystallography.structure_tools import execute, strict_json, failure, StructureError


def main():
    try:
        raw = sys.stdin.buffer.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise StructureError("Structure request exceeds256KiB")
        reply = execute(strict_json(raw.decode("utf-8")))
    except Exception as error:
        reply = failure(error)
    sys.stdout.write(json.dumps(reply, ensure_ascii=True, allow_nan=False) + "\n")
    return 0 if reply.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
