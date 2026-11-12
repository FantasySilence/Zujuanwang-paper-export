# ======================================================================  #
# @Author: Fantasy_Silence                                                #
# @Time: 2026-11-12                                                       #
# @IDE: Visual Studio Code & PyCharm                                      #
# @Python: 3.9.7                                                          #
# ======================================================================  #
# @Description: 批量导出的入口脚本（真正的逻辑在 batch/ 包里）             #
# ======================================================================  #
"""
用法::

    python multi_run.py batch/data/urls.txt
    python multi_run.py batch/data/urls.txt -o output --answers --workers 2

也可以当接口用::

    from multi_run import batch_export
    results = batch_export(["3p2856667", "3p129898802"], out_dir="output")
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许从任意工作目录调用本脚本
sys.path.insert(0, str(Path(__file__).resolve().parent))

from batch import BatchResult, batch_export, load_urls  # noqa: E402
from batch.cli import main  # noqa: E402

__all__ = ["BatchResult", "batch_export", "load_urls", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
