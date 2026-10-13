from pathlib import Path
import sys

# Make `app` importable when pytest is invoked from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
