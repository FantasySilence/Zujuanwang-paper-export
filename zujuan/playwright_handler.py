# =========================================================#
# @Author: Fantasy_Silence              ====================#
# @Time: 2026-11-12                    ====================#
# @IDE: Visual Studio Code & PyCharm   ====================#
# @Python: 3.9.7                       ====================#
# ===================================# =====================
# @Description: 基于 Playwright 的 Scrapy 下载处理器。
# =================================== =====================#
"""
站点正文依赖 JS 渲染，因此把 http(s) 请求交给 Chromium 打开，再把渲染后的
HTML 交回 Scrapy 解析。

为什么单独开线程？
    Windows 上 Twisted 的 AsyncioSelectorReactor 使用的是 ``SelectorEventLoop``，
    它不支持 ``subprocess_exec``，而 Playwright 需要启动 node 驱动子进程。
    所以这里给 Playwright 单独建一个线程 + ``ProactorEventLoop``，
    浏览器在该循环里长期存活，主线程只把协程提交过去，互不干扰。

请求 meta 支持的开关：

``playwright``
    必填，``True`` 表示走 Playwright。
``playwright_wait_for``
    额外等待的 CSS 选择器，出现后才算加载完成。
``playwright_expand_answers``
    逐题展开“答案与解析”，把答案图片写入 DOM 后再取页面 HTML。
``playwright_screenshot``
    截图保存路径（调试用）。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import threading
from typing import Any

from scrapy import Request
from scrapy.http import HtmlResponse, Response

try:  # Scrapy >= 2.13 改了 HTTP/1.1 处理器的名字
    from scrapy.core.downloader.handlers.http11 import HTTP11DownloadHandler as _BaseHandler
except ImportError:  # pragma: no cover - 兼容旧版本
    from scrapy.core.downloader.handlers.http import HTTPDownloadHandler as _BaseHandler  # type: ignore

logger = logging.getLogger(__name__)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 无头 Chromium 默认带明显的自动化特征，先把几个显眼的藏掉
_ANTI_DETECT_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


class _PlaywrightThread:
    """一个长期运行的线程，内部跑支持子进程的事件循环。

    Windows 上 Twisted 用的 SelectorEventLoop 不支持 subprocess_exec，
    而 Playwright 要拉起 node 驱动，所以浏览器单独放这个循环里跑。
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="playwright-loop", daemon=True)
        self._thread.start()
        # 等循环真正跑起来再返回，否则第一个 submit 会扑空
        self._ready.wait(timeout=15)
        if self._error is not None:
            raise RuntimeError(f"Playwright 事件循环启动失败：{self._error}") from self._error

    @property
    def started(self) -> bool:
        return self._thread is not None

    def _run(self) -> None:
        try:
            if os.name == "nt":
                # Proactor 才支持子进程；其它平台默认循环就可以
                loop: asyncio.AbstractEventLoop = asyncio.ProactorEventLoop()
            else:
                loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
        except BaseException as exc:  # noqa: BLE001
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                # 清掉残留任务并让子进程管道正常关闭，否则退出时会刷一屏报错
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.run_until_complete(asyncio.sleep(0))
            except Exception:  # noqa: BLE001
                pass
            finally:
                try:
                    loop.close()
                except Exception:  # noqa: BLE001
                    pass

    def submit(self, coro: Any) -> concurrent.futures.Future:
        if self._loop is None:
            raise RuntimeError("Playwright 事件循环尚未启动")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self, timeout: float = 10.0) -> None:
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None


class PlaywrightDownloadHandler(_BaseHandler):
    """把 ``meta['playwright']`` 的请求交给 Playwright，其余走原逻辑。"""

    def __init__(self, crawler: Any) -> None:
        super().__init__(crawler)
        settings = crawler.settings
        self._crawler = crawler

        self._thread = _PlaywrightThread()
        self._playwright = None
        self._browser = None
        self._context = None
        self._lock: asyncio.Lock | None = None

        self.headless = bool(settings.getbool("PLAYWRIGHT_HEADLESS", True))
        self.timeout = int(settings.getint("PLAYWRIGHT_TIMEOUT", 60_000))
        self.settle_ms = int(settings.getint("PLAYWRIGHT_SETTLE_MS", 1200))
        self.storage_state = settings.get("PLAYWRIGHT_STORAGE_STATE") or None
        self.block_resources = tuple(settings.getlist("PLAYWRIGHT_BLOCK_RESOURCES") or ())

    @classmethod
    def from_crawler(cls, crawler: Any) -> "PlaywrightDownloadHandler":
        return cls(crawler)

    async def download_request(self, request: Request) -> Response:
        # 没标 playwright 的请求还是走 Scrapy 原生 HTTP，省一次浏览器开销
        if not request.meta.get("playwright"):
            return await super().download_request(request)

        try:
            if not self._thread.started:
                self._thread.start()
            # 协程跨线程提交，主线程这边只等结果
            future = self._thread.submit(self._fetch(request))
            return await asyncio.wrap_future(future)
        except Exception as exc:  # noqa: BLE001 - 统一转成 Response 交给重试中间件
            logger.error("[playwright] 打开页面失败 %s：%s", request.url, exc)
            return HtmlResponse(
                url=request.url,
                status=599,
                body=b"",
                encoding="utf-8",
                request=request,
                flags=["playwright-error"],
            )

    async def close(self) -> None:
        if self._thread.started:
            try:
                future = self._thread.submit(self._shutdown())
                await asyncio.wait_for(asyncio.wrap_future(future), timeout=20)
            except Exception:  # noqa: BLE001
                logger.debug("[playwright] 关闭浏览器失败", exc_info=True)
            self._thread.stop()
        await super().close()

    async def _ensure_context(self) -> Any:
        if self._context is not None:
            return self._context
        if self._lock is None:
            # 锁要在工作循环里创建，不能跨事件循环复用
            self._lock = asyncio.Lock()

        async with self._lock:
            if self._context is not None:
                return self._context

            from playwright.async_api import async_playwright

            logger.info("[playwright] 启动 Chromium（headless=%s）", self.headless)
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--lang=zh-CN",
                ],
            )

            context_kwargs: dict[str, Any] = {
                "user_agent": _DEFAULT_UA,
                "locale": "zh-CN",
                "timezone_id": "Asia/Shanghai",
                "viewport": {"width": 1440, "height": 900},
            }
            # 登录态就是这一步带进去的，没有它拿到的试卷是残缺的
            if self.storage_state:
                context_kwargs["storage_state"] = self.storage_state

            self._context = await self._browser.new_context(**context_kwargs)
            self._context.set_default_timeout(self.timeout)
            await self._context.add_init_script(_ANTI_DETECT_JS)
            return self._context

    async def _shutdown(self) -> None:
        for attr in ("_context", "_browser", "_playwright"):
            obj = getattr(self, attr, None)
            if obj is None:
                continue
            try:
                await obj.close()
            except Exception:  # noqa: BLE001 - 关闭失败不影响已抓到的数据
                logger.debug("[playwright] 关闭 %s 失败", attr, exc_info=True)
            setattr(self, attr, None)
        # 给驱动子进程一点时间退出，避免管道被强制关闭
        await asyncio.sleep(0.3)

    async def _fetch(self, request: Request) -> Response:
        context = await self._ensure_context()
        page = await context.new_page()

        # 图片/字体不阻塞渲染，反正后面由 docx 阶段单独下载
        if self.block_resources:
            blocked = set(self.block_resources)

            async def _route(route: Any) -> None:
                try:
                    if route.request.resource_type in blocked:
                        await route.abort()
                    else:
                        await route.continue_()
                except Exception:  # noqa: BLE001
                    pass

            await page.route("**/*", _route)

        try:
            # 只等 DOM，站点的图片懒加载会拖到 load 很久
            response = await page.goto(
                request.url, wait_until="domcontentloaded", timeout=self.timeout
            )
            status = response.status if response is not None else 200

            wait_for = request.meta.get("playwright_wait_for")
            if wait_for:
                # 默认 attached：目标元素可能是隐藏域，等 visible 会白等到超时
                wait_state = request.meta.get("playwright_wait_state", "attached")
                try:
                    await page.wait_for_selector(wait_for, state=wait_state, timeout=self.timeout)
                except Exception:  # noqa: BLE001 - 结构变化时仍尽量返回页面
                    logger.warning("[playwright] 等待 %s 超时：%s", wait_for, request.url)

            if self.settle_ms:
                await page.wait_for_timeout(self.settle_ms)

            # 答案解析要逐题点开才会出现在 DOM 里
            if request.meta.get("playwright_expand_answers"):
                await self._expand_answers(page, int(request.meta.get("playwright_answers_limit") or 0))

            # 取的是渲染后的 DOM，题面、表格、图片都在里面了
            html = await page.content()

            screenshot = request.meta.get("playwright_screenshot")
            if screenshot:
                try:
                    await page.screenshot(path=screenshot, full_page=True)
                except Exception:  # noqa: BLE001
                    logger.debug("[playwright] 截图失败", exc_info=True)
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass

        return HtmlResponse(
            url=request.url,
            status=status,
            body=html.encode("utf-8", errors="replace"),
            encoding="utf-8",
            request=request,
        )

    async def _expand_answers(self, page: Any, limit: int = 0) -> None:
        """逐题点击，把答案与解析图片展开到 DOM 里。

        ``limit`` > 0 时最多展开这么多题，避免一次消耗过多每日查看额度。
        """
        selector = ".exam-list .tk-quest-item.quesroot .wrapper.quesdiv"
        count = await page.eval_on_selector_all(selector, "els => els.length")
        if not count:
            return
        target = min(count, limit) if limit > 0 else count
        logger.info("[playwright] 展开 %d/%d 道题的答案解析", target, count)

        for index in range(target):
            try:
                # 用 JS 直接 click，题目可能被侧栏遮挡，locator 容易点不中
                await page.eval_on_selector_all(
                    selector,
                    f"els => {{const el = els[{index}]; if (el) el.click();}}",
                )
                # 答案图是点击后异步请求回来的，等一会儿再取 DOM
                await page.wait_for_timeout(900)
            except Exception:  # noqa: BLE001 - 单题失败不影响整体
                logger.debug("[playwright] 第 %d 题展开失败", index + 1, exc_info=True)
