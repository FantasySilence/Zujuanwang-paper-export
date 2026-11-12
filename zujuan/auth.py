# =================================== #
# @Author: Fantasy_Silence            #
# @Time: 2026-11-12                   #
# @IDE: Visual Studio Code & PyCharm  #
# @Python: 3.9.7                      #
# =================================== #
# @Description: 登录态管理             #
# =================================== #

"""
组卷网需要登录才能看到完整试卷和答案解析，这里负责：

* 复用 ``.temp/auth/auth.json`` 里的登录态（Playwright storage_state）
* 首次运行自动从旧目录 ``.test/auth.json`` 迁移
* 交互式登录：打开有头浏览器，用户手动登录，脚本自动检测并保存
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import paths

HOME_URL = "https://zujuan.xkw.com/"
# 判断登录态的接口（页面内同源请求用相对路径，方便直接喂给 fetch）
PROBE_PATH = "/zujuan-api/user"
LOGIN_TIMEOUT_SECONDS = 300

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class AuthInfo:
    
    """
    登录态概况。
    """

    logged_in: bool
    user_name: str = ""
    message: str = ""


def meta_path() -> Path:
    return paths.AUTH_DIR / "auth_meta.json"


def ensure_auth_file() -> bool:
    
    """
    确保 ``.temp/auth/auth.json`` 存在（必要时从旧位置迁移）。
    """

    paths.ensure_dirs()
    if paths.AUTH_FILE.exists():
        return True
    legacy = paths.LEGACY_AUTH_FILE
    if legacy.exists():
        shutil.copy2(legacy, paths.AUTH_FILE)
        _write_meta(user_name="", note="migrated-from-.test")
        return True
    return False


def _write_meta(**data: Any) -> None:
    payload = {"saved_at": datetime.now().isoformat(timespec="seconds")}
    payload.update({k: v for k, v in data.items() if v is not None})
    try:
        meta_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def read_meta() -> dict[str, Any]:
    path = meta_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cookie_alive() -> bool:
    
    """
    只看本地 Cookie 是否过期，不联网。
    """

    if not paths.AUTH_FILE.exists():
        return False
    try:
        state = json.loads(paths.AUTH_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False

    now = time.time()
    tokens = {c.get("name"): c for c in state.get("cookies", []) if isinstance(c, dict)}
    # ------ 只认 user_token，其它 cookie 的过期时间不代表登录态 ------ #
    token = tokens.get("user_token")
    if token is None:
        return False
    expires = token.get("expires") or -1
    if expires and expires > 0 and expires < now:
        return False
    return True


def _parse_user_script(text: str) -> tuple[bool, str]:
    
    """
    解析 /zujuan-api/user 的返回，它是 JS 不是 JSON，只能正则捞。

    内容形如 ``var isvisitor=false,userinfo={"UserID":123,"UserName":"xkw_xxx",...}``
    """
    
    is_visitor = re.search(r"isvisitor\s*=\s*(true|false)", text)
    name = re.search(r'"UserName"\s*:\s*"([^"]*)"', text)
    logged_in = bool(is_visitor and is_visitor.group(1) == "false")
    return logged_in, (name.group(1) if name else "")


# 在页面里发同源请求，浏览器会自动带上当前最新的 cookie
_PROBE_JS = (f"async () => (await fetch('{PROBE_PATH}?t=' + Date.now(), "
             "{credentials: 'include'})).text()")


def _cookie_token(context: Any) -> str:
    
    """
    读当前浏览器里的 user_token，用来判断“登录动作有没有发生”。

    cookie 一变就说明登录完成了，这样可以立刻去复核，不用干等页面刷新。
    """
    
    try:
        for item in context.cookies():
            if item.get("name") == "user_token":
                return item.get("value") or ""
    except Exception:  # noqa: BLE001
        pass
    return ""


def _probe_login(page: Any, attempts: int = 3) -> tuple[bool, str]:
    
    """
    在页面内查一次登录态，返回 (是否已登录, 用户名)。

    不能用 context.request.get()：那个请求上下文拿的是创建时的 cookie 快照，
    用户登录后它看到的还是旧的匿名态，所以永远检测不到“登录成功”。
    页面内 fetch 走浏览器当前的 cookie，但页面本身也要重新加载过才能看到新状态。
    """
    
    for index in range(attempts):
        try:
            # ------ 还停在登录页（非组卷网域名）时先不查，避免跨域失败 ------ #
            if not page.url.startswith("https://zujuan.xkw.com"):
                return False, ""
            return _parse_user_script(page.evaluate(_PROBE_JS))
        except Exception:  # noqa: BLE001 - 页面正在跳转时执行上下文会失效，稍后重试
            if index + 1 >= attempts:
                return False, ""
            page.wait_for_timeout(600)
    return False, ""


def _ensure_probe_page(context: Any, probe: Any) -> Any:
    
    """
    拿到用于检测登录态的标签页。

    单独开一个页而不是复用用户正在操作的页，是因为确认时要重新加载，
    不能把用户正在填的登录表单刷掉。
    """
    
    try:
        if probe is not None and not probe.is_closed():
            return probe
        page = context.new_page()
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30_000)
        return page
    except Exception:  # noqa: BLE001
        return None


def _reload_probe(page: Any) -> None:
    
    """
    让探测页重新拿一次登录态。

    这里用 goto 而不是 reload：reload 会沿用页面已有的缓存/状态，
    实测登录后仍返回旧的匿名结果；重新导航才会按新 cookie 取。
    """
    
    try:
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30_000)
        # 页面加载完还会自己跳转一下，稍等一下再发探测请求
        page.wait_for_timeout(800)
    except Exception:  # noqa: BLE001
        pass


def check_login() -> AuthInfo:
    
    """
    打开浏览器校验登录态是否仍然有效。
    """
    
    if not ensure_auth_file():
        return AuthInfo(False, "", "还没有登录，请先执行登录")

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                storage_state=str(paths.AUTH_FILE),
                locale="zh-CN",
                user_agent=_UA,
            )
            try:
                page = context.new_page()
                page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(800)
                logged_in, name = _probe_login(page)
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        return AuthInfo(False, "", f"校验登录态失败：{exc}")

    if logged_in:
        _write_meta(user_name=name)
        return AuthInfo(True, name, "登录态有效")
    return AuthInfo(False, "", "登录态已失效，请重新登录")


def interactive_login(timeout_seconds: int = LOGIN_TIMEOUT_SECONDS) -> AuthInfo:
   
    """
    打开有头浏览器让用户登录，检测成功后保存登录态。

    这里刻意不加载旧登录态：带着旧 cookie 打开的话，“已登录”可能还是上一个账号，
    换号时会被误判成登录成功；从匿名状态开始，检测到就一定是这次真的登上了。
    """
    
    from playwright.sync_api import sync_playwright

    paths.ensure_dirs()

    print("即将打开浏览器窗口，请按下面步骤操作：")
    print("  1. 在窗口里点右上角「登录」（没有自动弹出的话）")
    print("  2. 用你的组卷网账号完成扫码 / 账号密码登录")
    print("  3. 登录成功后不用关闭浏览器，脚本会自动检测并保存登录态")
    print("（会额外开一个标签页专门检测登录状态，不用管它）")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        # ------ 不带 storage_state：从匿名态开始，检测到登录就一定是这次登上的 ------ #
        context = browser.new_context(
            locale="zh-CN",
            user_agent=_UA,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        try:
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        # ------ noqa: BLE001 - 首页打不开也让用户自己操作 ------ #
        except Exception:
            pass

        # ------ 尽量自动点开登录入口，失败就交给用户 ------ #
        for selector in (".login-btn", "a[href*='login']", "text=登录"):
            try:
                page.click(selector, timeout=1500)
                break
            except Exception:  # noqa: BLE001
                continue

        deadline = time.time() + timeout_seconds
        logged_in = False
        user_name = ""
        last_notice = 0.0
        last_confirm = time.time()
        # 起点是匿名态，正常情况下这里应该是空
        baseline_token = _cookie_token(context)
        probe = None
        try:
            while time.time() < deadline:
                if page.is_closed():
                    break
                now = time.time()
                token = _cookie_token(context)
                # ------ cookie 变了说明登录动作完成；没变也每 20 秒复核一次 ------ #
                if (token and token != baseline_token) or now - last_confirm >= 20:
                    probe = _ensure_probe_page(context, probe)
                    if probe is not None:
                        # 页面不重新导航的话，看到的还是登录前的状态
                        _reload_probe(probe)
                        logged_in, user_name = _probe_login(probe)
                    last_confirm = now
                    if logged_in:
                        break
                if now - last_notice > 10:
                    remaining = int(deadline - now)
                    print(f"  等待登录中…（剩余 {remaining} 秒）")
                    last_notice = now
                time.sleep(1.5)

            if logged_in:
                # ----- 登录成功立刻存盘，不依赖用户主动关浏览器 ------ #
                context.storage_state(path=str(paths.AUTH_FILE))
                _write_meta(user_name=user_name)
                print(f"\n登录成功：{user_name or '已登录'}，登录态已保存到 .temp/auth/auth.json")
            elif page.is_closed():
                print("\n浏览器窗口已关闭，登录态未更新。")
            else:
                print("\n等待超时，没有检测到登录完成，登录态未更新。")
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass

    return AuthInfo(logged_in, user_name, "登录成功" if logged_in else "未完成登录")
