# ============================================================= #
# @Author: Fantasy_Silence                                      #
# @Time: 2026-11-12                                             #
# @IDE: Visual Studio Code & PyCharm                            #
# @Python: 3.9.7                                                #
# ============================================================= #
# @Description: 程序入口：解析参数、准备控制台、分发到菜单或单份导出  #
# ============================================================= #

from __future__ import annotations

import argparse

from zujuan import auth, paths

from .banner import print_banner
from .console import prepare_console
from .export import export_paper
from .menus import menu


def main(argv: list[str] | None = None) -> int:
    """命令行入口：给了网址就直接导出，否则进菜单。"""
    args = parse_args(argv)
    prepare_console()
    paths.ensure_dirs()
    auth.ensure_auth_file()

    print_banner()

    try:
        if args.url:
            ok = export_paper(
                args.url,
                answers=args.answers,
                answers_limit=args.answers_limit,
                no_cache=args.no_cache,
                auto_open=not args.no_open,
                name=args.name,
            )
            return 0 if ok else 1
        return menu()
    except KeyboardInterrupt:
        print("\n已取消。")
        return 130
    finally:
        if args.pause:
            try:
                input("\n按回车键退出…")
            except (EOFError, KeyboardInterrupt):
                pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="组卷网试卷导出：输入试卷网址，生成 Word 文档",
    )
    parser.add_argument("url", nargs="?", help="试卷网址（不给则进入交互菜单）")
    parser.add_argument("-n", "--name", default="", help="自定义输出文件名（默认用试卷原标题）")
    parser.add_argument("--answers", action="store_true", help="同时导出答案解析图片（消耗每日查看额度）")
    parser.add_argument(
        "--answers-limit",
        type=int,
        default=0,
        help="最多导出多少道题的答案解析（0 表示全部）",
    )
    parser.add_argument("--no-cache", action="store_true", help="忽略本地页面缓存，重新访问站点")
    parser.add_argument("--pause", action="store_true", help="结束前等待回车（双击运行时用）")
    parser.add_argument("--no-open", action="store_true", help="生成后不自动打开 Word")
    return parser.parse_args(argv)
