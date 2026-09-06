#!/usr/bin/env python3
"""Deprecated local static server.

The Deal desk now runs as a TanStack Start app:

    npm install
    npm run dev

This module remains only so older docs/scripts that import it fail loudly.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "serve_dashboard.py is retired.\n"
        "Use the TanStack Start desk instead:\n"
        "  npm install && npm run dev\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
