# ============================================================== #
# @Author: Fantasy_Silence                                       #
# @Time: 2026-11-12                                              #
# @IDE: Visual Studio Code & PyCharm                             #
# @Python: 3.9.7                                                 #
# ============================================================== #
# @Description: 把 extractor 解析出的试卷结构渲染成 Word 文档。     #
# ============================================================== #
"""
把 extractor 解析出的试卷结构渲染成 Word 文档。

对外只需要这个包根提供的五项：``DocxOptions`` / ``build_document`` /
``default_filename`` / ``resolve_filename`` / ``sanitize_filename``。

模块分工::

    options.py     DocxOptions 与页宽 / 图片缩放等常量
    naming.py      文件名：试卷标题 → 合法文件名
    styles.py      页面、样式、字体等全局设置
    image_run.py   图片插入（含 python-docx 不认的 JPEG 补头）
    render.py      block（段落 / 表格 / 图片）→ Word 内容
    document.py    整篇文档骨架：标题、分节、答案附录
"""

from __future__ import annotations

from .document import build_document
from .naming import default_filename, resolve_filename, sanitize_filename
from .options import DocxOptions

__all__ = [
    "DocxOptions",
    "build_document",
    "default_filename",
    "resolve_filename",
    "sanitize_filename",
]
