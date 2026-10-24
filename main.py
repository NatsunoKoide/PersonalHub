"""双击或用快捷方式启动时走这里。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
