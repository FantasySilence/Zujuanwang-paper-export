# ============================================================== #
# @Author: Fantasy_Silence                                       #
# @Time: 2026-11-12                                              #
# @IDE: Visual Studio Code & PyCharm                             #
# @Python: 3.9.7                                                 #
# ============================================================== #
# @Description: 把 extractor 解析出的试卷结构渲染成 Word 文档。     #
# ============================================================== #

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.image.image import Image as DocxImage
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .images import ImageCache
from .paths import OUTPUT_DIR

__all__ = [
    "DocxOptions",
    "build_document",
    "default_filename",
    "resolve_filename",
    "sanitize_filename",
]


USABLE_WIDTH_CM = 16.6
# ------ 网页上的展示宽度是按屏幕像素给的，打印时放大一点更清晰 ------ #
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
    _setup_page(doc)
    _setup_styles(doc, options)
    # ----- 兼容模式提到 15，否则 Word 打开时标题栏挂个“兼容模式” ---- #
    _set_compatibility_mode(doc, "15")

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


def _set_compatibility_mode(doc: Document, mode: str = "15") -> None:
   
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


def _setup_page(doc: Document) -> None:
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


def _setup_styles(doc: Document, options: DocxOptions) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = options.font_body
    normal.font.size = Pt(options.body_size)
    normal.font.color.rgb = DARK
    _set_east_asia(normal.element, options.font_body_cn)

    fmt = normal.paragraph_format
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(2)
    fmt.line_spacing = 1.15


def _set_east_asia(element: Any, font_name: str) -> None:
    
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
    _set_east_asia(run._element, options.font_heading)

    _add_horizontal_rule(doc)


def _add_horizontal_rule(doc: Document, thick: bool = False) -> None:
    
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
    _set_east_asia(run._element, options.font_heading)

    for question in section.get("questions", []):
        _render_blocks(doc, question.get("blocks", []), options, cache)


def _render_blocks(
    container: Any,
    blocks: Iterable[dict[str, Any]],
    options: DocxOptions,
    cache: ImageCache,
    *,
    in_table: bool = False,
) -> None:
    for block in blocks:
        if block.get("type") == "para":
            _render_paragraph(container, block, options, cache, in_table=in_table)
        elif block.get("type") == "grid":
            _render_grid(container, block, options, cache)


def _render_paragraph(
    container: Any,
    block: dict[str, Any],
    options: DocxOptions,
    cache: ImageCache,
    *,
    in_table: bool = False,
) -> None:
    paragraph = container.add_paragraph()
    align = block.get("align")
    if align == "center":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == "right":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if block.get("indent") and not in_table:
        paragraph.paragraph_format.first_line_indent = Pt(options.body_size * 2)

    has_image = False
    for run_data in block.get("runs", []):
        if run_data.get("type") == "img":
            _add_image_run(paragraph, run_data, options, cache)
            has_image = True
            continue
        text = run_data.get("text", "")
        if not text:
            continue
        run = paragraph.add_run(text)
        run.bold = bool(run_data.get("b"))
        run.italic = bool(run_data.get("i"))
        run.underline = bool(run_data.get("u"))
        if run_data.get("sup"):
            run.font.superscript = True
        if run_data.get("sub"):
            run.font.subscript = True
        run.font.size = Pt(options.body_size)
        _set_east_asia(run._element, options.font_body_cn)

    if has_image:
        paragraph.paragraph_format.space_before = Pt(2)
        paragraph.paragraph_format.space_after = Pt(4)


def _render_grid(
    container: Any,
    block: dict[str, Any],
    options: DocxOptions,
    cache: ImageCache,
) -> None:
    rows = block.get("rows") or []
    if not rows:
        return
    cols = max(len(r) for r in rows)
    if cols == 0:
        return

    table = container.add_table(rows=len(rows), cols=cols)
    # ----- 选项表要无边框，其它表格（方框选词、填表题）保留框线 ----- #
    visible = bool(block.get("borders"))
    if visible:
        try:
            table.style = "Table Grid"
        except KeyError:
            _set_table_borders(table, visible=True)
    else:
        _set_table_borders(table, visible=False)

    # ------ 关掉自动调整，否则 Word 会按内容把小题号那一列撑宽 ------ #
    table.autofit = False
    widths = _column_widths(block, cols)

    for row_index, row in enumerate(rows):
        for col_index in range(cols):
            cell = table.cell(row_index, col_index)
            cell.width = widths[col_index]
            # ------ 行内单元格数量可能不齐，缺的补空单元格 ------ #
            cell_blocks = row[col_index] if col_index < len(row) else []
            _render_cell(cell, cell_blocks, options, cache)

    for col_index, width in enumerate(widths):
        table.columns[col_index].width = width

    # ------ 两个表格直接相邻会被 Word 合并成一张，中间必须隔个段落 ------ #
    _add_spacer(container)


def _render_cell(
    cell: Any,
    blocks: list[dict[str, Any]],
    options: DocxOptions,
    cache: ImageCache,
) -> None:
    # ------ 单元格自带一个空段落，能复用就复用，避免开头多一行空行 ------ #
    existing = cell.paragraphs
    first = existing[0] if existing else None
    if not blocks:
        if first is not None:
            first.paragraph_format.space_after = Pt(0)
        return

    added = 0
    for index, block in enumerate(blocks):
        if block.get("type") == "para":
            if index == 0 and first is not None:
                _fill_paragraph(first, block, options, cache, in_table=True)
                added += 1
            else:
                _render_paragraph(cell, block, options, cache, in_table=True)
        elif block.get("type") == "grid":
            # ------ python-docx 做不出嵌套表格，内层表格退化成一行行文字 ------ #
            for line in _grid_to_lines(block):
                paragraph = first if (index == 0 and first is not None and added == 0) else cell.add_paragraph()
                run = paragraph.add_run(line)
                run.font.size = Pt(options.body_size)
                _set_east_asia(run._element, options.font_body_cn)
                added += 1
    if added == 0 and first is not None:
        first.paragraph_format.space_after = Pt(0)


def _fill_paragraph(
    paragraph: Any,
    block: dict[str, Any],
    options: DocxOptions,
    cache: ImageCache,
    *,
    in_table: bool = False,
) -> None:
    align = block.get("align")
    if align == "center":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == "right":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    paragraph.paragraph_format.space_after = Pt(0)
    for run_data in block.get("runs", []):
        if run_data.get("type") == "img":
            _add_image_run(paragraph, run_data, options, cache)
            continue
        text = run_data.get("text", "")
        if not text:
            continue
        run = paragraph.add_run(text)
        run.bold = bool(run_data.get("b"))
        run.italic = bool(run_data.get("i"))
        run.underline = bool(run_data.get("u"))
        if run_data.get("sup"):
            run.font.superscript = True
        if run_data.get("sub"):
            run.font.subscript = True
        run.font.size = Pt(options.body_size)
        _set_east_asia(run._element, options.font_body_cn)


def _grid_to_lines(block: dict[str, Any]) -> list[str]:
    
    """
    把内层表格压成文字行，单元格之间用全角空格隔开。
    """
    
    lines: list[str] = []
    for row in block.get("rows", []):
        cells = []
        for cell in row:
            texts = []
            for cell_block in cell:
                if cell_block.get("type") == "para":
                    # ------ 图片在这条退化路径上没法插，只取文字 ------ #
                    texts.append(
                        "".join(
                            r.get("text", "") for r in cell_block.get("runs", []) if r.get("type") != "img"
                        ).strip()
                    )
            joined = " ".join(t for t in texts if t)
            if joined:
                cells.append(joined)
        line = "　".join(cells)
        if line:
            lines.append(line)
    return lines


def _column_widths(block: dict[str, Any], cols: int) -> list[Any]:
    rows = block.get("rows") or []
    first_cell = rows[0][0] if rows and rows[0] else []
    # “11. | A. habit | B. experience | C. service”这种，第一列只放小题号
    narrow_first = block.get("options") and cols >= 2 and _is_index_cell(first_cell)
    if narrow_first:
        first = Cm(1.1)
        rest = (USABLE_WIDTH_CM - 1.1) / (cols - 1)
        return [first] + [Cm(rest)] * (cols - 1)
    share = Cm(USABLE_WIDTH_CM / cols)
    return [share] * cols


def _is_index_cell(cell_blocks: list[dict[str, Any]]) -> bool:
    
    """
    判断单元格里是不是只有一个小题号。
    """
    
    text = "".join(
        run.get("text", "")
        for block in cell_blocks
        if block.get("type") == "para"
        for run in block.get("runs", [])
    ).strip()
    return bool(re.fullmatch(r"\d{1,3}[.．、]?", text))


def _set_table_borders(table: Any, visible: bool) -> None:
    
    """
    直接写 tblBorders：样式里没有无边框表格，只能自己置 nil。
    """
    
    tbl_pr = table._tbl.tblPr
    for existing in tbl_pr.findall(qn("w:tblBorders")):
        tbl_pr.remove(existing)

    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = OxmlElement(f"w:{edge}")
        if visible:
            element.set(qn("w:val"), "single")
            element.set(qn("w:sz"), "4")
            element.set(qn("w:space"), "0")
            element.set(qn("w:color"), "999999")
        else:
            element.set(qn("w:val"), "nil")
        borders.append(element)

    # tblBorders 在 tblPr 中的位置是固定的，顺序错了 Word 会忽略
    tbl_pr.insert_element_before(
        borders,
        "w:shd",
        "w:tblLayout",
        "w:tblCellMar",
        "w:tblLook",
        "w:tblCaption",
        "w:tblDescription",
        "w:tblPrChange",
    )


def _add_image_run(
    paragraph: Any,
    run_data: dict[str, Any],
    options: DocxOptions,
    cache: ImageCache,
) -> None:
    local = cache.local_path(run_data.get("src", ""))
    # ------ 图片单独下载，失败就留一行灰字，不让整篇文档生成不下去 ------ #
    if local is None:
        run = paragraph.add_run("[图片缺失]")
        run.font.size = Pt(9)
        run.font.color.rgb = GRAY
        return
    try:
        width_cm = _image_width_cm(local, run_data.get("width"))
        paragraph.add_run().add_picture(str(local), width=Cm(width_cm))
    except Exception:  # noqa: BLE001 - 个别格式 python-docx 不支持
        run = paragraph.add_run("[图片无法插入]")
        run.font.size = Pt(9)
        run.font.color.rgb = GRAY


def _image_width_cm(path: Path, width_px: int | None) -> float:
    
    """
    网页上的展示宽度换算成打印宽度；没有展示宽度时按原图尺寸并限宽。
    """
    
    max_cm = USABLE_WIDTH_CM - 0.4
    # ------ 浏览器按 96dpi 换算 CSS 像素，这里保持一致 ------ #
    if width_px and width_px > 0:
        return round(min(width_px / 96 * 2.54 * IMAGE_PRINT_SCALE, max_cm), 2)
    try:
        image = DocxImage.from_file(str(path))
        natural = image.px_width / 96 * 2.54
        return round(min(natural, max_cm), 2)
    except Exception:  # noqa: BLE001
        return min(10.0, max_cm)


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
    _set_east_asia(run._element, options.font_heading)

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
        _set_east_asia(label_run._element, options.font_body_cn)

        for answer in question.get("answer_images", []):
            paragraph = doc.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_image_run(paragraph, answer, options, cache)


def _add_spacer(container: Any) -> None:
    
    """
    插入一个极矮的空段落，用于分隔相邻表格。
    段落标记的字号调到 4 磅，肉眼几乎看不出来，但足够挡住 Word 的表格合并。
    """
    paragraph = container.add_paragraph()
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(0)
    fmt.line_spacing = Pt(4)
    ppr = paragraph._p.get_or_add_pPr()
    rpr = OxmlElement("w:rPr")
    size = OxmlElement("w:sz")
    size.set(qn("w:val"), "4")
    rpr.append(size)
    ppr.append(rpr)
