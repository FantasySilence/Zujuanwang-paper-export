# ============================================================== #
# @Author: Fantasy_Silence                                       #
# @Time: 2026-11-12                                              #
# @IDE: Visual Studio Code & PyCharm                             #
# @Python: 3.9.7                                                 #
# ============================================================== #
# @Description: 文件名处理：试卷标题 → 可用文件名。
# ============================================================== #
from __future__ import annotations

import re
from typing import Any


def default_filename(paper: dict[str, Any]) -> str:
    title = (paper.get("title") or "").strip()
    if not title:
        return f"{paper.get('paper_id', 'paper')}.docx"
    return f"{sanitize_filename(title)}.docx"


def resolve_filename(paper: dict[str, Any], custom_name: str | None = None) -> str:
    
    """
    决定输出文件名：用户填了就用用户的，没填就退回试卷原标题。
    用户可能只输入“期中卷”也可能连 .docx 一起贴进来，这里统一补齐后缀。
    """
    
    name = (custom_name or "").strip()
    if not name:
        return default_filename(paper)
    # ------ 去掉用户自己加的扩展名，统一由这里补成 .docx ------ #
    if name.lower().endswith(".docx"):
        name = name[:-5]
    return f"{sanitize_filename(name)}.docx"


def sanitize_filename(name: str, max_length: int = 120) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > max_length:
        name = name[:max_length].rstrip(" .")
    return name or "paper"
