# ============================================================== #
# @Author: Fantasy_Silence                                       #
# @Time: 2026-11-12                                              #
# @IDE: Visual Studio Code & PyCharm                             #
# @Python: 3.9.7                                                 #
# ============================================================== #
# @Description: 图片插入：尺寸换算 + 兼容性修补。
# ============================================================== #
from __future__ import annotations

from pathlib import Path
from typing import Any

from docx.image.image import Image as DocxImage
from docx.shared import Cm, Pt

from ..images import ImageCache
from .options import GRAY, IMAGE_PRINT_SCALE, USABLE_WIDTH_CM, DocxOptions


_JFIF_APP0 = bytes.fromhex("FFE000104A46494600010100000100010000")


def add_image_run(
    paragraph: Any,
    run_data: dict[str, Any],
    options: DocxOptions,
    cache: ImageCache,
) -> None:
    local = cache.local_path(run_data.get("src", ""))
    # ------ 图片单独下载，失败就留一行灰字，不让整篇文档生成不下去 ------ #
    if local is None:
        _placeholder(paragraph, "[图片缺失]")
        return
    # ------ python-docx 认不出的 JPEG 这里会补头重存一份 ------ #
    path = _docx_safe_image(local)
    if path is None:
        _placeholder(paragraph, "[图片无法插入]")
        return
    try:
        width_cm = _image_width_cm(path, run_data.get("width"))
        paragraph.add_run().add_picture(str(path), width=Cm(width_cm))
    except Exception:  # noqa: BLE001 - 个别格式 python-docx 不支持
        _placeholder(paragraph, "[图片无法插入]")


def _placeholder(paragraph: Any, text: str) -> None:
    """图片放不进去时留的一行灰字，别让整篇文档生成不下去。"""
    run = paragraph.add_run(text)
    run.font.size = Pt(9)
    run.font.color.rgb = GRAY


def _docx_safe_image(path: Path) -> Path | None:
    
    """
    返回一个 python-docx 一定认得的图片路径，认不出时返回 None。

    python-docx 解析 JPEG 时只认带 JFIF(APP0) 或 Exif(APP1) 头的文件；组卷网上
    有一部分照片是直接从 ICC(APP2) 开头的，会被判成“不支持的图片格式”，于是整
    张图变成一行灰字。这类文件补一段标准 JFIF 头就能正常插入，像素数据完全不动。
    修好的副本写回图片缓存目录，同一张图只处理一次。
    """
    
    try:
        DocxImage.from_file(str(path))
        return path
    except Exception:  # noqa: BLE001 - 落到下面按 JPEG 修补
        pass

    try:
        data = path.read_bytes()
    except OSError:
        return None
    # ------ 只处理真正缺 JFIF/Exif 头的 JPEG，别的格式交给上层报错 ------ #
    if not data.startswith(b"\xff\xd8") or data.startswith(b"\xff\xd8\xff\xe0"):
        return None

    patched = path.with_name(f"{path.stem}_docx.jpg")
    try:
        if not patched.exists():
            patched.write_bytes(data[:2] + _JFIF_APP0 + data[2:])
        DocxImage.from_file(str(patched))
        return patched
    except Exception:  # noqa: BLE001
        patched.unlink(missing_ok=True)
        return None


def _image_width_cm(path: Path, width_px: int | None) -> float:
    
    """
    网页上的展示宽度换算成打印宽度；没有展示宽度时按原图尺寸并限宽。
    """
    
    max_cm = USABLE_WIDTH_CM - 0.4
    # ------ 浏览器按 96dpi 换算 CSS 像素，这里保持一致 ------ #
    if width_px and width_px > 0:
        return round(min(width_px / 96 * 2.54 * IMAGE_PRINT_SCALE, max_cm), 2)
    try:
        image = DocxImage.from_file(str(path))
        natural = image.px_width / 96 * 2.54
        return round(min(natural, max_cm), 2)
    except Exception:  # noqa: BLE001
        return min(10.0, max_cm)
