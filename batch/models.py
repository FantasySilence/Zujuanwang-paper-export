# ======================================================================  #
# @Author: Fantasy_Silence                                                #
# @Time: 2026-11-12                                                       #
# @IDE: Visual Studio Code & PyCharm                                      #
# @Python: 3.9.7                                                          #
# ======================================================================  #
# @Description: 批量导出层的公共数据结构                                  #
# ======================================================================  #

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BatchResult:
    """一份试卷的处理结果。"""

    paper_id: str = ""
    url: str = ""
    ok: bool = False
    title: str = ""
    docx_path: Path | None = None
    question_count: int = 0
    answer_count: int = 0
    error: str = ""
    elapsed: float = 0.0


@dataclass
class BatchContext:
    """一次批量运行的共享配置，跨线程使用。"""

    out_dir: Path
    answers: bool
    answers_limit: int
    no_cache: bool
    names: dict[str, str]
    # 同一批里文件名去重，需要配合 lock 使用
    used_names: set[str]
    lock: threading.Lock
