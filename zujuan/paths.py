# ===================================================================== #
# @Author: Fantasy_Silence                                              #
# @Time: 2026-11-12                                                     #
# @IDE: Visual Studio Code & PyCharm                                    #
# @Python: 3.9.7                                                        #
# ===================================================================== #
# @Description: 项目路径约定：中间产物统一放 .temp，最终 Word 放 output。  #
# ===================================================================== #

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# 中间产物根目录，整体删掉也不影响已导出的 Word
TEMP_DIR = BASE_DIR / ".temp"

# Scrapy 渲染后的页面缓存，同一份试卷重复导出时不再访问站点
HTTPCACHE_DIR = TEMP_DIR / "httpcache"
# 解析结果，JSON 给 Word 用，CSV 给数据分析用
DATA_DIR = TEMP_DIR / "data"
# 题目图片与答案解析图片，按 URL 哈希命名
IMAGE_DIR = TEMP_DIR / "images"
# Playwright 登录态，组卷网有效期约一天
AUTH_DIR = TEMP_DIR / "auth"
AUTH_FILE = AUTH_DIR / "auth.json"
# 早期版本把登录态存在 .test 下，首次运行会从这里迁移
LEGACY_AUTH_FILE = BASE_DIR / ".test" / "auth.json"
LOG_DIR = TEMP_DIR / "logs"

# 用户最终拿到的文档目录
OUTPUT_DIR = BASE_DIR / "output"


def ensure_dirs() -> None:
    """创建运行所需目录。"""
    for path in (TEMP_DIR, HTTPCACHE_DIR, DATA_DIR, IMAGE_DIR, AUTH_DIR, LOG_DIR, OUTPUT_DIR):
        path.mkdir(parents=True, exist_ok=True)


def paper_json_path(paper_id: str) -> Path:
    """试卷解析结果的落盘位置。"""
    return DATA_DIR / f"{paper_id}.paper.json"


def paper_html_path(paper_id: str) -> Path:
    """留一份原始页面，解析结果不对时用来排查。"""
    return DATA_DIR / f"{paper_id}.page.html"
