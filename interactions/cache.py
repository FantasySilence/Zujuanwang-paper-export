# ============================================================= #
# @Author: Fantasy_Silence                                      #
# @Time: 2026-11-12                                             #
# @IDE: Visual Studio Code & PyCharm                            #
# @Python: 3.9.7                                                #
# ============================================================= #
# @Description: 缓存相关工具：列出已缓存试卷、统计大小、清空目录     #
# ============================================================= #

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from zujuan import paths


def cached_papers() -> list[dict[str, Any]]:
    
    """
    列出 .temp/data 下的试卷，最近导出的排在前面。
    """
    
    items: list[dict[str, Any]] = []
    for path in paths.DATA_DIR.glob("*.paper.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items.append({
            "path": str(path),
            "paper_id": data.get("paper_id", path.stem),
            "title": data.get("title") or path.stem,
            "question_count": (data.get("stats") or {}).get("question_count", "?"),
            "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            "_mtime": path.stat().st_mtime,
        })
    items.sort(key=lambda item: item["_mtime"], reverse=True)
    return items


def dir_size(path: Path) -> int:
    
    """
    统计目录占用，用来在缓存菜单里显示大小。
    """
    
    total = 0
    if not path.exists():
        return 0
    for file_path in path.rglob("*"):
        try:
            if file_path.is_file():
                total += file_path.stat().st_size
        except OSError:
            continue
    return total


def remove_tree(path: Path) -> None:
    
    """
    清空目录但保留目录本身，Scrapy 下次写入不会因为目录不存在报错。
    """
    
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
