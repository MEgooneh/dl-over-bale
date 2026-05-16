#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from dl_over_bale.sender import poll_forever

if __name__ == "__main__":
    poll_forever()
