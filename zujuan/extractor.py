# =========================================================== #
# @Author: Fantasy_Silence                                    #
# @Time: 2026-11-12                                           #
# @IDE: Visual Studio Code & PyCharm                          #
# @Python: 3.9.7                                              #
# =========================================================== #
# @Description: 把组卷网试卷详情页的 HTML 解析成结构化数据        #
# =========================================================== #
"""
产出是一个可直接 `json.dumps` 的字典（不依赖 Scrapy / Playwright），
方便离线复用到数据分析或再次生成 Word。

结构概览::

    {
      "paper_id": "3p2856667",
      "url": "...",
      "title": "...",
      "meta": {"province": "四川", "grade": "九年级", ...},
      "paper_json": {...},                 # 页面内联的 paperJson 元数据
      "sections": [
        {"index": 1, "title": "一、选词填空", "type_id": "1210",
         "questions": [
            {"id": "29530562", "code": "1-5", "type_label": "选词填空-短文",
             "difficulty": "适中 (0.65)", "difficulty_score": 0.65,
             "tags": ["名校"], "source": "...", "overview": "文章大意：...",
             "knowledge": ["中华文化", "游戏"],
             "blocks": [ <block>, ... ],       # 题面正文
             "images": [{"src": ..., "width": 136}],
             "answer_images": [{"src": ..., "width": 884}],
             "info": {"date": "...", "downloads": "117次下载"}}
         ]}
      ],
      "analysis": {"difficulty": "适中", "scope": "...", "type_counts": [...],
                   "knowledge": [...], "detail_table": [...],
                   "difficulty_list": [...]}
    }

block 只有三种::

    {"type": "para", "runs": [run, ...], "align": null|"center", "indent": false}
    {"type": "grid", "rows": [[ [block, ...], ...], ...], "options": true|false,
     "borders": true|false, "cols": 3}
    run = {"text": "..."} 或 {"type": "img", "src": "...", "width": 136}
    run 可带 b / i / u / sup / sub 标记。
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup, NavigableString, Tag

__all__ = ["parse_paper", "parse_paper_id", "normalize_paper_url", "extract_blocks", "plain_text"]


# 这些标签在正文里自成一块，其余（b/u/span/br/img…）都当行内元素处理
BLOCK_TAGS = {
    "p", "div", "table", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "ul", "ol", "dl", "dt", "dd", "blockquote", "pre",
    "section", "article", "figure", "figcaption", "hr",
}

# run 上可能带的格式标记
_FMT_KEYS = ("b", "i", "u", "sup", "sub")

_WS_RE = re.compile(r" {2,}")


def parse_paper_id(url: str) -> str:
    """从试卷网址中提取试卷标识，例如 ``3p2856667``。"""
    match = re.search(r"(3p\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"/(\d{5,})\.html", url)
    if match:
        return f"3p{match.group(1)}"
    raise ValueError(f"无法从网址中识别试卷编号: {url}")


def normalize_paper_url(raw: str) -> str:
    """把用户输入（网址 / 试卷编号 / 带杂物的一整行）规范成试卷详情页网址。

    支持的输入::

        https://zujuan.xkw.com/3p2856667.html          普通试卷
        https://zujuan.xkw.com/usertk/3p129898802.html 自己组的试卷（个人题库）
        https://zujuan.xkw.com/3p2856667.html?from=xx#comments
        3p2856667
        2856667
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("试卷网址为空")

    match = re.search(r"https?://[^\s]+", text)
    if match:
        url = match.group(0).split("?", 1)[0].split("#", 1)[0]
        if "zujuan.xkw.com" not in url:
            raise ValueError("目前只支持组卷网（zujuan.xkw.com）的试卷网址")
        if re.fullmatch(r"https?://zujuan\.xkw\.com/\d+\.html", url):
            url = re.sub(r"/(\d+)\.html$", r"/3p\1.html", url)
        # 自组试卷挂在 /usertk/ 下，路径不同但编号规则一样
        if not re.fullmatch(r"https?://zujuan\.xkw\.com/(?:usertk/)?3p\d+\.html", url):
            raise ValueError(
                "看起来不是试卷详情页网址，示例："
                "https://zujuan.xkw.com/3p2856667.html 或 https://zujuan.xkw.com/usertk/3p129898802.html"
            )
        return url

    # 只给编号时先按普通试卷打开，抓不到题目会自动换成 /usertk/ 再试一次
    if re.fullmatch(r"3p\d+", text):
        return f"https://zujuan.xkw.com/{text}.html"
    if re.fullmatch(r"\d{5,}", text):
        return f"https://zujuan.xkw.com/3p{text}.html"
    raise ValueError("无法识别的试卷网址，请粘贴形如 https://zujuan.xkw.com/3p2856667.html 的链接")


def usertk_url(paper_id: str) -> str:
    """同一份试卷在“个人题库”里的地址。"""
    return f"https://zujuan.xkw.com/usertk/{paper_id}.html"


def _page_title(soup: BeautifulSoup) -> str:
    """取试卷标题。

    普通试卷是 ``.title-txt > span.txt``，自组试卷直接是 ``span.title-txt``；
    两者都没有时才退回 <title>，但要排掉“个人题库”这类站点标题。
    """
    for selector in ("h2.exam-title .title-txt .txt", "h2.exam-title .title-txt"):
        element = soup.select_one(selector)
        if element is not None:
            text = element.get_text(" ", strip=True)
            if text:
                return text
    if soup.title is not None:
        text = soup.title.get_text(strip=True)
        if text and text not in _GENERIC_TITLES:
            return text
    return ""


_GENERIC_TITLES = {
    "个人题库",
    "组卷网",
    "当前请求资源不存在",
    "学科网-让教与学更高效",
}



def parse_paper(html: str, url: str) -> dict[str, Any]:
    """解析试卷详情页 HTML。"""
    soup = BeautifulSoup(html, "lxml")
    pj = parse_paper_json(html)

    paper_id = parse_paper_id(url)
    meta = _parse_meta(soup)
    sections = _parse_sections(soup, pj)
    analysis = _parse_analysis(soup, pj)

    title = meta.pop("title", "") or _page_title(soup)

    return {
        "paper_id": paper_id,
        "url": url,
        "title": title,
        "meta": meta,
        "paper_json": pj,
        "sections": sections,
        "analysis": analysis,
        "stats": {
            "section_count": len(sections),
            "question_count": sum(len(s["questions"]) for s in sections),
        },
    }


def parse_paper_json(html: str) -> dict[str, Any]:
    """提取页面内联的 ``paperJson``（题型/题号/难度/知识点标签等）。

    它是拼在 script 里的 JSON 字面量，用 JSONDecoder 从 "=" 后面整段解出来最稳，
    正则截取遇到字符串里的括号就会断。
    """
    marker = "var paperJson"
    idx = html.find(marker)
    if idx < 0:
        return {}
    idx = html.find("=", idx)
    if idx < 0:
        return {}
    idx += 1
    while idx < len(html) and html[idx] in " \t\r\n":
        idx += 1
    try:
        data, _end = json.JSONDecoder().raw_decode(html, idx)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_meta(soup: BeautifulSoup) -> dict[str, Any]:
    meta: dict[str, Any] = {}

    # 普通试卷和自组试卷的标题层级不同，统一交给 _page_title 处理
    title = _page_title(soup)
    if title:
        meta["title"] = title

    # 信息栏前几项是纯值，后面是“标签：值”，混在一起只能按顺序拆
    plain: list[str] = []
    for item in soup.select("h2.exam-title .info-list .item"):
        text = item.get_text(" ", strip=True)
        if not text:
            continue
        plain.append(text)

    labels = {"整体难度": "difficulty", "考查范围": "scope"}
    for text in plain:
        matched = False
        for key, field in labels.items():
            if text.startswith(key):
                value = text[len(key):].lstrip("：: ").strip()
                meta[field] = value
                matched = True
                break
        if not matched:
            meta.setdefault("_info", []).append(text)

    info = meta.pop("_info", [])
    for i, field in enumerate(("province", "grade", "exam_type", "date", "views")):
        if i < len(info):
            meta[field] = info[i]
    if len(info) > 5:
        meta["extra_info"] = info[5:]

    # 收藏按钮上挂着试卷原始编号、权限等级、题目数
    fav = soup.select_one(".collectpaper")
    if fav:
        if fav.get("data-paperid"):
            meta["raw_paper_id"] = fav.get("data-paperid")
        if fav.get("data-paperlevel"):
            meta["paper_level"] = fav.get("data-paperlevel")
        if fav.get("data-quescount"):
            meta["question_count"] = _to_int(fav.get("data-quescount"))

    for hid in ("can_view_paper_all", "status"):
        el = soup.select_one(f"#{hid}")
        if el is not None:
            meta[hid] = el.get("value")

    if soup.select_one(".exam-item__opt .item.no-login"):
        meta["need_login"] = True

    return meta


def _parse_sections(soup: BeautifulSoup, paper_json: dict[str, Any]) -> list[dict[str, Any]]:
    """按文档顺序遍历 ``h4.sec-title`` / ``div.sec-list``，题目归属紧随其后的标题。

    页面上所有题型标题和题目列表其实是同一层的兄弟节点（不是嵌套），
    所以只能顺着文档流往下走，遇到标题就换节、遇到列表就往当前节里塞题。
    """
    type_names = {
        str(t.get("id")): t.get("name", "")
        for t in paper_json.get("quesTypes", []) or []
        if t.get("id") is not None
    }
    ques_info = _question_index(paper_json)

    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    counters: dict[str, int] = {}

    for node in soup.select("section.exam-list h4.sec-title, section.exam-list div.sec-list"):
        if node.name == "h4":
            heading = node.select_one("span")
            title = heading.get_text(" ", strip=True) if heading else node.get_text(" ", strip=True)
            title = re.sub(r"\s*添加题型下试题\s*$", "", title).strip()
            link = node.select_one(".add-sec-ques")
            type_id = link.get("qtid") if link else None
            current = {
                "index": len(sections) + 1,
                "title": title,
                "type_id": type_id,
                "type_name": type_names.get(str(type_id), "") if type_id else "",
                "questions": [],
            }
            sections.append(current)
            continue

        if current is None:
            current = {"index": len(sections) + 1, "title": "", "type_id": None,
                       "type_name": "", "questions": []}
            sections.append(current)

        for item in node.select("div.tk-quest-item.quesroot"):
            key = f"{current['index']}"
            counters[key] = counters.get(key, 0) + 1
            current["questions"].append(_parse_question(item, ques_info, counters[key]))

    return [s for s in sections if s["questions"] or s["title"]]


def _question_index(paper_json: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """questionid -> 题号范围 / 难度系数 / 知识点标签。"""
    index: dict[str, dict[str, Any]] = {}
    for qtype in paper_json.get("quesTypes", []) or []:
        for q in qtype.get("quesList", []) or []:
            qid = str(q.get("id"))
            index[qid] = {
                "code": q.get("quesCode"),
                "difficulty_score": q.get("quesDiff"),
                "category": q.get("category") or [],
                "child_type": q.get("ChildTypeName") or "",
                "child_num": q.get("quesChildNum"),
                "type_name": qtype.get("name", ""),
            }
    return index


def _parse_question(item: Tag, ques_index: dict[str, dict[str, Any]], local_index: int) -> dict[str, Any]:
    qid = item.get("questionid") or ""
    extra = ques_index.get(str(qid), {})

    # 信息栏前两条顺序固定：先“题型-小题型”，再“难度 (系数)”
    type_label = ""
    difficulty = ""
    for info in item.select(".ques-additional .msg-box .left-msg .addi-info .info-cnt"):
        text = info.get_text(" ", strip=True)
        if not text:
            continue
        if not type_label:
            type_label = text
        elif not difficulty:
            difficulty = text
    diff_score = _parse_difficulty_score(difficulty)
    # 页面上没印系数时退回 paperJson 里的 quesDiff
    if diff_score is None:
        diff_score = extra.get("difficulty_score")

    tags = [t.get_text(strip=True) for t in item.select(".msg-box .right-msg .tag")]
    source_el = item.select_one(".top-msg .ques-src")
    overview_el = item.select_one(".art-overview")
    content_el = item.select_one(".exam-item__cnt")

    blocks = extract_blocks(content_el) if content_el is not None else []
    knowledge = [k.get_text(strip=True) for k in item.select(".exam-item__opt .item.knowlegde .knowledge-name")]

    # 只有点了“显示答案”才会有图，默认这里是空的
    answer_images = []
    for img in item.select(".exam-item__opt .item.answer img"):
        info = _img_info(img)
        if info:
            answer_images.append(info)

    # 底部信息栏：日期 | 下载次数 | 来源，除了日期都按关键字认
    info_msgs = item.select_one(".exam-item__info .info-msgs")
    info: dict[str, Any] = {}
    if info_msgs is not None:
        spans = info_msgs.find_all("span")
        texts = [s.get_text(" ", strip=True) for s in spans if s.get_text(" ", strip=True)]
        if texts:
            info["date"] = texts[0]
        for text in texts[1:]:
            if "下载" in text:
                info["downloads"] = text
            else:
                info.setdefault("extra", []).append(text)

    return {
        "index": local_index,
        "id": qid,
        "code": extra.get("code") or "",
        "type_label": type_label or extra.get("type_name", ""),
        "child_type": extra.get("child_type", ""),
        "difficulty": difficulty,
        "difficulty_score": diff_score,
        "tags": tags,
        "source": source_el.get_text(" ", strip=True) if source_el else "",
        "overview": overview_el.get_text(" ", strip=True) if overview_el else "",
        "knowledge": knowledge or list(extra.get("category") or []),
        "blocks": blocks,
        "images": [img for img in _collect_images(blocks)],
        "answer_images": answer_images,
        "info": info,
    }


def _collect_images(blocks: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for block in blocks:
        if block.get("type") == "para":
            for run in block.get("runs", []):
                if run.get("type") == "img":
                    found.append({"src": run["src"], "width": run.get("width")})
        elif block.get("type") == "grid":
            for row in block.get("rows", []):
                for cell in row:
                    found.extend(_collect_images(cell))
    return found


def _parse_analysis(soup: BeautifulSoup, paper_json: dict[str, Any]) -> dict[str, Any]:
    analysis: dict[str, Any] = {}

    for div in soup.select("section.exam-analyze .info-box > div"):
        text = div.get_text(" ", strip=True)
        for key, field in (("整体难度", "difficulty"), ("考查范围", "scope")):
            if text.startswith(key):
                analysis[field] = text[len(key):].lstrip("：: ").strip()

    # 试卷分析区里的“题型 / 数量”表格
    type_counts = []
    for row in soup.select("section.exam-analyze .ques-type-count .sec-item__tr"):
        cells = [c.get_text(strip=True) for c in row.select(".sec-item__td")]
        if len(cells) >= 2 and cells[0]:
            type_counts.append({"name": cells[0], "count": _to_int(cells[1])})
    analysis["type_counts"] = type_counts

    # 知识点分析：一个知识点对应一串题号链接
    knowledge = []
    for row in soup.select("section.exam-analyze .analyze-knowledge .sec-item__tr"):
        cells = row.select(".sec-item__td")
        if len(cells) < 3:
            continue
        links = [
            {"code": a.get_text(strip=True), "question_id": a.get("data-ques-id")}
            for a in cells[2].select("a.ques-item")
        ]
        knowledge.append({
            "no": _to_int(cells[0].get_text(strip=True)),
            "name": cells[1].get_text(strip=True),
            "questions": links,
        })
    analysis["knowledge"] = knowledge

    # 细目表：题型分组行用 td.ques-type（colspan 4），其余行是 4 列数据
    detail: list[dict[str, Any]] = []
    for row in soup.select("section.exam-analyze .basic-analyze table tbody tr"):
        type_cell = row.select_one("td.ques-type")
        if type_cell is not None:
            detail.append({"group": type_cell.get_text(" ", strip=True)})
            continue
        cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
        if len(cells) >= 3:
            detail.append({
                "no": cells[0],
                "difficulty_score": _to_float(cells[1]),
                # 知识点之间用 nbsp 分隔，不能按普通空格切
                "knowledge": [k for k in re.split(r"[\s\u00a0]+", cells[2]) if k],
                "remark": cells[3] if len(cells) > 3 else "",
            })
    analysis["detail"] = detail

    # 难度分布这些只有 paperJson 里有，页面上是图表
    analysis["difficulty_list"] = paper_json.get("paperDiffList") or []
    if paper_json.get("paperTitle"):
        analysis.setdefault("title", paper_json["paperTitle"])
    if paper_json.get("totalScore") is not None:
        analysis["total_score"] = paper_json["totalScore"]
    analysis["question_way"] = paper_json.get("questionWay", "")

    return analysis


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
    info = _img_info(img)
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


def _img_info(img: Tag) -> dict[str, Any] | None:
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


def _parse_difficulty_score(text: str) -> float | None:
    match = re.search(r"\((\d+(?:\.\d+)?)\)", text or "")
    return float(match.group(1)) if match else None


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


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
