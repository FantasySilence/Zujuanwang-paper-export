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
USER_API = "https://zujuan.xkw.com/zujuan-api/user"
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
                # ------ 用 APIRequestContext 直接请求，不依赖当前页面停在哪个域名 ------ #
                response = context.request.get(f"{USER_API}?t={int(time.time() * 1000)}")
                logged_in, name = _parse_user_script(response.text())
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
    """
    
    from playwright.sync_api import sync_playwright

    paths.ensure_dirs()

    print("即将打开浏览器窗口，请按下面步骤操作：")
    print("  1. 在窗口里点右上角「登录」（没有自动弹出的话）")
    print("  2. 用你的组卷网账号完成扫码 / 账号密码登录")
    print("  3. 登录成功后不用关闭浏览器，脚本会自动检测并保存登录态")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
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
        try:
            # ------ 轮询用户接口，比监听页面跳转稳：扫码、账号密码、换页都能覆盖 ------ #
            while time.time() < deadline:
                if page.is_closed():
                    break
                try:
                    response = context.request.get(f"{USER_API}?t={int(time.time() * 1000)}")
                    logged_in, user_name = _parse_user_script(response.text())
                # ------ noqa: BLE001 - 忽略瞬时网络错误 ------ #
                except Exception: 
                    logged_in = False
                if logged_in:
                    break
                now = time.time()
                if now - last_notice > 10:
                    remaining = int(deadline - now)
                    print(f"  等待登录中…（剩余 {remaining} 秒）")
                    last_notice = now
                time.sleep(2)

            if logged_in:
                # ----- 登录成功立刻存盘，不依赖用户主动关浏览器 ------ #
                context.storage_state(path=str(paths.AUTH_FILE))
                _write_meta(user_name=user_name)
                print(f"\n登录成功：{user_name or '已登录'}，登录态已保存到 .temp/auth/auth.json")
            else:
                print("\n没有检测到登录完成，登录态未更新。")
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass

    return AuthInfo(logged_in, user_name, "登录成功" if logged_in else "未完成登录")
