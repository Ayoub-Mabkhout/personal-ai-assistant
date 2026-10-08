"""Resolve private runtime paths independently of the current working directory."""

import os
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = Path(os.environ.get('ASSISTANT_STATE_DIR', str(WORKSPACE_ROOT / 'state'))).expanduser().resolve()
