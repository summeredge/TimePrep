"""工业时序数据预处理工具 MVP —— 启动入口。

用法: python main.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ui.app import main  # noqa: E402

if __name__ == "__main__":
    main()
