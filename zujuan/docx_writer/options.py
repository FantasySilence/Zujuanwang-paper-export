# ============================================================== #
# @Author: Fantasy_Silence                                       #
# @Time: 2026-11-12                                              #
# @IDE: Visual Studio Code & PyCharm                             #
# @Python: 3.9.7                                                 #
# ============================================================== #
# @Description: 排版选项与全局常量。
# ============================================================== #
from __future__ import annotations

from dataclasses import dataclass

from docx.shared import RGBColor

__all__ = ["DocxOptions"]


USABLE_WIDTH_CM = 16.6


IMAGE_PRINT_SCALE = 1.15


GRAY = RGBColor(0x66, 0x66, 0x66)


DARK = RGBColor(0x1A, 0x1A, 0x1A)


@dataclass
class DocxOptions:
    
    """
    Word 输出选项。
    """

    include_answers: bool = True
    font_body: str = "Times New Roman"
    font_body_cn: str = "宋体"
    font_heading: str = "黑体"
    body_size: float = 10.5
