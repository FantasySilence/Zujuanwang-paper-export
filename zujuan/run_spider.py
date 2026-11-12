# ================================================== #
# @Author: Fantasy_Silence                           #
# @Time: 2026-11-12                                  #
# @IDE: Visual Studio Code & PyCharm                 #
# @Python: 3.9.7                                     #
# ================================================== #
# @Description: 在独立进程里跑一次 ``paper`` 爬虫。    #
# ================================================== #
"""
命令行工具通过子进程调用它，好处是 Twisted reactor 与 Playwright
不会和交互界面互相干扰，每份试卷都是干净的一次运行。

    python -m zujuan.run_spider --url https://zujuan.xkw.com/3p2856667.html
"""

from __future__ import annotations

import argparse
import os
import sys
import warnings

from . import paths, status


def _quiet_asyncio_pipe_noise() -> None:
    """Playwright 的 node 驱动子进程管道在 Windows 上退出时会抛出无害的
    ``ValueError: I/O operation on closed pipe``（发生在解释器清理阶段），
    这里只屏蔽这一种，避免命令行窗口出现吓人的 Traceback。"""
    default_hook = sys.unraisablehook

    def hook(unraisable):  # type: ignore[no-untyped-def]
        exc = unraisable.exc_value
        if isinstance(exc, ValueError) and "closed pipe" in str(exc):
            return
        default_hook(unraisable)

    sys.unraisablehook = hook
    warnings.filterwarnings("ignore", category=ResourceWarning)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="抓取一份组卷网试卷")
    parser.add_argument("--url", required=True, help="试卷网址或试卷编号")
    parser.add_argument("--answers", action="store_true", help="同时抓取答案解析（消耗每日查看额度）")
    parser.add_argument(
        "--answers-limit",
        type=int,
        default=0,
        help="最多展开多少道题的答案解析（0 表示全部）",
    )
    parser.add_argument("--no-cache", action="store_true", help="忽略本地缓存，重新访问站点")
    parser.add_argument("--loglevel", default="INFO", help="Scrapy 日志级别")
    # ------ 批量下载时给每份试卷指各自的文件，避免并发互相覆盖 ------ #
    parser.add_argument("--status-file", default="", help="运行结果写到这里（默认 .temp/logs/last_run.json）")
    parser.add_argument("--log-file", default="", help="Scrapy 日志写到这里（默认 .temp/logs/scrapy.log）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths.ensure_dirs()
    status.set_path(args.status_file or None)
    status.clear()
    _quiet_asyncio_pipe_noise()

    # get_project_settings() 靠这个环境变量找到 settings.py
    os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "zujuan.settings")

    from scrapy.crawler import CrawlerProcess
    from scrapy.utils.project import get_project_settings

    from .spiders.paper import PaperSpider

    settings = get_project_settings()
    # 命令行传进来的日志级别优先于 settings.py 里的默认值
    settings.set("LOG_LEVEL", args.loglevel, priority="cmdline")
    if args.log_file:
        settings.set("LOG_FILE", args.log_file, priority="cmdline")

    # 一次进程只跑一份试卷，reactor 用完即退，不和交互界面抢事件循环
    process = CrawlerProcess(settings)
    process.crawl(
        PaperSpider,
        url=args.url,
        answers=args.answers,
        answers_limit=args.answers_limit,
        no_cache=args.no_cache,
    )
    process.start()

    # 成败不看退出码，看爬虫自己写的状态文件
    result = status.read()
    if not result.get("ok"):
        message = result.get("error") or f"抓取未产生结果，请查看 {args.log_file or '.temp/logs/scrapy.log'}"
        print(f"[失败] {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
