# =================================== #
# @Author: Fantasy_Silence            #
# @Time: 2026-11-12                   #
# @IDE: Visual Studio Code & PyCharm  #
# @Python: 3.9.7                      #
# =================================== #
# @Description: 命令行入口             #
# =================================== #
"""
用法::

    python run.py                              # 交互式菜单
    python run.py https://zujuan.xkw.com/3p2856667.html
    python run.py 3p2856667 --answers          # 连同答案解析一起导出
    python run.py <网址> --no-cache            # 忽略缓存重新抓取
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许从任意工作目录调用本脚本
sys.path.insert(0, str(Path(__file__).resolve().parent))

from interactions import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
