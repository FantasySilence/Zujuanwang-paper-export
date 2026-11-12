# ======================================================================  #
# @Author: Fantasy_Silence                                                #
# @Time: 2026-11-12                                                       #
# @IDE: Visual Studio Code & PyCharm                                      #
# @Python: 3.9.7                                                          #
# ======================================================================  #
# @Description: 输入归一化：把列表 / 文本文件 / 一段文本统一成网址列表     #
# ======================================================================  #

from __future__ import annotations

from pathlib import Path
from typing import Sequence


def load_urls(source: Sequence[str] | str | Path) -> list[str]:
    
    """
    把输入统一成网址列表。

    可以给：列表、文本文件路径、一段带换行的文本。
    空行和 # 开头的行会被忽略，方便直接维护一份 urls.txt。
    """
    
    if isinstance(source, (list, tuple)):
        rows = [str(item) for item in source]
    elif isinstance(source, Path):
        rows = read_lines(source)
    elif isinstance(source, str):
        candidate = Path(source)
        # ------ 传进来的可能是文件路径，也可能直接就是网址，靠“文件是否存在”区分 ------ #
        if "\n" not in source and candidate.is_file():
            rows = read_lines(candidate)
        else:
            rows = source.splitlines()
    else:
        raise TypeError(f"不支持的 urls 类型：{type(source).__name__}")

    cleaned: list[str] = []
    for row in rows:
        text = row.strip()
        if not text or text.startswith("#"):
            continue
        cleaned.append(text)
    return cleaned


def read_lines(path: Path) -> list[str]:
    """按行读文本，兼容记事本另存的 UTF-8 BOM 和 GBK。"""
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=encoding).splitlines()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"读不出这个文件，编码无法识别：{path}")
