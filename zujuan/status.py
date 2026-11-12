# ======================================================================  #
# @Author: Fantasy_Silence                                                #
# @Time: 2026-11-12                                                       #
# @IDE: Visual Studio Code & PyCharm                                      #
# @Python: 3.9.7                                                          #
# ======================================================================  #
# @Description: 一次抓取运行的结果，爬虫写在子进程里、命令行读回来判断成败     #
# ======================================================================  #

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from . import paths

# ------ 批量下载时每份试卷各写一个文件，避免并发互相覆盖（None 表示用默认位置） ------ #
_status_path: Path | None = None


def status_file() -> Path:
    return _status_path or (paths.LOG_DIR / "last_run.json")


def set_path(path: str | Path | None) -> None:
    """指定本次运行的状态文件位置，批量下载时每份试卷用各自的文件。"""
    global _status_path
    _status_path = Path(path) if path else None


def write(*, ok: bool, **extra: Any) -> Path:
    """写本次运行结果，失败原因通过 extra 里的 error 带出去。"""
    payload: dict[str, Any] = {
        "ok": ok,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }
    payload.update(extra)
    path = status_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read() -> dict[str, Any]:
    path = status_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def clear() -> None:
    """每份试卷开始前清掉，避免把上一次的结果当成本次结果。"""
    status_file().unlink(missing_ok=True)
