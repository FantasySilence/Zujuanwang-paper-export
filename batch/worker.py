# ======================================================================  #
# @Author: Fantasy_Silence                                                #
# @Time: 2026-11-12                                                       #
# @IDE: Visual Studio Code & PyCharm                                      #
# @Python: 3.9.7                                                          #
# ======================================================================  #
# @Description: 单份试卷的处理：抓取子进程 → 读状态 → 生成 Word           #
# ======================================================================  #

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from zujuan import paths
from zujuan.docx_writer import DocxOptions, build_document, resolve_filename
from zujuan.extractor import normalize_paper_url, parse_paper_id
from zujuan.images import ImageCache

from .models import BatchContext, BatchResult

# batch/ 的上一层就是项目根目录，子进程要用它当工作目录
ROOT = Path(__file__).resolve().parents[1]


def run_one(raw: str, context: BatchContext) -> BatchResult:
    """处理一份试卷：归一化网址 → 抓取 → 生成 Word，全程不抛异常。"""
    started = time.perf_counter()
    result = BatchResult(url=raw)
    try:
        url = normalize_paper_url(raw)
    except ValueError as exc:
        result.error = str(exc)
        result.elapsed = time.perf_counter() - started
        return result

    paper_id = parse_paper_id(url)
    result.paper_id = paper_id
    result.url = url

    code, out, err = run_spider(url, paper_id, context)
    status = read_json(status_path(paper_id))
    if code != 0 or not status.get("ok"):
        result.error = status.get("error") or (err or out or "").strip() or "抓取失败"
        result.elapsed = time.perf_counter() - started
        return result

    result.title = status.get("title", "")
    result.question_count = int(status.get("question_count") or 0)
    result.answer_count = int(status.get("answer_count") or 0)

    json_path = paths.paper_json_path(paper_id)
    if not json_path.exists():
        result.error = f"没有找到解析结果：{json_path}"
        result.elapsed = time.perf_counter() - started
        return result

    try:
        result.docx_path = build_docx(json_path, raw, url, paper_id, context)
        result.ok = True
    except Exception as exc:  # noqa: BLE001 - 生成失败也只影响这一份
        result.error = f"生成 Word 失败：{type(exc).__name__}: {exc}"
    result.elapsed = time.perf_counter() - started
    return result


def run_spider(url: str, paper_id: str, context: BatchContext) -> tuple[int, str, str]:
    """起子进程抓一份试卷，返回 (退出码, stdout, stderr)。"""
    cmd = [
        sys.executable, "-m", "zujuan.run_spider",
        "--url", url,
        # ------ 每份试卷各写一份状态和日志，workers>1 时不至于互相覆盖 ------ #
        "--status-file", str(status_path(paper_id)),
        "--log-file", str(log_path(paper_id)),
    ]
    if context.answers:
        cmd.append("--answers")
        if context.answers_limit > 0:
            cmd.extend(["--answers-limit", str(context.answers_limit)])
    if context.no_cache:
        cmd.append("--no-cache")

    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return proc.returncode or 0, proc.stdout or "", proc.stderr or ""


def build_docx(
    json_path: Path,
    raw: str,
    url: str,
    paper_id: str,
    context: BatchContext,
) -> Path:
    """用解析结果生成 Word；同批重名的自动加 _2/_3。"""
    paper = json.loads(json_path.read_text(encoding="utf-8"))
    answers = sum(
        len(question.get("answer_images") or [])
        for section in paper.get("sections", [])
        for question in section.get("questions", [])
    )

    custom = context.names.get(paper_id) or context.names.get(url) or context.names.get(raw)
    filename = resolve_filename(paper, custom)

    # ------ 同一批里标题撞车的加 _2/_3；上一轮留下的同名文件则是正常覆盖 ------ #
    with context.lock:
        candidate = filename
        stem, suffix = Path(filename).stem, Path(filename).suffix
        serial = 2
        while candidate.lower() in context.used_names:
            candidate = f"{stem}_{serial}{suffix}"
            serial += 1
        context.used_names.add(candidate.lower())

    target = context.out_dir / candidate
    return build_document(
        paper,
        target,
        options=DocxOptions(include_answers=answers > 0),
        image_cache=ImageCache(),
    )


def status_path(paper_id: str) -> Path:
    """这份试卷的运行状态文件。"""
    return paths.LOG_DIR / f"batch_{paper_id}.json"


def log_path(paper_id: str) -> Path:
    """这份试卷的 Scrapy 日志文件。"""
    return paths.LOG_DIR / f"batch_{paper_id}.log"


def read_json(path: Path) -> dict[str, Any]:
    """读状态文件；读不到就当没有结果。"""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def format_line(done: int, total: int, result: BatchResult) -> str:
    """把一份结果格式化成一行进度。"""
    head = f"[{done}/{total}]"
    if result.ok:
        name = result.docx_path.name if result.docx_path else "?"
        return (f"{head} OK   {result.paper_id}  {result.question_count}题  "
                f"{result.elapsed:5.1f}s  -> {name}")
    return f"{head} 失败 {result.paper_id or result.url}  {result.elapsed:5.1f}s  {result.error}"
