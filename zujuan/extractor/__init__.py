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

模块分工（对外只用从这个包根 import）::

    urls.py       网址与试卷编号：2p / 3p / 4p / 5p 是不同题库，前缀要原样保留
    blocks.py     题面 HTML → 段落 / 表格 / 图片混排的 block 列表
    questions.py  按题型分节、逐题抽取题号 / 难度 / 图片
    meta.py       标题、地区年级、页内 paperJson、试卷分析表
"""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from .blocks import extract_blocks, plain_text
from .meta import page_title, parse_analysis, parse_meta, parse_paper_json
from .questions import parse_sections
from .urls import normalize_paper_url, parse_paper_id, plan_urls, usertk_url

__all__ = [
    "parse_paper",
    "parse_paper_id",
    "normalize_paper_url",
    "plan_urls",
    "usertk_url",
    "extract_blocks",
    "plain_text",
]


def parse_paper(html: str, url: str) -> dict[str, Any]:
    """解析试卷详情页 HTML。"""
    soup = BeautifulSoup(html, "lxml")
    pj = parse_paper_json(html)

    paper_id = parse_paper_id(url)
    meta = parse_meta(soup)
    sections = parse_sections(soup, pj)
    analysis = parse_analysis(soup, pj)

    title = meta.pop("title", "") or page_title(soup)

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
