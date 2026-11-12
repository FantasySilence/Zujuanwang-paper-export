# ============================================================= #
# @Author: Fantasy_Silence                                      #
# @Time: 2026-11-12                                             #
# @IDE: Visual Studio Code & PyCharm                            #
# @Python: 3.9.7                                                #
# ============================================================= #
# @Description: 命令行交互界面：输入试卷网址，输出 Word 文档。      #
# ============================================================= #

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import auth, paths, status
from .docx_writer import DocxOptions, build_document, resolve_filename
from .extractor import normalize_paper_url, parse_paper_id
from .images import ImageCache

SPINNER = ("|", "/", "-", "\\")

# ------ 启动 Banner，宽度按最长一行对齐下面的分隔线 ------ #
BANNER = r"""
  ______     _                                            _____                      ______                       _
 |___  /    (_)                                          |  __ \                    |  ____|                     | |
    / /_   _ _ _   _  __ _ _ ____      ____ _ _ __   __ _| |__) |_ _ _ __   ___ _ __| |__  __  ___ __   ___ _ __| |_
   / /| | | | | | | |/ _` | '_ \ \ /\ / / _` | '_ \ / _` |  ___/ _` | '_ \ / _ \ '__|  __| \ \/ / '_ \ / _ \| '__| __|
  / /_| |_| | | |_| | (_| | | | \ V  V / (_| | | | | (_| | |  | (_| | |_) |  __/ |  | |____ >  <| |_) | (_) | |  | |_
 /_____\__,_| |\__,_|\__,_|_| |_|\_/\_/ \__,_|_| |_|\__, |_|   \__,_| .__/ \___|_|  |______/_/\_\ .__/ \___/|_|   \__|
           _/ |                                      __/ |          | |                         | |
          |__/                                      |___/           |_|                         |_|
""".strip("\n")

LINE = "-" * max(len(row) for row in BANNER.splitlines())

# ------ 输入流被关闭（管道 / 自动化调用）时置位，用来退出菜单 ------ #
_EOF_REACHED = False


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _prepare_console()
    paths.ensure_dirs()
    auth.ensure_auth_file()

    _print_banner()

    try:
        if args.url:
            ok = _export(
                args.url,
                answers=args.answers,
                answers_limit=args.answers_limit,
                no_cache=args.no_cache,
                auto_open=not args.no_open,
                name=args.name,
            )
            return 0 if ok else 1
        return _menu()
    except KeyboardInterrupt:
        print("\n已取消。")
        return 130
    finally:
        if args.pause:
            try:
                input("\n按回车键退出…")
            except (EOFError, KeyboardInterrupt):
                pass


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
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


def _prepare_console() -> None:
    
    """
    让中文在管道重定向时也不至于抛 UnicodeEncodeError。

    控制台里 Python 用 WriteConsoleW 输出，重定向到文件时才按代码页编码，
    拿不准字符集就直接替换掉，别让整个导出挂在打印上。
    """
    
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def _print_banner() -> None:
    print(LINE)
    print()
    print(BANNER)
    print()
    print(LINE)
    print()
    print("  组卷网试卷导出工具   ·   Scrapy + Playwright")
    print("  中间产物：.temp      输出目录：output")
    print("  作者：Fantasy_Silence   ·   仓库地址：https://github.com/FantasySilence/Zujuanwang-paper-export")
    print()
    print(LINE)
    print()

    if not auth.ensure_auth_file():
        print("  状态：尚未登录（首次使用请先执行菜单 2）")
        return

    info = auth.read_meta()
    if info.get("user_name"):
        print(f"  账号：{info['user_name']}（登录态保存于 {info.get('saved_at', '未知时间')}）")
    elif auth.cookie_alive():
        print("  账号：已登录（本地登录态有效）")
    else:
        print("  状态：登录态可能已过期，建议执行菜单 2 重新登录")
    print()
    print(LINE)


def _menu() -> int:
    while True:
        print()
        print("  [1] 导出试卷（输入试卷网址）")
        print("  [2] 登录 / 更换账号")
        print("  [3] 用缓存数据重新生成 Word")
        print("  [4] 查看 / 清理缓存")
        print("  [0] 退出")
        print()
        choice = _ask("请选择").strip()

        if _EOF_REACHED:
            print("\n再见。")
            return 0
        if choice in ("0", "q", "quit", "exit"):
            print("\n再见。")
            return 0
        if choice == "1":
            _menu_export()
        elif choice == "2":
            _menu_login()
        elif choice == "3":
            _menu_rebuild()
        elif choice == "4":
            _menu_cache()
        elif choice == "":
            continue
        else:
            print("  无效的选项，请输入 0-4。")


def _ask(prompt: str) -> str:
    global _EOF_REACHED
    try:
        return input(f"{prompt}: ")
    except EOFError:
        # ------ 管道调用时没有输入，标记一下让菜单自己退出去 ------ #
        _EOF_REACHED = True
        return ""


def _ask_yes(prompt: str, default: bool = False) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    answer = _ask(f"{prompt} {hint}").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes", "是")


def _interactive() -> bool:
    
    """
    判断是不是真人在控制台操作，管道调用时不该弹确认、也不该自动开 Word。
    """
    
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _menu_export() -> None:
    print()
    print("  把试卷详情页网址粘贴进来即可，例如：")
    print("    https://zujuan.xkw.com/3p2856667.html")
    print("  （也可以只输入试卷编号，如 3p2856667）")
    print()

    while True:
        raw = _ask("试卷网址（直接回车返回）").strip()
        if not raw:
            return
        answers = _ask_yes("是否需要一并导出答案解析（消耗每日查看额度）", default=False)
        limit = 0
        if answers:
            raw_limit = _ask("最多导出多少题的答案（直接回车=全部）").strip()
            limit = int(raw_limit) if raw_limit.isdigit() else 0
        name = _ask("保存的文件名（直接回车用试卷原标题）").strip()
        _export(raw, answers=answers, answers_limit=limit, no_cache=False, name=name)
        print()
        if not _ask_yes("继续导出下一份", default=False):
            return


def _menu_login() -> None:
    print()
    # ------ 本地登录态还没过期就别折腾，只做一次联网校验 ------ #
    if auth.cookie_alive() and not _ask_yes("本地已有登录态，仍然重新登录吗", default=False):
        if _ask_yes("要联网校验一下当前登录态吗", default=True):
            print("  正在校验…")
            info = auth.check_login()
            print(f"  {'[OK] ' if info.logged_in else '[X]  '}{info.message}"
                  + (f"（{info.user_name}）" if info.user_name else ""))
        return

    print("  正在打开浏览器…")
    info = auth.interactive_login()
    if info.logged_in:
        print(f"  [OK] 登录成功：{info.user_name or '已登录'}")
        _print_banner()
    else:
        print("  [X]  没有检测到登录，稍后可重试。")


def _menu_rebuild() -> None:
    papers = _cached_papers()
    if not papers:
        print("\n  还没有缓存数据，先用菜单 1 导出一份试卷吧。")
        return

    print()
    print("  已缓存的试卷：")
    for index, item in enumerate(papers, 1):
        print(f"   [{index}] {item['title']}")
        print(f"        {item['paper_id']} · {item['question_count']} 题 · {item['mtime']}")
    print()

    choice = _ask("选择要重新生成的编号（回车返回）").strip()
    if not choice:
        return
    if not choice.isdigit() or not (1 <= int(choice) <= len(papers)):
        print("  编号无效。")
        return

    item = papers[int(choice) - 1]
    name = _ask("保存的文件名（直接回车用试卷原标题）").strip()
    _build_docx(Path(item["path"]), name=name)


def _menu_cache() -> None:
    print()
    print(f"  缓存目录：{paths.TEMP_DIR}")
    for label, path in (
        ("页面缓存 (httpcache)", paths.HTTPCACHE_DIR),
        ("解析数据 (data)", paths.DATA_DIR),
        ("题目图片 (images)", paths.IMAGE_DIR),
        ("登录态 (auth)", paths.AUTH_DIR),
        ("日志 (logs)", paths.LOG_DIR),
    ):
        print(f"    {label:<24} {_dir_size(path)/1024/1024:>8.2f} MB")

    papers = _cached_papers()
    print(f"\n  已缓存 {len(papers)} 份试卷。")

    print()
    print("  [1] 清空页面缓存（下次重新访问站点）")
    print("  [2] 清空全部缓存（含解析数据、图片、登录态）")
    print("  [0] 返回")
    choice = _ask("请选择").strip()
    if choice == "1":
        _remove_tree(paths.HTTPCACHE_DIR)
        print("  页面缓存已清空。")
    elif choice == "2":
        if _ask_yes("确认清空全部缓存（登录态也会失效）", default=False):
            for path in (paths.HTTPCACHE_DIR, paths.DATA_DIR, paths.IMAGE_DIR, paths.AUTH_DIR):
                _remove_tree(path)
            print("  缓存已清空。")
    print()


def _export(
    raw_url: str,
    *,
    answers: bool = False,
    answers_limit: int = 0,
    no_cache: bool = False,
    auto_open: bool | None = None,
    name: str = "",
) -> bool:
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
    code, _out, err = _run_spider(url, answers=answers, answers_limit=answers_limit, no_cache=no_cache)
    result = status.read()

    if code != 0 or not result.get("ok"):
        message = result.get("error") or (err or "").strip() or "抓取失败"
        print(f"\n  [X]  {message}")
        print("      详细日志：.temp/logs/scrapy.log")
        return False

    print(f"  [OK] 抓取完成：{result.get('section_count')} 个题型 / {result.get('question_count')} 道题"
          + (f"（答案解析 {result.get('answer_count')} 张）" if result.get("answer_count") else ""))

    json_path = paths.paper_json_path(result.get("paper_id") or paper_id)
    if not json_path.exists():
        print(f"\n  [X]  没有找到解析结果：{json_path}")
        return False

    docx_path = _build_docx(json_path, name=name)
    if docx_path is None:
        return False

    if auto_open is False:
        return True
    if _ask_yes("现在打开 Word 文档吗", default=_interactive()):
        _open_file(docx_path)
    return True


def _run_spider(
    url: str,
    *,
    answers: bool,
    answers_limit: int = 0,
    no_cache: bool = False,
) -> tuple[int, str, str]:
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
    animate = _interactive()
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


def _build_docx(json_path: Path, name: str = "") -> Path | None:
    
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
    if target.exists() and _interactive() and not _ask_yes(f"{target.name} 已存在，覆盖吗", default=True):
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
    print(f"       大小 {size_mb:.2f} MB · 图片 {len(_paper_images(paper))} 张"
          f"（新下载 {stats['downloaded']} / 缓存命中 {stats['cached']}"
          + (f" / 失败 {stats['failed']}" if stats["failed"] else "") + "）")
    return path


def _paper_images(paper: dict[str, Any]) -> list[dict[str, Any]]:
    images = []
    for section in paper.get("sections", []):
        for question in section.get("questions", []):
            images.extend(question.get("images") or [])
    return images


def _open_file(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:  # noqa: BLE001
        print(f"  打不开文件：{exc}")


def _cached_papers() -> list[dict[str, Any]]:
   
    """
    列出 .temp/data 下的试卷，最近导出的排在前面。
    """
   
    items: list[dict[str, Any]] = []
    for path in paths.DATA_DIR.glob("*.paper.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items.append({
            "path": str(path),
            "paper_id": data.get("paper_id", path.stem),
            "title": data.get("title") or path.stem,
            "question_count": (data.get("stats") or {}).get("question_count", "?"),
            "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            "_mtime": path.stat().st_mtime,
        })
    items.sort(key=lambda item: item["_mtime"], reverse=True)
    return items


def _dir_size(path: Path) -> int:
    
    """
    统计目录占用，用来在缓存菜单里显示大小。
    """
    
    total = 0
    if not path.exists():
        return 0
    for file_path in path.rglob("*"):
        try:
            if file_path.is_file():
                total += file_path.stat().st_size
        except OSError:
            continue
    return total


def _remove_tree(path: Path) -> None:
    
    """
    清空目录但保留目录本身，Scrapy 下次写入不会因为目录不存在报错。
    """
   
    import shutil

    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
