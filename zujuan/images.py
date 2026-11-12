# =================================== #
# @Author: Fantasy_Silence            #
# @Time: 2026-11-12                   #
# @IDE: Visual Studio Code & PyCharm  #
# @Python: 3.9.7                      #
# =================================== #
# @Description: 题目图片下载与本地缓存  #
# =================================== #
"""
图片不需要登录态，但同一份试卷重复导出时没必要再联网，
所以统一落盘到 .temp/images，用 URL 的 SHA1 做文件名。
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .paths import IMAGE_DIR

# 扩展名以响应头为准，不信任 URL 里的后缀
_EXT_BY_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
}

# 部分图片站点会校验 Referer，伪装成从试卷页点过来的
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://zujuan.xkw.com/",
}


class ImageCache:
    """按 URL 缓存图片，返回本地路径。"""

    def __init__(self, directory: Path | None = None, timeout: int = 30) -> None:
        self.directory = Path(directory or IMAGE_DIR)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        # 同一份试卷里图片可能重复引用，内存里也挡一层
        self._memory: dict[str, Path | None] = {}
        self.downloaded = 0
        self.cached = 0
        self.failed = 0

    def local_path(self, url: str) -> Path | None:
        if not url:
            return None
        if url in self._memory:
            return self._memory[url]

        key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
        # 磁盘上已有同名文件就直接复用，不再发请求
        for existing in self.directory.glob(f"{key}.*"):
            if existing.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
                self.cached += 1
                self._memory[url] = existing
                return existing

        path = self._download(url, key)
        self._memory[url] = path
        return path

    def _download(self, url: str, key: str) -> Path | None:
        try:
            response = requests.get(url, headers=_HEADERS, timeout=self.timeout, stream=True)
            response.raise_for_status()
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            suffix = _EXT_BY_TYPE.get(content_type)
            if suffix is None:
                suffix = Path(urlsplit(url).path).suffix.lower() or mimetypes.guess_extension(content_type) or ".png"
                if suffix == ".jpe":
                    suffix = ".jpg"
            path = self.directory / f"{key}{suffix}"
            with path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=16384):
                    handle.write(chunk)
            # 服务端偶尔回 200 但内容为空，删掉当作下载失败
            if path.stat().st_size == 0:
                path.unlink(missing_ok=True)
                self.failed += 1
                return None
            self.downloaded += 1
            return path
        except Exception:  # noqa: BLE001 - 单张图片失败不应该中断整份试卷的导出
            self.failed += 1
            return None

    def stats(self) -> dict[str, int]:
        return {"downloaded": self.downloaded, "cached": self.cached, "failed": self.failed}
