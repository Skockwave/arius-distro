#!/usr/bin/env python3
"""ARIUS entry point.

Usage:
    python main.py            # start the interactive assistant
    python main.py init       # scaffold config + owner account
    python main.py --help
"""

import sys

from arius.cli import main

if __name__ == "__main__":
    sys.exit(main())
