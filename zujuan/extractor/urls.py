# =========================================================== #
# @Author: Fantasy_Silence                                    #
# @Time: 2026-11-12                                           #
# @IDE: Visual Studio Code & PyCharm                          #
# @Python: 3.9.7                                              #
# =========================================================== #
# @Description: 试卷网址与编号：解析用户输入、推导要依次尝试的地址。
# =========================================================== #
from __future__ import annotations

import re

__all__ = ["parse_paper_id", "normalize_paper_url", "plan_urls", "usertk_url"]


_PAPER_ID_RE = re.compile(r"(\d+p\d+)")


_PAPER_URL_RE = re.compile(r"https?://zujuan\.xkw\.com/(?:usertk/)?\d+p\d+\.html")


_BARE_PATH_RE = re.compile(r"https?://zujuan\.xkw\.com/(\d+)\.html")


def parse_paper_id(url: str) -> str:
    """从试卷网址中提取试卷标识，例如 ``3p2856667`` / ``2p3041456``。

    前缀（2p / 3p …）是站内的题库编号，必须原样保留：同一个数字在两个题库里
    可能是两份完全不同的试卷，所以不能把 2p 归一成 3p。
    """
    match = _PAPER_ID_RE.search(url)
    if match:
        return match.group(1)
    match = re.search(r"/(\d{5,})\.html", url)
    if match:
        return f"3p{match.group(1)}"
    raise ValueError(f"无法从网址中识别试卷编号: {url}")


def normalize_paper_url(raw: str) -> str:
    """把用户输入（网址 / 试卷编号 / 带杂物的一整行）规范成试卷详情页网址。

    支持的输入::

        https://zujuan.xkw.com/3p2856667.html          普通试卷（3 号题库）
        https://zujuan.xkw.com/2p3041456.html          普通试卷（2 号题库）
        https://zujuan.xkw.com/usertk/3p129898802.html 自己组的试卷（个人题库）
        https://zujuan.xkw.com/3p2856667.html?from=xx#comments
        3p2856667
        2856667
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("试卷网址为空")

    match = re.search(r"https?://[^\s]+", text)
    if match:
        url = match.group(0).split("?", 1)[0].split("#", 1)[0]
        if "zujuan.xkw.com" not in url:
            raise ValueError("目前只支持组卷网（zujuan.xkw.com）的试卷网址")
        # 历史链接里有没有前缀的写法（/3041456.html），这种只能按 3 号题库猜
        url = _BARE_PATH_RE.sub(r"https://zujuan.xkw.com/3p\1.html", url)
        # 自组试卷挂在 /usertk/ 下，路径不同但编号规则一样
        if not _PAPER_URL_RE.fullmatch(url):
            raise ValueError(
                "看起来不是试卷详情页网址，示例："
                "https://zujuan.xkw.com/3p2856667.html、"
                "https://zujuan.xkw.com/2p3041456.html 或 "
                "https://zujuan.xkw.com/usertk/3p129898802.html"
            )
        return url

    # 只给编号：带前缀（2p3041456 / 3p2856667）就照前缀打开
    if _PAPER_ID_RE.fullmatch(text):
        return f"https://zujuan.xkw.com/{text}.html"
    # 连前缀都没给，先按使用最多的 3 号题库打开
    if re.fullmatch(r"\d{5,}", text):
        return f"https://zujuan.xkw.com/3p{text}.html"
    raise ValueError("无法识别的试卷网址，请粘贴形如 https://zujuan.xkw.com/3p2856667.html 的链接")


def plan_urls(raw: str) -> list[str]:
    """把用户输入展开成“依次尝试”的地址列表，第一个就是首选地址。

    站内有两套普通题库（编号前缀 2p / 3p），同一个数字在两边可能是两份不同的
    试卷，所以：

    * 输入里已经写明前缀 → 只认这一份，另外再试一下 /usertk/（个人题库）
    * 只给了数字、分不清是哪个题库 → 依次试 ``3p`` → ``/usertk/3p`` → ``2p``

    逐个尝试由爬虫负责：只有“这个地址压根没有题目”时才换下一个，
    所以顺序在前面的永远是用户真正想要的那份。
    """
    primary = normalize_paper_url(raw)
    paper_id = parse_paper_id(primary)
    urls = [primary]

    text = (raw or "").strip()
    has_prefix = bool(_PAPER_ID_RE.search(text))
    is_usertk = "/usertk/" in primary

    if not is_usertk:
        urls.append(usertk_url(paper_id))
    if not has_prefix:
        urls.append(_other_bank_url(primary, paper_id))
    return urls


def usertk_url(paper_id: str) -> str:
    """同一份试卷在“个人题库”里的地址。"""
    return f"https://zujuan.xkw.com/usertk/{paper_id}.html"


def _other_bank_url(url: str, paper_id: str) -> str:
    """同一个编号在另一个题库里的地址（2p ↔ 3p）。

    只在用户没写前缀、靠猜的时候用：同号不同卷，所以绝不能拿来“纠正”用户输入的网址。
    """
    number = paper_id.split("p", 1)[1]
    other = "2p" if paper_id.startswith("3p") else "3p"
    return url.replace(f"/{paper_id}.html", f"/{other}{number}.html")
