# ======================================================================  #
# @Author: Fantasy_Silence                                                #
# @Time: 2026-11-12                                                       #
# @IDE: Visual Studio Code & PyCharm                                      #
# @Python: 3.9.7                                                          #
# ======================================================================  #
# @Description: 批量导出组卷网试卷的非交互接口（也支持命令行读文本文件）      #
# ======================================================================  #

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zujuan import paths  # noqa: E402
from zujuan.docx_writer import DocxOptions, build_document, resolve_filename  # noqa: E402
from zujuan.extractor import normalize_paper_url, parse_paper_id  # noqa: E402
from zujuan.images import ImageCache  # noqa: E402

__all__ = ["BatchResult", "batch_export", "load_urls"]


@dataclass
class BatchResult:
    """一份试卷的处理结果。"""

    paper_id: str = ""
    url: str = ""
    ok: bool = False
    title: str = ""
    docx_path: Path | None = None
    question_count: int = 0
    answer_count: int = 0
    error: str = ""
    elapsed: float = 0.0


def batch_export(
    urls: Sequence[str] | str | Path,
    *,
    out_dir: str | Path | None = None,
    answers: bool = False,
    answers_limit: int = 0,
    no_cache: bool = False,
    names: dict[str, str] | None = None,
    workers: int = 1,
    quiet: bool = False,
    on_progress: Callable[[int, int, BatchResult], None] | None = None,
) -> list[BatchResult]:
    
    """
    批量下载试卷并生成 Word，返回每份试卷的结果。

    参数：
        urls        网址列表，或一个文本文件路径（一行一个网址，支持 # 注释），
                    或直接给一整段用换行分隔的文本
        out_dir     输出目录，默认 output/
        answers     是否连带答案解析（消耗站点的每日查看额度）
        answers_limit  每份试卷最多展开多少题的答案，0 表示全部
        no_cache    忽略本地页面缓存，强制重新访问站点
        names       自定义文件名，键可以是试卷编号（3p2856667）或原始网址
        workers     并发子进程数，默认 1；同域名并发容易被风控，除非确认过否则别调大
        quiet       True 时一行都不打印，适合当纯接口用
        on_progress 每完成一份回调一次：fn(已完成数, 总数, 结果)

    单份失败不会中断整批，错误放在 BatchResult.error 里。
    """

    paths.ensure_dirs()
    targets = load_urls(urls)
    total = len(targets)
    results: list[BatchResult] = [BatchResult(url=raw) for raw in targets]
    if total == 0:
        if not quiet:
            print("没有需要处理的网址。")
        return results

    directory = Path(out_dir) if out_dir else paths.OUTPUT_DIR
    directory.mkdir(parents=True, exist_ok=True)

    context = _BatchContext(
        out_dir=directory,
        answers=answers,
        answers_limit=answers_limit,
        no_cache=no_cache,
        names=names or {},
        used_names=set(),
        lock=threading.Lock(),
    )

    started = time.perf_counter()

    def run_task(index: int) -> BatchResult:
        return _run_one(targets[index], context)

    # ------ 串行是默认值：站点对同域名并发很敏感，workers 只留给确认过风控的人 ------ #
    if workers and workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run_task, index) for index in range(total)]
            for index, future in enumerate(futures):
                results[index] = _collect(future, targets[index])
                _report(index + 1, total, results[index], quiet, on_progress)
    else:
        for index in range(total):
            results[index] = run_task(index)
            _report(index + 1, total, results[index], quiet, on_progress)

    elapsed = time.perf_counter() - started
    if not quiet:
        success = sum(1 for item in results if item.ok)
        print()
        print(f"处理完成：成功 {success} / {total} 份，总耗时 {elapsed:.1f}s")
        failed = [item for item in results if not item.ok]
        if failed:
            print("失败清单：")
            for item in failed:
                print(f"  - {item.url}：{item.error}")
    return results


def _collect(future: Any, raw: str) -> BatchResult:
    """取回线程结果，顺带把意外异常兜成一条失败记录。"""
    try:
        return future.result()
    except Exception as exc:  # noqa: BLE001 - 单份异常不该中断整批
        return BatchResult(url=raw, ok=False, error=f"内部错误：{type(exc).__name__}: {exc}")


def _report(
    done: int,
    total: int,
    result: BatchResult,
    quiet: bool,
    on_progress: Callable[[int, int, BatchResult], None] | None,
) -> None:
    """统一的进度出口：打印和回调都在这里，避免并发时顺序错乱。"""
    if not quiet:
        print(_format_line(done, total, result), flush=True)
    if on_progress is not None:
        on_progress(done, total, result)


def load_urls(source: Sequence[str] | str | Path) -> list[str]:
    
    """
    把输入统一成网址列表。

    可以给：列表、文本文件路径、一段带换行的文本。
    空行和 # 开头的行会被忽略，方便直接维护一份 urls.txt。
    """
    
    if isinstance(source, (list, tuple)):
        rows = [str(item) for item in source]
    elif isinstance(source, Path):
        rows = _read_lines(source)
    elif isinstance(source, str):
        candidate = Path(source)
        # ------ 传进来的可能是文件路径，也可能直接就是网址，靠“文件是否存在”区分 ------ #
        if "\n" not in source and candidate.is_file():
            rows = _read_lines(candidate)
        else:
            rows = source.splitlines()
    else:
        raise TypeError(f"不支持的 urls 类型：{type(source).__name__}")

    cleaned: list[str] = []
    for row in rows:
        text = row.strip()
        if not text or text.startswith("#"):
            continue
        cleaned.append(text)
    return cleaned


@dataclass
class _BatchContext:
    """一次批量运行的共享配置。"""

    out_dir: Path
    answers: bool
    answers_limit: int
    no_cache: bool
    names: dict[str, str]
    used_names: set[str]
    lock: threading.Lock


def _read_lines(path: Path) -> list[str]:
    for encoding in ("utf-8-sig", "gbk"):  # 记事本另存为的可能不是 UTF-8
        try:
            return path.read_text(encoding=encoding).splitlines()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"读不出这个文件，编码无法识别：{path}")


def _run_one(raw: str, context: _BatchContext) -> BatchResult:
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

    code, out, err = _run_spider(url, paper_id, context)
    status = _read_json(_status_path(paper_id))
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
        result.docx_path = _build_docx(json_path, raw, url, paper_id, context)
        result.ok = True
    except Exception as exc:  # noqa: BLE001 - 生成失败也只影响这一份
        result.error = f"生成 Word 失败：{type(exc).__name__}: {exc}"
    result.elapsed = time.perf_counter() - started
    return result


def _run_spider(url: str, paper_id: str, context: _BatchContext) -> tuple[int, str, str]:
    cmd = [
        sys.executable, "-m", "zujuan.run_spider",
        "--url", url,
        # ------ 每份试卷各写一份状态和日志，workers>1 时不至于互相覆盖 ------ #
        "--status-file", str(_status_path(paper_id)),
        "--log-file", str(_log_path(paper_id)),
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


def _build_docx(
    json_path: Path,
    raw: str,
    url: str,
    paper_id: str,
    context: _BatchContext,
) -> Path:
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


def _status_path(paper_id: str) -> Path:
    return paths.LOG_DIR / f"batch_{paper_id}.json"


def _log_path(paper_id: str) -> Path:
    return paths.LOG_DIR / f"batch_{paper_id}.log"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _format_line(done: int, total: int, result: BatchResult) -> str:
    head = f"[{done}/{total}]"
    if result.ok:
        name = result.docx_path.name if result.docx_path else "?"
        return (f"{head} OK   {result.paper_id}  {result.question_count}题  "
                f"{result.elapsed:5.1f}s  -> {name}")
    return f"{head} 失败 {result.paper_id or result.url}  {result.elapsed:5.1f}s  {result.error}"


def main(argv: list[str] | None = None) -> int:
    
    """
    命令行入口：从一个文本文件里读网址批量导出，全部成功返回 0，否则返回 1。
    
        python multi_run.py urls.txt --answers --workers 2
    """
    
    parser = argparse.ArgumentParser(
        prog="multi_run.py",
        description="批量导出组卷网试卷（无交互，网址一行一个写在文本文件里）",
    )
    parser.add_argument("file", help="网址列表文件（一行一个，支持 # 注释）")
    parser.add_argument("-o", "--out", default="", help="输出目录，默认 output/")
    parser.add_argument("-n", "--name", action="append", default=[],
                        help="自定义文件名，格式 编号=名字，可重复")
    parser.add_argument("--answers", action="store_true", help="同时导出答案解析（消耗每日查看额度）")
    parser.add_argument("--answers-limit", type=int, default=0,
                        help="每份试卷最多导出多少题的答案（0 表示全部）")
    parser.add_argument("--no-cache", action="store_true", help="忽略本地缓存，重新访问站点")
    parser.add_argument("--workers", type=int, default=1,
                        help="并发子进程数，默认 1（同域名并发容易被风控）")
    parser.add_argument("--quiet", action="store_true", help="不打印进度")
    args = parser.parse_args(argv)

    source = Path(args.file)
    if not source.is_file():
        print(f"找不到网址列表文件：{source}", file=sys.stderr)
        return 2

    results = batch_export(
        source,
        out_dir=args.out or None,
        answers=args.answers,
        answers_limit=args.answers_limit,
        no_cache=args.no_cache,
        names=_parse_name_args(args.name),
        workers=args.workers,
        quiet=args.quiet,
    )
    return 0 if all(item.ok for item in results) else 1


def _parse_name_args(items: list[str]) -> dict[str, str]:
    """把 ``-n 3p2856667=期中卷`` 解析成字典。"""
    names: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            print(f"忽略无效的 --name：{item}（应为 编号=名字）", file=sys.stderr)
            continue
        names[key.strip()] = value.strip()
    return names


if __name__ == "__main__":
    raise SystemExit(main())
