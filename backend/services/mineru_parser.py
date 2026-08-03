"""MinerU 精准解析 API 客户端。

提供异步文件上传 → 轮询 → 下载 zip → 提取 markdown 的完整流程。
仅当配置启用且 token 有效时才会真正调用；否则 parse_file 返回 None，
由调用方 fallback 到本地解析器。

文档参考：https://mineru.net/api/docs
"""

import io
import logging
import zipfile
from pathlib import Path
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://mineru.net/api/v4"
DEFAULT_TIMEOUT = 300
DEFAULT_POLL_INTERVAL = 3.0


class MinerUParseError(Exception):
    """MinerU 解析失败或接口返回错误。"""


class MinerUTimeoutError(Exception):
    """轮询超时。"""


class MinerUClient:
    """MinerU 精准解析 API 客户端。

    支持单文件上传解析（通过 /api/v4/file-urls/batch 获取临时上传链接）。
    """

    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        model_version: str | None = None,
        timeout: int | None = None,
        poll_interval: float | None = None,
        enable_table: bool | None = None,
        enable_formula: bool | None = None,
        language: str | None = None,
    ) -> None:
        self.token = (token or settings.MINERU_TOKEN or "").strip()
        self.base_url = (base_url or settings.MINERU_BASE_URL or DEFAULT_BASE_URL).rstrip("/")
        self.model_version = model_version or settings.MINERU_MODEL_VERSION or "vlm"
        self.timeout = timeout or settings.MINERU_TIMEOUT or DEFAULT_TIMEOUT
        self.poll_interval = poll_interval or settings.MINERU_POLL_INTERVAL or DEFAULT_POLL_INTERVAL
        self.enable_table = enable_table if enable_table is not None else settings.MINERU_ENABLE_TABLE
        self.enable_formula = enable_formula if enable_formula is not None else settings.MINERU_ENABLE_FORMULA
        self.language = language or settings.MINERU_LANGUAGE or "ch"

    @property
    def enabled(self) -> bool:
        """配置开关 + token 非空才启用。"""
        return bool(settings.MINERU_ENABLED and self.token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def parse_file(self, file_path: str) -> str | None:
        """解析本地文件，返回 markdown 文本。

        Returns:
            成功：markdown 字符串
            未启用或失败：None（调用方应 fallback）

        Raises:
            MinerUParseError：MinerU 返回 failed 或接口错误
            MinerUTimeoutError：轮询超时
        """
        if not self.enabled:
            logger.debug("MinerU 未启用或缺少 token，跳过")
            return None

        path = Path(file_path)
        if not path.exists():
            logger.warning("MinerU 解析：文件不存在 %s", file_path)
            return None

        try:
            batch_id, upload_url = await self._request_upload_url(path.name)
            await self._upload_file(upload_url, file_path)
            result = await self._poll_batch_result(batch_id)
            return await self._download_and_extract_markdown(result)
        except MinerUParseError:
            raise
        except MinerUTimeoutError:
            raise
        except Exception:
            logger.exception("MinerU 解析异常，fallback 到本地解析")
            return None

    async def _request_upload_url(self, filename: str) -> tuple[str, str]:
        """申请批量上传链接，返回 (batch_id, upload_url)。"""
        url = f"{self.base_url}/file-urls/batch"
        payload: dict[str, Any] = {
            "files": [
                {
                    "name": filename,
                    "data_id": Path(filename).stem,
                }
            ],
            "model_version": self.model_version,
            "enable_table": self.enable_table,
            "enable_formula": self.enable_formula,
            "language": self.language,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 0:
            raise MinerUParseError(f"申请上传链接失败: {data.get('msg')} (code={data.get('code')})")

        batch_id = data["data"]["batch_id"]
        upload_urls = data["data"]["file_urls"]
        if not upload_urls:
            raise MinerUParseError("MinerU 未返回上传链接")

        return batch_id, upload_urls[0]

    async def _upload_file(self, upload_url: str, file_path: str) -> None:
        """PUT 上传原始文件到 OSS 临时链接。"""
        async with httpx.AsyncClient() as client:
            with open(file_path, "rb") as f:
                resp = await client.put(upload_url, content=f)
            if resp.status_code not in (200, 201):
                raise MinerUParseError(f"文件上传失败: HTTP {resp.status_code}")

    async def _poll_batch_result(self, batch_id: str) -> dict[str, Any]:
        """轮询批量解析结果，直到 done/failed 或超时。"""
        url = f"{self.base_url}/extract-results/batch/{batch_id}"
        elapsed = 0.0

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while elapsed < self.timeout:
                resp = await client.get(url, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()

                if data.get("code") != 0:
                    raise MinerUParseError(f"查询任务失败: {data.get('msg')} (code={data.get('code')})")

                result = data["data"]
                extract_result = result.get("extract_result")
                if isinstance(extract_result, list) and extract_result:
                    item = extract_result[0]
                elif isinstance(extract_result, dict):
                    item = extract_result
                else:
                    item = {}

                state = item.get("state", "")
                if state == "done":
                    return item
                if state == "failed":
                    raise MinerUParseError(f"MinerU 解析失败: {item.get('err_msg', '未知错误')}")

                await __import__("asyncio").sleep(self.poll_interval)
                elapsed += self.poll_interval

        raise MinerUTimeoutError(f"MinerU 解析轮询超时 ({self.timeout}s)")

    async def _download_and_extract_markdown(self, result: dict[str, Any]) -> str:
        """下载 zip 并提取 full.md。"""
        zip_url = result.get("full_zip_url")
        if not zip_url:
            raise MinerUParseError("MinerU 返回结果缺少 full_zip_url")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(zip_url)
            resp.raise_for_status()
            zip_bytes = resp.content

        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                # 优先读取 full.md；不存在则找任意 .md
                candidates = [name for name in zf.namelist() if name.lower().endswith(".md")]
                if not candidates:
                    raise MinerUParseError("ZIP 中未找到 markdown 文件")

                target = "full.md"
                if target not in candidates:
                    target = candidates[0]

                with zf.open(target) as md_file:
                    content = md_file.read().decode("utf-8", errors="replace")
                    return content.strip()
        except zipfile.BadZipFile as e:
            raise MinerUParseError(f"下载的 ZIP 文件损坏: {e}") from e


# 全局默认客户端实例（懒加载配置）
_default_client: MinerUClient | None = None


def get_mineru_client() -> MinerUClient:
    """获取默认 MinerU 客户端实例。"""
    global _default_client
    if _default_client is None:
        _default_client = MinerUClient()
    return _default_client


def reset_mineru_client(client: MinerUClient | None = None) -> None:
    """重置默认客户端，主要用于测试。"""
    global _default_client
    _default_client = client
