# ============================================================== #
# @Author: Fantasy_Silence                                       #
# @Time: 2026-11-12                                              #
# @IDE: Visual Studio Code & PyCharm                             #
# @Python: 3.9.7                                                 #
# ============================================================== #
# @Description: 整篇文档的骨架：标题、分节、答案附录。
# ============================================================== #
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from ..images import ImageCache
from ..paths import OUTPUT_DIR
from .image_run import add_image_run
from .naming import default_filename
from .options import DARK, GRAY, DocxOptions
from .render import render_blocks
from .styles import (
    set_compatibility_mode,
    set_east_asia,
    setup_page,
    setup_styles,
)


def build_document(
    paper: dict[str, Any],
    output_path: Path | str | None = None,
    *,
    options: DocxOptions | None = None,
    image_cache: ImageCache | None = None,
) -> Path:
    
    """
    生成 Word 文档并返回文件路径。
    """
    
    options = options or DocxOptions()
    cache = image_cache or ImageCache()

    if output_path is None:
        output_path = OUTPUT_DIR / default_filename(paper)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    setup_page(doc)
    setup_styles(doc, options)
    # ----- 兼容模式提到 15，否则 Word 打开时标题栏挂个“兼容模式” ---- #
    set_compatibility_mode(doc, "15")

    _write_title(doc, paper, options)

    for section in paper.get("sections", []):
        _write_section(doc, section, options, cache)

    # ------ 抓过答案才附“参考答案”，没抓就整段跳过 ----- #
    if options.include_answers:
        answers = [
            (section, question)
            for section in paper.get("sections", [])
            for question in section.get("questions", [])
            if question.get("answer_images")
        ]
        if answers:
            _write_answers(doc, answers, options, cache)

    doc.core_properties.title = paper.get("title", "")
    doc.core_properties.subject = "组卷网试卷导出"
    doc.core_properties.comments = f"来源：{paper.get('url', '')}"
    doc.core_properties.author = "Zujuanwang-paper-export"

    doc.save(str(output_path))
    return output_path


def add_horizontal_rule(doc: Document, thick: bool = False) -> None:
    
    """
    用段落下边框画一条分隔线，比插图片省事且能跟着内容走。
    """
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(6)
    ppr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12" if thick else "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "808080")
    pbdr.append(bottom)
    # -----  pBdr 在 pPr 里有固定位置，直接 append 会让 Word 认为文件损坏 ---- #
    ppr.insert_element_before(
        pbdr,
        "w:shd",
        "w:tabs",
        "w:suppressAutoHyphens",
        "w:kinsoku",
        "w:wordWrap",
        "w:overflowPunct",
        "w:topLinePunct",
        "w:autoSpaceDE",
        "w:autoSpaceDN",
        "w:bidi",
        "w:adjustRightInd",
        "w:snapToGrid",
        "w:spacing",
        "w:ind",
        "w:contextualSpacing",
        "w:mirrorIndents",
        "w:suppressOverlap",
        "w:jc",
        "w:textDirection",
        "w:textAlignment",
        "w:textboxTightWrap",
        "w:outlineLvl",
        "w:divId",
        "w:cnfStyle",
        "w:rPr",
        "w:sectPr",
        "w:pPrChange",
    )


def _write_title(doc: Document, paper: dict[str, Any], options: DocxOptions) -> None:
    title = (paper.get("title") or "试卷").strip()
    # ------ 标题尾部常挂着“-组卷网”，打印出来多余 ------ #
    title = re.sub(r"[-—]\s*组卷网\s*$", "", title)

    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(6)
    run = paragraph.add_run(title)
    run.bold = True
    run.font.size = Pt(15)
    run.font.name = options.font_heading
    run.font.color.rgb = DARK
    set_east_asia(run._element, options.font_heading)

    add_horizontal_rule(doc)


def _write_section(
    doc: Document,
    section: dict[str, Any],
    options: DocxOptions,
    cache: ImageCache,
) -> None:
    heading = doc.add_paragraph()
    heading.paragraph_format.space_before = Pt(12)
    heading.paragraph_format.space_after = Pt(4)
    heading.paragraph_format.keep_with_next = True
    run = heading.add_run(section.get("title") or "")
    run.bold = True
    run.font.size = Pt(12)
    run.font.name = options.font_heading
    set_east_asia(run._element, options.font_heading)

    for question in section.get("questions", []):
        render_blocks(doc, question.get("blocks", []), options, cache)


def _write_answers(
    doc: Document,
    answers: list[tuple[dict[str, Any], dict[str, Any]]],
    options: DocxOptions,
    cache: ImageCache,
) -> None:
    """
    答案附录。组卷网的答案是整张图片，这里只按题号排进去。
    """
    
    doc.add_page_break()
    heading = doc.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    heading.paragraph_format.space_after = Pt(8)
    run = heading.add_run("参考答案与解析")
    run.bold = True
    run.font.size = Pt(14)
    run.font.name = options.font_heading
    set_east_asia(run._element, options.font_heading)

    note = doc.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    note_run = note.add_run("答案由组卷网以图片形式提供")
    note_run.font.size = Pt(8)
    note_run.font.color.rgb = GRAY

    for section, question in answers:
        label = doc.add_paragraph()
        label.paragraph_format.space_before = Pt(8)
        label.paragraph_format.space_after = Pt(2)
        code = question.get("code") or str(question.get("index", ""))
        label_run = label.add_run(f"{section.get('title', '')}　{code}")
        label_run.bold = True
        label_run.font.size = Pt(10.5)
        set_east_asia(label_run._element, options.font_body_cn)

        for answer in question.get("answer_images", []):
            paragraph = doc.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_image_run(paragraph, answer, options, cache)
