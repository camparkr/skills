#!/usr/bin/env python3
"""Print five star lines, as report.py renders them, to check by eye that each harness displays the stars.

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

# report.py switches bytecode off itself; this script does too, before importing it.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skill" / "scripts"))
import report  # noqa: E402

# The star counts to show: none, a lone half, whole stars, whole stars and a half, and all five.
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
