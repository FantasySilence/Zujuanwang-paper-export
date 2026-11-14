# ============================================================= #
# @Author: Fantasy_Silence                                      #
# @Time: 2026-11-12                                             #
# @IDE: Visual Studio Code & PyCharm                            #
# @Python: 3.9.7                                                #
# ============================================================= #
# @Description: 单份试卷的导出流程：抓取子进程 → 生成 Word         #
# ============================================================= #

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from zujuan import paths, status
from zujuan.docx_writer import DocxOptions, build_document, resolve_filename
from zujuan.extractor import normalize_paper_url, parse_paper_id
from zujuan.images import ImageCache

from .console import SPINNER, ask_yes, is_interactive, open_file


def export_paper(
    raw_url: str,
    *,
    answers: bool = False,
    answers_limit: int = 0,
    no_cache: bool = False,
    auto_open: bool | None = None,
    name: str = "",
) -> bool:
    """导出单份试卷，成功返回 True。"""
    try:
        url = normalize_paper_url(raw_url)
    except ValueError as exc:
        print(f"\n  [X]  {exc}")
        return False

    paper_id = parse_paper_id(url)
    print(f"\n  目标试卷：{paper_id}")
    print(f"  {url}")

    # ------ 先清掉上次的结果，抓完读到的就一定是这次的 ------ #
    status.clear()
    # ------ 交给爬虫的是用户的原始输入：只给了数字时它才能依次去 3p / 个人题库 / 2p 试 ------ #
    code, _out, err = run_spider(raw_url, answers=answers, answers_limit=answers_limit, no_cache=no_cache)
    result = status.read()

    if code != 0 or not result.get("ok"):
        message = result.get("error") or (err or "").strip() or "抓取失败"
        print(f"\n  [X]  {message}")
        print("      详细日志：.temp/logs/scrapy.log")
        return False

    print(f"  [OK] 抓取完成：{result.get('section_count')} 个题型 / {result.get('question_count')} 道题"
          + (f"（答案解析 {result.get('answer_count')} 张）" if result.get("answer_count") else ""))

    resolved_id = result.get("paper_id") or paper_id
    # ------ 只给了数字时可能换了题库地址，得告诉用户最后打开的是哪一份 ------ #
    if resolved_id != paper_id:
        print(f"  [提示] 这份试卷在另一个题库：{resolved_id}（原按 {paper_id} 找不到）")

    # ------ 编号以爬虫最后真正打开的那份为准（只给数字时可能换了题库地址） ------ #
    json_path = paths.paper_json_path(result.get("paper_id") or paper_id)
    if not json_path.exists():
        print(f"\n  [X]  没有找到解析结果：{json_path}")
        return False

    docx_path = build_docx(json_path, name=name)
    if docx_path is None:
        return False

    if auto_open is False:
        return True
    if ask_yes("现在打开 Word 文档吗", default=is_interactive()):
        open_file(docx_path)
    return True


def run_spider(
    url: str,
    *,
    answers: bool,
    answers_limit: int = 0,
    no_cache: bool = False,
) -> tuple[int, str, str]:
    """起一个子进程跑爬虫，返回 (退出码, stdout, stderr)。"""
    cmd = [sys.executable, "-m", "zujuan.run_spider", "--url", url]
    if answers:
        cmd.append("--answers")
        if answers_limit > 0:
            cmd.extend(["--answers-limit", str(answers_limit)])
    if no_cache:
        cmd.append("--no-cache")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    print(f"\n  正在抓取{'（含答案解析，需逐题展开，请稍候）' if answers else ''}…")
    try:
        # ------ 独立进程跑爬虫，reactor 用完即退，不影响下一次导出 ------ #
        proc = subprocess.Popen(
            cmd,
            cwd=str(paths.BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except OSError as exc:
        return 1, "", f"无法启动抓取进程：{exc}"

    index = 0
    started = time.time()
    # ------ 爬虫日志都写进文件了，这里只转个圈，避免窗口看起来像卡死 ------ #
    animate = is_interactive()
    while proc.poll() is None:
        elapsed = time.time() - started
        if animate:
            print(f"\r    {SPINNER[index % len(SPINNER)]} 已用 {elapsed:4.1f}s   ", end="", flush=True)
        index += 1
        time.sleep(0.15)

    out, err = proc.communicate()
    if animate:
        print("\r" + " " * 32 + "\r", end="")
    else:
        print(f"    用时 {time.time() - started:.1f}s")
    return proc.returncode or 0, out or "", err or ""


def build_docx(json_path: Path, name: str = "") -> Path | None:
    
    """
    用缓存里的解析结果生成 Word。
    name 为空时按试卷原标题命名，填了就用用户的名字。
    """
    
    try:
        paper = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"\n  [X]  读取解析结果失败：{exc}")
        return None

    # ------ 抓过答案才附“参考答案”附录，否则只会得到一串空标题 ------ #
    total_answers = sum(
        len(question.get("answer_images") or [])
        for section in paper.get("sections", [])
        for question in section.get("questions", [])
    )

    options = DocxOptions(include_answers=total_answers > 0)

    target = paths.OUTPUT_DIR / resolve_filename(paper, name)
    # ------ 同名文件先问一句，免得辛苦导出的旧文件被悄悄覆盖 ------ #
    if target.exists() and is_interactive() and not ask_yes(f"{target.name} 已存在，覆盖吗", default=True):
        target = target.with_name(f"{target.stem}_{datetime.now():%Y%m%d_%H%M%S}.docx")

    print("  正在生成 Word（首次会下载题目图片）…")
    cache = ImageCache()
    try:
        path = build_document(paper, target, options=options, image_cache=cache)
    except PermissionError:
        # ------ 目标文件正被 Word 打开时会占用，换个带时间戳的文件名重试 ------ #
        fallback = target.with_name(f"{target.stem}_{datetime.now():%Y%m%d_%H%M%S}.docx")
        try:
            path = build_document(paper, fallback, options=options, image_cache=cache)
            print("  原文件正被占用（可能已在 Word 中打开），已另存为新文件。")
        except Exception as exc:  # noqa: BLE001
            print(f"\n  [X]  生成 Word 失败：{exc}")
            return None
    except Exception as exc:  # noqa: BLE001 - 生成失败要给用户一个明确提示
        print(f"\n  [X]  生成 Word 失败：{exc}")
        return None

    stats = cache.stats()
    print(f"  [OK] 已生成：{path}")
    size_mb = path.stat().st_size / 1024 / 1024
    print(f"       大小 {size_mb:.2f} MB · 图片 {len(paper_images(paper))} 张"
          f"（新下载 {stats['downloaded']} / 缓存命中 {stats['cached']}"
          + (f" / 失败 {stats['failed']}" if stats["failed"] else "") + "）")
    return path


def paper_images(paper: dict[str, Any]) -> list[dict[str, Any]]:
    """把一份试卷里所有题目图片摊平，用于统计张数。"""
    images = []
    for section in paper.get("sections", []):
        for question in section.get("questions", []):
            images.extend(question.get("images") or [])
    return images
