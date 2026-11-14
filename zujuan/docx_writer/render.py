# ============================================================== #
# @Author: Fantasy_Silence                                       #
# @Time: 2026-11-12                                              #
# @IDE: Visual Studio Code & PyCharm                             #
# @Python: 3.9.7                                                 #
# ============================================================== #
# @Description: block → Word 内容：段落、表格、单元格与选项表。
# ============================================================== #
from __future__ import annotations

import re
from typing import Any, Iterable

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from ..images import ImageCache
from .image_run import add_image_run
from .options import USABLE_WIDTH_CM, DocxOptions
from .styles import set_east_asia


def render_blocks(
    container: Any,
    blocks: Iterable[dict[str, Any]],
    options: DocxOptions,
    cache: ImageCache,
    *,
    in_table: bool = False,
) -> None:
    blocks = list(blocks)
    # ------ 选择题的题干、插图和选项表是一组，尽量排在同一页 ------ #
    option_index = next(
        (i for i, block in enumerate(blocks)
         if block.get("type") == "grid" and block.get("options")),
        None,
    )
    for index, block in enumerate(blocks):
        before = len(container.paragraphs)
        if block.get("type") == "para":
            _render_paragraph(container, block, options, cache, in_table=in_table)
        elif block.get("type") == "grid":
            _render_grid(container, block, options, cache)
        if option_index is not None and index < option_index and not in_table:
            for paragraph in container.paragraphs[before:]:
                paragraph.paragraph_format.keep_with_next = True


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
            add_image_run(paragraph, run_data, options, cache)
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
        set_east_asia(run._element, options.font_body_cn)

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

    # ------ 选项 A/B/C/D 是一组，被分页拆开就会看不明白，尽量整表留在一页 ------ #
    if options:
        _keep_table_together(table)

    # ------ 两个表格直接相邻会被 Word 合并成一张，中间必须隔个段落 ------ #
    _add_spacer(container)


def _keep_table_together(table: Any) -> None:
    
    """
    让整张表尽量不跨页：行内不许断，除最后一行外都与下一行同页。

    Word 里只能靠 keep_with_next 间接表达“这些行不许分开”，
    拆不拆仍然由 Word 按页面剩余空间决定。
    """
    
    rows = list(table.rows)
    for index, row in enumerate(rows):
        tr_pr = row._tr.get_or_add_trPr()
        if tr_pr.find(qn("w:cantSplit")) is None:
            tr_pr.append(OxmlElement("w:cantSplit"))
        # ------ 末行不需要和后面的内容绑在一起 ------ #
        if index < len(rows) - 1:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.keep_with_next = True


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
                set_east_asia(run._element, options.font_body_cn)
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
            add_image_run(paragraph, run_data, options, cache)
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
        set_east_asia(run._element, options.font_body_cn)


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
