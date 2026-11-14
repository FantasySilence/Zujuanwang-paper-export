# =========================================================== #
# @Author: Fantasy_Silence                                    #
# @Time: 2026-11-12                                           #
# @IDE: Visual Studio Code & PyCharm                          #
# @Python: 3.9.7                                              #
# =========================================================== #
# @Description: 试卷元信息：标题、地区年级、难度、页面内联 paperJson 与分析表。
# =========================================================== #
from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup


def page_title(soup: BeautifulSoup) -> str:
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


def parse_meta(soup: BeautifulSoup) -> dict[str, Any]:
    meta: dict[str, Any] = {}

    # 普通试卷和自组试卷的标题层级不同，统一交给 page_title 处理
    title = page_title(soup)
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


def parse_analysis(soup: BeautifulSoup, paper_json: dict[str, Any]) -> dict[str, Any]:
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
