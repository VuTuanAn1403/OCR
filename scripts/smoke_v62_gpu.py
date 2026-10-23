"""Compatibility name for the unified synthetic GPU smoke check."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.smoke_unified import main

if __name__ == "__main__":
    raise SystemExit(main())
