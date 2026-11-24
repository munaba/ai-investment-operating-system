import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aios_v2_rank import run  # noqa: E402

sys.exit(run("idx"))
