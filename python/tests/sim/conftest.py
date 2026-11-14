import sys
from pathlib import Path

# The repository keeps importable packages under python/; this lets the suite
# exercise the worktree source without reinstalling the virtualenv package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

