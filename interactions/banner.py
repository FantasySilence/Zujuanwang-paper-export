# ============================================================= #
# @Author: Fantasy_Silence                                      #
# @Time: 2026-11-12                                             #
# @IDE: Visual Studio Code & PyCharm                            #
# @Python: 3.9.7                                                #
# ============================================================= #
# @Description: 启动画面：ASCII Banner、分隔线、账号状态            #
# ============================================================= #

from __future__ import annotations

from zujuan import auth

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


def print_banner() -> None:
    """打印启动画面和当前账号状态。"""
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
