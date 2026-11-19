"""Run the Python core from the installed Git plugin, from any working directory."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from finder_core.__main__ import entrypoint

if __name__ == "__main__":
    raise SystemExit(entrypoint())
