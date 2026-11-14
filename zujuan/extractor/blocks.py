# =========================================================== #
# @Author: Fantasy_Silence                                    #
# @Time: 2026-11-12                                           #
# @IDE: Visual Studio Code & PyCharm                          #
# @Python: 3.9.7                                              #
# =========================================================== #
# @Description: 题面内容解析：HTML 片段 → 段落 / 表格 / 图片混合的 block 列表。
# =========================================================== #
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup, NavigableString, Tag


BLOCK_TAGS = {
    "p", "div", "table", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "ul", "ol", "dl", "dt", "dd", "blockquote", "pre",
    "section", "article", "figure", "figcaption", "hr",
}


_FMT_KEYS = ("b", "i", "u", "sup", "sub")


_WS_RE = re.compile(r" {2,}")


def extract_blocks(container: Tag | None) -> list[dict[str, Any]]:
    """把题面容器拆成段落 / 表格块序列，保留行内格式与图片。

    题面里块级元素和行内元素是穿插的（``文字 <bk/> 文字 <br/> 文字``），
    所以先攒 run，遇到块级元素再把攒下的收成一个段落。
    """
    if container is None:
        return []

    blocks: list[dict[str, Any]] = []
    buf: list[dict[str, Any]] = []

    def flush(align: str | None = None, indent: bool = False) -> None:
        nonlocal buf
        runs = _trim_runs(buf)
        if runs:
            blocks.append({"type": "para", "runs": runs, "align": align, "indent": indent})
        buf = []

    for child in container.children:
        if isinstance(child, NavigableString):
            _push_text(buf, _node_text(str(child)), {})
            continue
        if not isinstance(child, Tag):
            continue

        name = child.name
        if name in ("script", "style", "noscript"):
            continue

        style = _style(child)

        if name == "table":
            flush()
            blocks.append(_table_block(child))
        elif name in BLOCK_TAGS and name != "hr":
            # div 里还套着块级元素时继续往下拆，否则整块当一个段落
            if _has_block_children(child):
                flush()
                blocks.extend(extract_blocks(child))
            else:
                flush()
                block = _element_para(child)
                if block:
                    blocks.append(block)
        elif name == "span" and ("display:table-row" in style or "display:table-cell" in style):
            # 完形填空用 span 撑出表格行，本质是一行“小题号 + 选项”
            flush()
            blocks.append(_row_span_block(child))
        elif name == "hr":
            flush()
        elif name == "img":
            _push_img(buf, child)
        elif name == "br":
            _push_text(buf, "\n", {})
        else:
            _collect_inline(child, buf, {})

    flush()
    return blocks


def _element_para(el: Tag) -> dict[str, Any] | None:
    buf: list[dict[str, Any]] = []
    for child in el.children:
        if isinstance(child, NavigableString):
            _push_text(buf, _node_text(str(child)), {})
        elif isinstance(child, Tag):
            if child.name == "br":
                _push_text(buf, "\n", {})
            elif child.name == "img":
                _push_img(buf, child)
            elif child.name == "table":
                # 极少见：段落里嵌表格，退化成占位说明
                _push_text(buf, " ", {})
            else:
                _collect_inline(child, buf, {})
    runs = _trim_runs(buf)
    if not runs:
        return None
    style = _style(el)
    align = None
    if "text-align:center" in style:
        align = "center"
    elif "text-align:right" in style:
        align = "right"
    return {
        "type": "para",
        "runs": runs,
        "align": align,
        "indent": "text-indent" in style,
    }


def _collect_inline(el: Tag, buf: list[dict[str, Any]], fmt: dict[str, bool]) -> None:
    """把行内元素（b/i/u/span/br/bk...）展开成 run 序列。

    格式标记沿着递归往下传，``<u><bk/></u>`` 这种嵌套才能正确叠加。
    """
    name = el.name
    local = dict(fmt)

    if name in ("b", "strong"):
        local["b"] = True
    elif name in ("i", "em"):
        local["i"] = True
    elif name == "u":
        local["u"] = True
    elif name == "sup":
        local["sup"] = True
    elif name == "sub":
        local["sub"] = True
    elif name == "bk":
        # 组卷网用 <bk><u>&nbsp;1&nbsp;</u></bk> 表示填空，本质是下划线空格
        local["u"] = True
    elif name == "br":
        _push_text(buf, "\n", local)
        return
    elif name == "img":
        _push_img(buf, el)
        return
    elif name in ("script", "style"):
        return
    else:
        style = _style(el)
        if "underline" in style or "text-decoration:underline" in style:
            local["u"] = True
        if "font-weight:bold" in style or "font-weight:700" in style:
            local["b"] = True
        if "font-style:italic" in style:
            local["i"] = True

    for child in el.children:
        if isinstance(child, NavigableString):
            _push_text(buf, _node_text(str(child)), local)
        elif isinstance(child, Tag):
            _collect_inline(child, buf, local)


def _table_block(tbl: Tag) -> dict[str, Any]:
    rows: list[list[list[dict[str, Any]]]] = []
    for tr in _direct_rows(tbl):
        cells: list[list[dict[str, Any]]] = []
        for td in tr.find_all(["td", "th"], recursive=False):
            cells.append(extract_blocks(td))
        if cells:
            rows.append(cells)
    # 选项表在网页上不显示边框，靠 name 属性区分
    options = (tbl.get("name") or "") == "optionsTable"
    cols = max((len(r) for r in rows), default=1)
    return {
        "type": "grid",
        "rows": rows,
        "options": options,
        "borders": not options,
        "cols": cols,
    }


def _row_span_block(span: Tag) -> dict[str, Any]:
    """处理 ``<span style="display:table-row">`` 这种“小题号 + 选项表”的伪表格行。"""
    cells: list[list[dict[str, Any]]] = []
    extra_rows: list[list[list[dict[str, Any]]]] = []

    for child in span.children:
        if isinstance(child, NavigableString):
            buf: list[dict[str, Any]] = []
            _push_text(buf, _node_text(str(child)), {})
            runs = _trim_runs(buf)
            if runs:
                cells.append([{"type": "para", "runs": runs, "align": None, "indent": False}])
            continue
        if not isinstance(child, Tag):
            continue
        if child.name == "table":
            table = _table_block(child)
            rows = table["rows"]
            if rows:
                # 选项表的第一行并到“小题号”那一行，多行的话首列留空对齐
                cells.extend(rows[0])
                for row in rows[1:]:
                    extra_rows.append([[]] + row)
            continue
        if child.name in BLOCK_TAGS:
            cells.append(extract_blocks(child))
        else:
            buf = []
            _collect_inline(child, buf, {})
            runs = _trim_runs(buf)
            if runs:
                cells.append([{"type": "para", "runs": runs, "align": None, "indent": False}])

    rows = [cells] + extra_rows if cells else extra_rows
    return {
        "type": "grid",
        "rows": rows,
        "options": True,
        "borders": False,
        "cols": max((len(r) for r in rows), default=1),
    }


def _direct_rows(tbl: Tag) -> list[Tag]:
    """只取本层的 tr，避免把单元格里嵌套的表格行也收进来。"""
    body = tbl.find("tbody")
    holder = body if body is not None else tbl
    return [tr for tr in holder.find_all("tr", recursive=False)]


def _has_block_children(el: Tag) -> bool:
    """判断一个元素里是否还套着块级内容（div 套 p 的情况很常见）。"""
    for child in el.children:
        if not isinstance(child, Tag):
            continue
        if child.name == "table":
            return True
        if child.name in BLOCK_TAGS and child.name != "hr":
            return True
        if child.name == "span":
            style = _style(child)
            if "display:table-row" in style or "display:table-cell" in style:
                return True
    return False


def _push_text(buf: list[dict[str, Any]], text: str, fmt: dict[str, bool]) -> None:
    if not text:
        return

    text = text.replace("\r", " ").replace("\t", " ")
    text = _WS_RE.sub(" ", text)
    marks = {k: fmt[k] for k in _FMT_KEYS if fmt.get(k)}

    # 纯空白：单独的换行要留，连续空格按 HTML 规则压成一个
    if text.strip(" \n") == "":
        if text == "\n":
            _push_run(buf, {"text": "\n", **marks})
            return
        if not buf:
            return
        last = buf[-1]
        if last.get("type") == "img":
            return
        if last.get("text", "")[-1:] in (" ", "\u00a0", "\n"):
            return
        _push_run(buf, {"text": " ", **marks})
        return

    _push_run(buf, {"text": text, **marks})


def _node_text(raw: str) -> str:
    """源码里的换行/缩进是排版噪声，转成空格；真正的换行只来自 <br>。"""
    return raw.replace("\r", " ").replace("\n", " ").replace("\t", " ")


def _push_img(buf: list[dict[str, Any]], img: Tag) -> None:
    info = img_info(img)
    if info:
        buf.append(info)


def _push_run(buf: list[dict[str, Any]], run: dict[str, Any]) -> None:
    """把格式相同、相邻的 run 合并，少生成一堆碎 run。"""
    if not run:
        return
    if buf and run.get("type") != "img" and buf[-1].get("type") != "img":
        last = buf[-1]
        if all(bool(last.get(k)) == bool(run.get(k)) for k in _FMT_KEYS):
            last["text"] = last.get("text", "") + run.get("text", "")
            return
    buf.append(run)


def _trim_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉段首段尾的空格和空 run，Word 里这些会变成多余缩进。"""
    cleaned: list[dict[str, Any]] = []
    for run in runs:
        if run.get("type") == "img":
            cleaned.append(run)
            continue
        text = run.get("text", "")
        if not text:
            continue
        cleaned.append(run)

    while cleaned and cleaned[0].get("type") != "img":
        new_text = cleaned[0].get("text", "").lstrip(" \u00a0\n")
        if new_text:
            cleaned[0]["text"] = new_text
            break
        cleaned.pop(0)

    while cleaned and cleaned[-1].get("type") != "img":
        new_text = cleaned[-1].get("text", "").rstrip(" \u00a0\n")
        if new_text:
            cleaned[-1]["text"] = new_text
            break
        cleaned.pop()

    merged: list[dict[str, Any]] = []
    for run in cleaned:
        _push_run(merged, run)
    return [r for r in merged if r.get("type") == "img" or r.get("text")]


def _style(el: Tag) -> str:
    return (el.get("style") or "").replace(" ", "").lower()


def img_info(img: Tag) -> dict[str, Any] | None:
    """把 <img> 转成 run，顺便拆出原图地址和网页上的展示宽度。

    组卷网用小图地址（?resizew=136）做占位，去掉参数才是原图，
    所以 src 去掉缩放参数留原图，宽度单独记下来给 Word 排版用。
    """
    src = img.get("src") or img.get("data-src") or img.get("data-original")
    if not src:
        return None
    if src.startswith("//"):
        src = "https:" + src
    elif src.startswith("/"):
        src = "https://zujuan.xkw.com" + src

    width = None
    parts = urlsplit(src)
    if parts.query:
        query = parse_qsl(parts.query, keep_blank_values=True)
        for key, value in query:
            if key.lower() in ("resizew", "width", "w"):
                try:
                    width = int(float(value))
                except ValueError:
                    pass
        query = [(k, v) for k, v in query if k.lower() not in ("resizew", "width", "w")]
        full = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    else:
        full = src

    if width is None:
        raw = (img.get("width") or "").strip()
        match = re.match(r"(\d+)", raw)
        if match:
            width = int(match.group(1))

    return {"type": "img", "src": full, "display_src": src, "width": width}


def plain_text(blocks: Iterable[dict[str, Any]]) -> str:
    """把块序列还原成纯文本，给 CSV 和检索用。

    表格按行拼、单元格用制表符分隔，多列选项不会挤成一行。
    """
    out: list[str] = []

    def handle(items: Iterable[dict[str, Any]], depth: int = 0) -> None:
        for block in items:
            if block.get("type") == "para":
                text = "".join(
                    run.get("text", "") if run.get("type") != "img" else "[图片]"
                    for run in block.get("runs", [])
                )
                if text.strip():
                    out.append(text.strip())
            elif block.get("type") == "grid":
                for row in block.get("rows", []):
                    cells = []
                    for cell in row:
                        # 先把单元格内容写进同一个列表，再切出来拼这一行
                        before = len(out)
                        handle(cell, depth + 1)
                        cells.append(" ".join(out[before:]))
                        del out[before:]
                    line = "\t".join(c for c in cells if c)
                    if line.strip():
                        out.append(line)

    handle(blocks)
    return "\n".join(out)
