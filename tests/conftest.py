import sys
from unittest.mock import MagicMock

try:
    import torch
except Exception:
    sys.modules["torch"] = MagicMock()
