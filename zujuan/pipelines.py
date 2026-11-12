# ======================================================================== #
# @Author: Fantasy_Silence                                                 #
# @Time: 2026-11-12                                                        #
# @IDE: Visual Studio Code & PyCharm                                       #
# @Python: 3.9.7                                                           #
# ======================================================================== #
# @Description: Scrapy 管道：把解析结果落盘，供 Word 生成与后续分析复用。      #
# ======================================================================== #
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem

from . import paths
from .extractor import plain_text

logger = logging.getLogger(__name__)


class PaperJsonPipeline:
    """把每份试卷写成 JSON（完整结构）和 CSV（一道题一行，便于分析）。"""

    CSV_FIELDS = [
        "paper_id",
        "paper_title",
        "section_index",
        "section_title",
        "question_index",
        "question_id",
        "question_code",
        "type_label",
        "child_type",
        "difficulty",
        "difficulty_score",
        "knowledge",
        "tags",
        "source",
        "overview",
        "text",
    ]

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or paths.DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.saved: list[Path] = []

    @classmethod
    def from_crawler(cls, crawler: Any) -> "PaperJsonPipeline":
        return cls()

    def process_item(self, item: Any, spider: Any = None) -> Any:
        adapter = ItemAdapter(item)
        payload = adapter.get("payload")
        if not payload:
            raise DropItem("payload 为空，无法保存")

        paper_id = payload.get("paper_id") or adapter.get("paper_id") or "unknown"
        payload.setdefault("fetched_at", adapter.get("fetched_at")
                           or datetime.now().isoformat(timespec="seconds"))

        target = self.data_dir / f"{paper_id}.paper.json"
        # 先写临时文件再改名，中途出错不会留下半截 JSON
        tmp = target.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        tmp.replace(target)

        # CSV 是为了直接扔进 Excel / pandas，写失败不影响主流程
        csv_path = self.data_dir / f"{paper_id}.questions.csv"
        try:
            self._write_csv(csv_path, payload)
        except OSError:
            logger.warning("[pipeline] 写 CSV 失败：%s", csv_path, exc_info=True)

        self.saved.append(target)
        stats = payload.get("stats") or {}
        logger.info(
            "[pipeline] 已保存 %s（%s 个题型 / %s 道题）",
            target.name,
            stats.get("section_count"),
            stats.get("question_count"),
        )
        return item

    def _write_csv(self, path: Path, payload: dict[str, Any]) -> None:
        title = payload.get("title", "")
        paper_id = payload.get("paper_id", "")
        tmp = path.with_suffix(".csv.tmp")
        # utf-8-sig 带 BOM，Excel 双击打开中文才不乱码
        with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.CSV_FIELDS)
            writer.writeheader()
            for section in payload.get("sections", []):
                for question in section.get("questions", []):
                    # 一道题一行；知识点和标签是列表，用竖线拼平
                    writer.writerow({
                        "paper_id": paper_id,
                        "paper_title": title,
                        "section_index": section.get("index", ""),
                        "section_title": section.get("title", ""),
                        "question_index": question.get("index", ""),
                        "question_id": question.get("id", ""),
                        "question_code": question.get("code", ""),
                        "type_label": question.get("type_label", ""),
                        "child_type": question.get("child_type", ""),
                        "difficulty": question.get("difficulty", ""),
                        "difficulty_score": question.get("difficulty_score", ""),
                        "knowledge": "|".join(question.get("knowledge") or []),
                        "tags": "|".join(question.get("tags") or []),
                        "source": question.get("source", ""),
                        "overview": question.get("overview", ""),
                        "text": plain_text(question.get("blocks") or []),
                    })
        tmp.replace(path)
