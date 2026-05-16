#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from dl_over_bale.receiver import serve_forever

if __name__ == "__main__":
    serve_forever()
