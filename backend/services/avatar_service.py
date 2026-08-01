"""T26: 头像上传服务 — 照片安全。

职责：
- save_avatar: 安全保存头像图片（白名单 MIME / 5MB 限制 / PIL 校验 / UUID 文件名）
- 返回头像 URL 路径

安全措施：
1. MIME 白名单: image/jpeg, image/png, image/webp
2. 文件大小限制: 5MB
3. PIL 校验: 打开图片验证是真实图片（防伪造 MIME）
4. UUID 文件名: 防路径遍历
5. 扩展名白名单: .jpg/.jpeg/.png/.webp

设计依据：
- plan.md T26: 头像上传（白名单/MIME/5MB/PIL/uuid）
"""

import logging
import os
import uuid
from pathlib import Path

from fastapi import UploadFile, HTTPException, status
from PIL import Image

logger = logging.getLogger(__name__)

# ── 安全校验常量 ──
_AVATAR_MAX_SIZE = 5 * 1024 * 1024  # 5MB
_AVATAR_ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp"}
_AVATAR_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_AVATAR_UPLOAD_DIR = "uploads/avatars"


def _ensure_upload_dir() -> Path:
    """确保头像上传目录存在。"""
    upload_dir = Path(_AVATAR_UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def _validate_mime(file: UploadFile) -> str:
    """校验 MIME 类型。"""
    content_type = file.content_type or ""
    if content_type not in _AVATAR_ALLOWED_MIMES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"不支持的头像格式: {content_type}，仅支持 JPEG/PNG/WebP",
        )
    return content_type


def _validate_size(data: bytes) -> None:
    """校验文件大小。"""
    if len(data) > _AVATAR_MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"头像文件过大（{len(data)} bytes），最大 5MB",
        )


def _validate_image(data: bytes) -> None:
    """用 PIL 校验是真实图片。"""
    try:
        from io import BytesIO
        img = Image.open(BytesIO(data))
        img.verify()  # 验证但不加载像素数据
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="头像文件不是有效的图片",
        ) from e


def _get_extension(content_type: str) -> str:
    """根据 MIME 类型获取扩展名。"""
    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    return ext_map.get(content_type, ".jpg")


async def save_avatar(file: UploadFile, resume_id: int) -> str:
    """安全保存头像图片。

    流程：
    1. MIME 白名单校验
    2. 读取文件内容 + 大小校验
    3. PIL 真实图片校验
    4. UUID 文件名（防路径遍历）
    5. 保存到 uploads/avatars/

    Returns:
        avatar_url: 头像访问路径（如 /uploads/avatars/uuid.jpg）

    Raises:
        HTTPException 422: MIME 不支持 / 不是有效图片
        HTTPException 413: 文件过大
    """
    # 1. MIME 校验
    content_type = _validate_mime(file)

    # 2. 读取 + 大小校验
    data = await file.read()
    _validate_size(data)

    # 3. PIL 校验
    _validate_image(data)

    # 4. UUID 文件名
    ext = _get_extension(content_type)
    filename = f"{uuid.uuid4().hex}{ext}"

    # 5. 保存
    upload_dir = _ensure_upload_dir()
    file_path = upload_dir / filename
    file_path.write_bytes(data)

    avatar_url = f"/{_AVATAR_UPLOAD_DIR}/{filename}"
    logger.info(
        "Saved avatar: resume=%d, file=%s, size=%d bytes, mime=%s",
        resume_id, filename, len(data), content_type,
    )
    return avatar_url
