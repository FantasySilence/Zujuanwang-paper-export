# ============================================================= #
# @Author: Fantasy_Silence                                      #
# @Time: 2026-11-12                                             #
# @IDE: Visual Studio Code & PyCharm                            #
# @Python: 3.9.7                                                #
# ============================================================= #
# @Description: 控制台小工具：输入、判断是否真人操作、打开文件       #
# ============================================================= #

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SPINNER = ("|", "/", "-", "\\")

# ------ 输入流被关闭（管道 / 自动化调用）时置位，用来退出菜单 ------ #
_eof_reached = False


def prepare_console() -> None:
    
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


def ask(prompt: str) -> str:
    """读一行输入；输入流已关闭时记下来，让菜单自己退出。"""
    global _eof_reached
    try:
        return input(f"{prompt}: ")
    except EOFError:
        _eof_reached = True
        return ""


def ask_yes(prompt: str, default: bool = False) -> bool:
    """问一个 y/n 问题，直接回车就用默认值。"""
    hint = "[Y/n]" if default else "[y/N]"
    answer = ask(f"{prompt} {hint}").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes", "是")


def eof() -> bool:
    """输入流是否已经读完（管道调用时会立刻为真）。"""
    return _eof_reached


def is_interactive() -> bool:
    
    """
    判断是不是真人在控制台操作，管道调用时不该弹确认、也不该自动开 Word。
    """
    
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def open_file(path: Path) -> None:
    """用系统默认程序打开文件，失败只提示不抛异常。"""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:  # noqa: BLE001
        print(f"  打不开文件：{exc}")
