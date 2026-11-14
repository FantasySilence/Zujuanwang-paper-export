# =========================================================== #
# @Author: Fantasy_Silence                                    #
# @Time: 2026-11-12                                           #
# @IDE: Visual Studio Code & PyCharm                          #
# @Python: 3.9.7                                              #
# =========================================================== #
# @Description: 题目与题型分节：按文档流把题目归到题型下，并补上题号、难度、图片。
# =========================================================== #
from __future__ import annotations

import re
from typing import Any, Iterable

from bs4 import BeautifulSoup, Tag

from .blocks import extract_blocks, img_info


def parse_sections(soup: BeautifulSoup, paper_json: dict[str, Any]) -> list[dict[str, Any]]:
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
        info = img_info(img)
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


def _parse_difficulty_score(text: str) -> float | None:
    match = re.search(r"\((\d+(?:\.\d+)?)\)", text or "")
    return float(match.group(1)) if match else None
