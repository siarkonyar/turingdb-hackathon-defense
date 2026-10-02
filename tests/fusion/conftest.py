"""fusion/ modules use flat imports (they run as scripts), so put the folder on sys.path."""

import sys
from pathlib import Path

FUSION_DIR = Path(__file__).resolve().parents[2] / "fusion"
if str(FUSION_DIR) not in sys.path:
    sys.path.insert(0, str(FUSION_DIR))
