# ============================================================= #
# @Author: Fantasy_Silence                                      #
# @Time: 2026-11-12                                             #
# @IDE: Visual Studio Code & PyCharm                            #
# @Python: 3.9.7                                                #
# ============================================================= #
# @Description: 菜单：主循环 + 导出/登录/重建/缓存四个菜单项        #
# ============================================================= #

from __future__ import annotations

from pathlib import Path

from zujuan import auth, paths

from .banner import print_banner
from .cache import cached_papers, dir_size, remove_tree
from .console import ask, ask_yes, eof
from .export import build_docx, export_paper


def menu() -> int:
    """主菜单循环，返回进程退出码。"""
    while True:
        print()
        print("  [1] 导出试卷（输入试卷网址）")
        print("  [2] 登录 / 更换账号")
        print("  [3] 用缓存数据重新生成 Word")
        print("  [4] 查看 / 清理缓存")
        print("  [0] 退出")
        print()
        choice = ask("请选择").strip()

        if eof():
            print("\n已退出。")
            return 0
        if choice in ("0", "q", "quit", "exit"):
            print("\n已退出。")
            return 0
        if choice == "1":
            menu_export()
        elif choice == "2":
            menu_login()
        elif choice == "3":
            menu_rebuild()
        elif choice == "4":
            menu_cache()
        elif choice == "":
            continue
        else:
            print("  无效的选项，请输入 0-4。")


def menu_export() -> None:
    """菜单项 1：输入网址导出，支持连续导出多份。"""
    print()
    print("  把试卷详情页网址粘贴进来即可，例如：")
    print("    https://zujuan.xkw.com/3p2856667.html")
    print("    https://zujuan.xkw.com/2p3041456.html")
    print("  （也可以只输入试卷编号，如 3p2856667 / 2p3041456）")
    print("  （前缀 2p / 3p 是两个不同的题库，同一编号可能是两份试卷，别改前缀）")
    print()

    while True:
        raw = ask("试卷网址（直接回车返回）").strip()
        if not raw:
            return
        answers = ask_yes("是否需要一并导出答案解析（消耗每日查看额度）", default=False)
        limit = 0
        if answers:
            raw_limit = ask("最多导出多少题的答案（直接回车=全部）").strip()
            limit = int(raw_limit) if raw_limit.isdigit() else 0
        name = ask("保存的文件名（直接回车用试卷原标题）").strip()
        export_paper(raw, answers=answers, answers_limit=limit, no_cache=False, name=name)
        print()
        if not ask_yes("继续导出下一份", default=False):
            return


def menu_login() -> None:
    """菜单项 2：登录或更换账号。"""
    print()
    # ------ 本地登录态还没过期就别折腾，只做一次联网校验 ------ #
    if auth.cookie_alive() and not ask_yes("本地已有登录态，仍然重新登录吗", default=False):
        if ask_yes("要联网校验一下当前登录态吗", default=True):
            print("  正在校验…")
            info = auth.check_login()
            print(f"  {'[OK] ' if info.logged_in else '[X]  '}{info.message}"
                  + (f"（{info.user_name}）" if info.user_name else ""))
        return

    print("  正在打开浏览器…")
    info = auth.interactive_login()
    if info.logged_in:
        print(f"  [OK] 登录成功：{info.user_name or '已登录'}")
        print_banner()
    else:
        print("  [X]  没有检测到登录，稍后可重试。")


def menu_rebuild() -> None:
    """菜单项 3：从缓存里的解析结果重新生成 Word。"""
    papers = cached_papers()
    if not papers:
        print("\n  还没有缓存数据，先用菜单 1 导出一份试卷吧。")
        return

    print()
    print("  已缓存的试卷：")
    for index, item in enumerate(papers, 1):
        print(f"   [{index}] {item['title']}")
        print(f"        {item['paper_id']} · {item['question_count']} 题 · {item['mtime']}")
    print()

    choice = ask("选择要重新生成的编号（回车返回）").strip()
    if not choice:
        return
    if not choice.isdigit() or not (1 <= int(choice) <= len(papers)):
        print("  编号无效。")
        return

    item = papers[int(choice) - 1]
    name = ask("保存的文件名（直接回车用试卷原标题）").strip()
    build_docx(Path(item["path"]), name=name)


def menu_cache() -> None:
    """菜单项 4：查看各缓存目录占用并支持清空。"""
    print()
    print(f"  缓存目录：{paths.TEMP_DIR}")
    for label, path in (
        ("页面缓存 (httpcache)", paths.HTTPCACHE_DIR),
        ("解析数据 (data)", paths.DATA_DIR),
        ("题目图片 (images)", paths.IMAGE_DIR),
        ("登录态 (auth)", paths.AUTH_DIR),
        ("日志 (logs)", paths.LOG_DIR),
    ):
        print(f"    {label:<24} {dir_size(path)/1024/1024:>8.2f} MB")

    papers = cached_papers()
    print(f"\n  已缓存 {len(papers)} 份试卷。")

    print()
    print("  [1] 清空页面缓存（下次重新访问站点）")
    print("  [2] 清空全部缓存（含解析数据、图片、登录态）")
    print("  [0] 返回")
    choice = ask("请选择").strip()
    if choice == "1":
        remove_tree(paths.HTTPCACHE_DIR)
        print("  页面缓存已清空。")
    elif choice == "2":
        if ask_yes("确认清空全部缓存（登录态也会失效）", default=False):
            for path in (paths.HTTPCACHE_DIR, paths.DATA_DIR, paths.IMAGE_DIR, paths.AUTH_DIR):
                remove_tree(path)
            print("  缓存已清空。")
    print()
