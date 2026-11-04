import sys
from pathlib import Path
from unittest.mock import MagicMock

# Prioritize local repository over globally installed site-packages
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import torch
except Exception:
    sys.modules["torch"] = MagicMock()

