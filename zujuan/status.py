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


def status_file() -> Path:
    return paths.LOG_DIR / "last_run.json"


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
