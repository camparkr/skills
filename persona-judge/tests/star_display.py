#!/usr/bin/env python3
"""Print the five star lines T-S checks in each harness, as report.py renders them.

Usage:
  star_display.py            print the five lines
  star_display.py --bytes    print each line with its UTF-8 bytes in hexadecimal

The lines are 0, 0.5, 3, 3.5 and 5 stars. Ask the agent in each harness to reply with them exactly, then
compare the bytes it received with --bytes; whether each renders is recorded by a person looking at it.

Exit codes: 0 printed; 2 a usage error.
"""

import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skill" / "scripts"))
import report  # noqa: E402

# The star counts T-S names (specification §8, T-S).
VALUES = (Fraction(0), Fraction(1, 2), Fraction(3), Fraction(7, 2), Fraction(5))


def main(argv):
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if argv not in ([], ["--bytes"]):
        print("star_display.py: usage: star_display.py [--bytes]", file=sys.stderr)
        return 2
    for value in VALUES:
        line = report.star_line(value)
        print(f"{line}\t{line.encode('utf-8').hex(' ')}" if argv else line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
