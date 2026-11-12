# =================================== #
# @Author: Fantasy_Silence            #
# @Time: 2026-11-12                   #
# @IDE: Visual Studio Code & PyCharm  #
# @Python: 3.9.7                      #
# =================================== #
# @Description: 抓取组卷网单份试卷详情页#
# =================================== #
"""
抓取组卷网单份试卷详情页。

一般由命令行工具通过 ``python -m zujuan.run_spider`` 调用，也可以直接用 Scrapy::

    scrapy crawl paper -a url=https://zujuan.xkw.com/3p2856667.html
    scrapy crawl paper -a url=3p2856667 -a answers=1 --answers-limit 5
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import scrapy
from scrapy.http import Response

from .. import paths, status
from ..extractor import normalize_paper_url, parse_paper, parse_paper_id
from ..items import PaperItem

logger = logging.getLogger(__name__)


class PaperError(RuntimeError):
    
    """
    可以展示给用户的抓取错误。
    """


class PaperSpider(scrapy.Spider):

    name = "paper"
    allowed_domains = ["zujuan.xkw.com"]

    def __init__(
        self,
        url: str | None = None,
        paper_id: str | None = None,
        answers: str | bool | int = False,
        answers_limit: str | int = 0,
        no_cache: str | bool | int = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if not url and not paper_id:
            raise ValueError("必须提供 url 或 paper_id 参数")

        self.raw_url = url or ""
        self.requested_paper_id = paper_id or ""
        self.with_answers = _truthy(answers)
        try:
            self.answers_limit = max(0, int(answers_limit or 0))
        except (TypeError, ValueError):
            self.answers_limit = 0
        self.no_cache = _truthy(no_cache)

        self.paper_url = self._normalize_url(url, paper_id)
        self.paper_id = parse_paper_id(self.paper_url)
        self.html_path = paths.paper_html_path(self.paper_id)

    async def start(self):
        
        """
        Scrapy 2.13+ 的入口（异步生成器）。
        """
        
        # ------ 没有登录态连页面都是残缺的，先拦下来给个能看懂的提示 ------ #
        if not paths.AUTH_FILE.exists():
            self._fail("没有找到登录态文件 .temp/auth/auth.json，请先运行登录（菜单第 2 项）")
            return

        meta: dict[str, Any] = {
            "playwright": True,
            "playwright_wait_for": ".exam-title",
            "playwright_wait_state": "attached",
            "playwright_expand_answers": self.with_answers,
            "playwright_answers_limit": self.answers_limit,
        }
        # ------ 展开答案后的 DOM 和普通页面内容不同，既不复用也不写入缓存 ------ #
        if self.no_cache or self.with_answers:
            meta["dont_cache"] = True

        yield scrapy.Request(
            self.paper_url,
            callback=self.parse,
            errback=self.on_error,
            meta=meta,
            dont_filter=True,
        )

    def parse(self, response: Response):

        # ------ 所有异常都收敛成状态文件里的一条错误，命令行据此打印提示 ------ #
        try:
            return self._parse(response)
        except PaperError as exc:
            self._fail(str(exc))
        # ------ noqa: BLE001 - 兜底，保证命令行能拿到失败原因 ------ #
        except Exception as exc:  
            logger.exception("[spider] 解析异常")
            self._fail(f"解析失败：{type(exc).__name__}: {exc}")
        return None

    def _parse(self, response: Response):
        if response.status >= 400:
            raise PaperError(f"页面返回 HTTP {response.status}，可能触发了站点风控，请稍后重试")

        html = response.text

        # ------ 存一份原始页面，解析结果不对时可以直接拿来复现 ------ #
        self._save_html(html)

        problem = self._detect_problem(response)
        if problem:
            raise PaperError(problem)

        payload = parse_paper(html, self.paper_url)
        if not payload.get("sections"):
            raise PaperError("页面结构已变化，没有解析出任何题目")

        item = PaperItem(
            paper_id=payload["paper_id"],
            url=self.paper_url,
            title=payload.get("title", ""),
            fetched_at=datetime.now().isoformat(timespec="seconds"),
            payload=payload,
        )

        answers = sum(len(q.get("answer_images") or []) for s in payload["sections"] for q in s["questions"])
        status.write(
            ok=True,
            paper_id=self.paper_id,
            title=payload.get("title", ""),
            question_count=payload["stats"]["question_count"],
            section_count=payload["stats"]["section_count"],
            answer_count=answers,
            url=self.paper_url,
        )
        logger.info(
            "[spider] %s 解析完成：%s 个题型 / %s 道题",
            self.paper_id,
            payload["stats"]["section_count"],
            payload["stats"]["question_count"],
        )
        return item

    def on_error(self, failure: Any):
        message = str(failure.value)
        logger.error("[spider] 抓取失败：%s", message)
        self._fail(f"抓取失败：{message}")
        return None

    def _fail(self, message: str) -> None:
        status.write(ok=False, paper_id=self.paper_id, url=self.paper_url, error=message)

    def _save_html(self, html: str) -> None:
        
        """
        落盘失败不影响抓取结果，所以只记 debug 日志。
        """
        try:
            self.html_path.parent.mkdir(parents=True, exist_ok=True)
            self.html_path.write_text(html, encoding="utf-8")
        except OSError:
            logger.debug("保存 HTML 失败", exc_info=True)

    @staticmethod
    def _detect_problem(response: Response) -> str | None:
        
        """
        把页面上能看出来的问题翻译成人话，返回 None 表示正常。

        组卷网不报错，只是不给内容，所以得自己按权限标记、登录墙、
        验证码页面这些特征去判，否则用户只会看到“没有解析出题目”。
        """
        
        html = response.text
        soup = None
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")
        except Exception:  # noqa: BLE001
            soup = None

        if soup is not None:
            can_view = soup.select_one("#can_view_paper_all")
            if can_view is not None and (can_view.get("value") or "").lower() not in ("true", "1"):
                return "该试卷需要更高权限才能查看（组卷网会员/下载券），当前账号无权访问"

            if soup.select_one(".exam-item__opt .item.no-login"):
                return "登录态已失效，请重新运行登录（登录菜单第 2 项）"

            if not soup.select_one(".exam-list .tk-quest-item.quesroot") and not soup.select_one(
                ".exam-analyze"
            ):
                return "页面里没有题目内容，可能需要验证码或账号被限制，请稍后重试"

            if soup.select_one(".exam-list"):
                return None

        # 拿不到结构化特征时退回按关键字认，覆盖风控页和登录页
        lowered = html.lower()
        for keyword, message in (
            ("验证码", "站点要求输入验证码，请在浏览器中打开该试卷完成验证后重试"),
            ("访问过于频繁", "访问过于频繁，已被站点临时限制，请稍后再试"),
            ("请登录", "登录态已失效，请重新登录"),
            ("无权查看", "当前账号无权查看该试卷"),
        ):
            if keyword in lowered and not soup.select_one(".exam-list"):
                return message
        return None

    @staticmethod
    def _normalize_url(url: str | None, paper_id: str | None) -> str:
        
        """
        命令行可能传网址，也可能只传试卷编号，这里统一成详情页网址。
        """
        raw = (url or "").strip() or (paper_id or "").strip()
        try:
            return normalize_paper_url(raw)
        except ValueError as exc:
            raise PaperError(str(exc)) from exc


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")
