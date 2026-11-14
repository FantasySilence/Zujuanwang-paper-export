# ============================================================== #
# @Author: Fantasy_Silence                                       #
# @Time: 2026-11-12                                              #
# @IDE: Visual Studio Code & PyCharm                             #
# @Python: 3.9.7                                                 #
# ============================================================== #
# @Description: 页面与样式的全局设置。
# ============================================================== #
from __future__ import annotations

from typing import Any

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from .options import DARK, DocxOptions


def set_compatibility_mode(doc: Document, mode: str = "15") -> None:
   
    """
    把文档兼容模式提到 Word 2013+，避免 Word 打开时显示“兼容模式”。
    """
   
    settings = doc.settings.element
    compat = settings.find(qn("w:compat"))
    if compat is None:
        compat = OxmlElement("w:compat")
        settings.append(compat)
    for item in compat.findall(qn("w:compatSetting")):
        if item.get(qn("w:name")) == "compatibilityMode":
            item.set(qn("w:val"), mode)
            return
    element = OxmlElement("w:compatSetting")
    element.set(qn("w:name"), "compatibilityMode")
    element.set(qn("w:uri"), "http://schemas.microsoft.com/office/word")
    element.set(qn("w:val"), mode)
    compat.append(element)


def setup_page(doc: Document) -> None:
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.orientation = WD_ORIENT.PORTRAIT
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)
    section.header_distance = Cm(1.2)
    section.footer_distance = Cm(1.2)


def setup_styles(doc: Document, options: DocxOptions) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = options.font_body
    normal.font.size = Pt(options.body_size)
    normal.font.color.rgb = DARK
    set_east_asia(normal.element, options.font_body_cn)

    fmt = normal.paragraph_format
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(2)
    fmt.line_spacing = 1.15


def set_east_asia(element: Any, font_name: str) -> None:
    
    """
    给样式/run 的 rPr 补上东亚字体。
    只设 font.name 只管西文，中文会回落到默认字体，所以 eastAsia 必须单独写。
    """
    
    try:
        rpr = element.get_or_add_rPr()
    except AttributeError:
        rpr = element.find(qn("w:rPr"))
        if rpr is None:
            rpr = OxmlElement("w:rPr")
            element.append(rpr)
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:eastAsia"), font_name)
