"""独立依赖检查脚本：start.bat 用它判断 python 是否齐全。

退出码: 0 = 全部可导入；1 = 缺失。缺失的具体包名写入 stderr。
避免在 .bat 中拼装 `python -c "import ..."` 这种容易被 cmd 错误解析的字符串。
"""

import sys

REQUIRED = ("pandas", "numpy", "openpyxl", "xlrd", "matplotlib")


def main() -> int:
    missing = []
    for name in REQUIRED:
        try:
            __import__(name)
        except Exception as exc:  # noqa: BLE001 - 仅用于提示，不影响流程
            missing.append(f"{name} ({exc.__class__.__name__})")

    if missing:
        print("missing: " + ", ".join(missing), file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
