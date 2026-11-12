# ======================================================================  #
# @Author: Fantasy_Silence                                                #
# @Time: 2026-11-12                                                       #
# @IDE: Visual Studio Code & PyCharm                                      #
# @Python: 3.9.7                                                          #
# ======================================================================  #
# @Description: 批量导出的命令行入口                                      #
# ======================================================================  #

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .api import batch_export


def main(argv: list[str] | None = None) -> int:
    
    """
    命令行入口：从一个文本文件里读网址批量导出，全部成功返回 0，否则返回 1。

        python multi_run.py batch/data/urls.txt --answers --workers 2
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
        print(f"找不到网址列表文件：{source}（示例见 batch/data/urls.txt）", file=sys.stderr)
        return 2

    results = batch_export(
        source,
        out_dir=args.out or None,
        answers=args.answers,
        answers_limit=args.answers_limit,
        no_cache=args.no_cache,
        names=parse_name_args(args.name),
        workers=args.workers,
        quiet=args.quiet,
    )
    return 0 if all(item.ok for item in results) else 1


def parse_name_args(items: list[str]) -> dict[str, str]:
    """把 ``-n 3p2856667=期中卷`` 解析成字典。"""
    names: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            print(f"忽略无效的 --name：{item}（应为 编号=名字）", file=sys.stderr)
            continue
        names[key.strip()] = value.strip()
    return names
