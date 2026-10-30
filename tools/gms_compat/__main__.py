"""Entry point for ``python -m gms_compat``."""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import cli  # noqa: E402  (path insertion is required for flat module imports)

if __name__ == "__main__":
    sys.exit(cli.main(sys.argv[1:]))
