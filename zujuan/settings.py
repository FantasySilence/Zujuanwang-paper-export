# =================================== #
# @Author: Fantasy_Silence            #
# @Time: 2026-11-12                   #
# @IDE: Visual Studio Code & PyCharm  #
# @Python: 3.9.7                      #
# =================================== #
# @Description: Scrapy 配置。          #
# =================================== #
"""
几个关键决定：
* 所有 http(s) 请求都走 Playwright 下载处理器，因为正文是 JS 渲染出来的
* 开启 HTTP 缓存，同一份试卷重复导出时直接复用 .temp/httpcache 里的 HTML
* 并发压到 1，组卷网的风控对连续请求比较敏感
"""

from __future__ import annotations

from . import paths

BOT_NAME = "zujuan"

SPIDER_MODULES = ["zujuan.spiders"]
NEWSPIDER_MODULE = "zujuan.spiders"

paths.ensure_dirs()

# 抓取行为
ROBOTSTXT_OBEY = False
CONCURRENT_REQUESTS = 2
# 同一域名只跑一个请求，慢一点但稳
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 0.5
RANDOMIZE_DOWNLOAD_DELAY = True
DOWNLOAD_TIMEOUT = 120
RETRY_TIMES = 1
# 登录态由 Playwright 的 storage_state 提供，这里的 Cookie 中间件基本不参与
COOKIES_ENABLED = True
TELNETCONSOLE_ENABLED = False
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# Playwright：自实现的下载处理器，只接管 meta 里标了 playwright 的请求
DOWNLOAD_HANDLERS = {
    "http": "zujuan.playwright_handler.PlaywrightDownloadHandler",
    "https": "zujuan.playwright_handler.PlaywrightDownloadHandler",
}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

# 下面几项由下载处理器直接读取
PLAYWRIGHT_HEADLESS = True
PLAYWRIGHT_TIMEOUT = 60_000
PLAYWRIGHT_STORAGE_STATE = str(paths.AUTH_FILE)
# domcontentloaded 之后再多等一会儿，让题目内容渲染完
PLAYWRIGHT_SETTLE_MS = 1200
# 图片和字体在生成 Word 时单独下载，浏览器里没必要加载
PLAYWRIGHT_BLOCK_RESOURCES = ("image", "media", "font")

# 缓存：0 表示永不过期，试卷内容变了用 --no-cache 强刷
HTTPCACHE_ENABLED = True
HTTPCACHE_DIR = str(paths.HTTPCACHE_DIR)
HTTPCACHE_POLICY = "scrapy.extensions.httpcache.DummyPolicy"
HTTPCACHE_EXPIRATION_SECS = 0
HTTPCACHE_IGNORE_HTTP_CODES = [403, 404, 429, 500, 502, 503]
HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

ITEM_PIPELINES = {
    "zujuan.pipelines.PaperJsonPipeline": 300,
}

# 日志每次覆盖，排查问题时看的就是最近一次
LOG_LEVEL = "INFO"
LOG_FILE = str(paths.LOG_DIR / "scrapy.log")
LOG_FILE_APPEND = False
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR_TIMEOUT = 30

FEED_EXPORT_ENCODING = "utf-8"
