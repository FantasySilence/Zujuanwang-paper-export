# ======================================================================  #
# @Author: Fantasy_Silence                                                #
# @Time: 2026-11-12                                                       #
# @IDE: Visual Studio Code & PyCharm                                      #
# @Python: 3.9.7                                                          #
# ======================================================================  #
# @Description: 批量编排：串行/并发调度、进度上报、结果汇总                #
# ======================================================================  #

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Sequence

from zujuan import paths

from .models import BatchContext, BatchResult
from .sources import load_urls
from .worker import format_line, run_one


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

    context = BatchContext(
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
        return run_one(targets[index], context)

    # ------ 串行是默认值：站点对同域名并发很敏感，workers 只留给确认过风控的人 ------ #
    if workers and workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run_task, index) for index in range(total)]
            for index, future in enumerate(futures):
                results[index] = collect(future, targets[index])
                report(index + 1, total, results[index], quiet, on_progress)
    else:
        for index in range(total):
            results[index] = run_task(index)
            report(index + 1, total, results[index], quiet, on_progress)

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


def collect(future: Any, raw: str) -> BatchResult:
    """取回线程结果，顺带把意外异常兜成一条失败记录。"""
    try:
        return future.result()
    except Exception as exc:  # noqa: BLE001 - 单份异常不该中断整批
        return BatchResult(url=raw, ok=False, error=f"内部错误：{type(exc).__name__}: {exc}")


def report(
    done: int,
    total: int,
    result: BatchResult,
    quiet: bool,
    on_progress: Callable[[int, int, BatchResult], None] | None,
) -> None:
    """统一的进度出口：打印和回调都在这里，避免并发时顺序错乱。"""
    if not quiet:
        print(format_line(done, total, result), flush=True)
    if on_progress is not None:
        on_progress(done, total, result)
