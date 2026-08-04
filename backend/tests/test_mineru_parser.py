"""MinerU 精准解析 API 客户端测试。

所有外部 HTTP 调用均 mock，不依赖真实 token / 网络。
"""

import io
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.mineru_parser import MinerUClient, MinerUParseError, MinerUTimeoutError


@pytest.fixture
def client():
    with patch("services.mineru_parser.settings.MINERU_ENABLED", True):
        yield MinerUClient(
            token="test-token",
            base_url="https://mineru.net/api/v4",
            model_version="vlm",
            timeout=10,
            poll_interval=0.01,
        )


@pytest.fixture
def sample_zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("full.md", "# 简历\n\n张三\n北京大学")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_enabled_requires_token_and_setting():
    """enabled = MINERU_ENABLED + token 非空。"""
    with patch("services.mineru_parser.settings.MINERU_ENABLED", False):
        # 有 token 但开关关闭
        client = MinerUClient(token="abc")
        assert not client.enabled

    with patch("services.mineru_parser.settings.MINERU_ENABLED", True), \
         patch("services.mineru_parser.settings.MINERU_TOKEN", ""):
        # 开关打开但无 token（显式 token 为空，且环境 MINERU_TOKEN 也为空）
        client = MinerUClient(token="")
        assert not client.enabled

        # 同时满足
        client = MinerUClient(token="abc")
        assert client.enabled


@pytest.mark.asyncio
async def test_parse_file_when_disabled_returns_none():
    """未启用时直接返回 None，调用方 fallback。"""
    client = MinerUClient(token="")
    result = await client.parse_file("/fake/resume.pdf")
    assert result is None


@pytest.mark.asyncio
async def test_parse_file_success(client, sample_zip_bytes, tmp_path):
    """完整流程：申请上传链接 → PUT 上传 → 轮询 done → 下载 zip → 提取 markdown。"""
    resume_file = tmp_path / "resume.pdf"
    resume_file.write_text("fake pdf content")

    with patch.object(client, "_request_upload_url", new=AsyncMock(return_value=("batch-123", "https://oss.example.com/upload/1"))) as mock_request:
        with patch.object(client, "_upload_file", new=AsyncMock(return_value=None)) as mock_upload:
            with patch.object(
                client,
                "_poll_batch_result",
                new=AsyncMock(return_value={"full_zip_url": "https://cdn.example.com/result.zip"}),
            ) as mock_poll:
                with patch.object(client, "_download_and_extract_markdown", new=AsyncMock(return_value="# 简历\n\n张三\n北京大学")) as mock_download:
                    result = await client.parse_file(str(resume_file))

    assert result == "# 简历\n\n张三\n北京大学"
    mock_request.assert_awaited_once_with("resume.pdf")
    mock_upload.assert_awaited_once_with("https://oss.example.com/upload/1", str(resume_file))
    mock_poll.assert_awaited_once_with("batch-123")
    mock_download.assert_awaited_once_with({"full_zip_url": "https://cdn.example.com/result.zip"})


@pytest.mark.asyncio
async def test_request_upload_url_api_error(client):
    """MinerU 接口返回非 0 code 时抛 MinerUParseError。"""
    async def mock_post(url, **kwargs):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {"code": -10002, "msg": "参数错误"}
        return resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = MagicMock()
        instance.post = AsyncMock(side_effect=mock_post)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance

        with pytest.raises(MinerUParseError, match="参数错误"):
            await client._request_upload_url("resume.pdf")


@pytest.mark.asyncio
async def test_poll_batch_result_failed(client):
    """MinerU 返回 failed 状态时抛 MinerUParseError。"""
    async def mock_get(url, **kwargs):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {
            "code": 0,
            "data": {
                "batch_id": "batch-123",
                "extract_result": [
                    {"state": "failed", "err_msg": "文件格式不支持"}
                ],
            },
        }
        return resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = MagicMock()
        instance.get = AsyncMock(side_effect=mock_get)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance

        with pytest.raises(MinerUParseError, match="文件格式不支持"):
            await client._poll_batch_result("batch-123")


@pytest.mark.asyncio
async def test_poll_batch_result_timeout(client):
    """轮询超时时抛 MinerUTimeoutError。"""
    async def mock_get(url, **kwargs):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {
            "code": 0,
            "data": {
                "batch_id": "batch-123",
                "extract_result": [{"state": "running"}],
            },
        }
        return resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = MagicMock()
        instance.get = AsyncMock(side_effect=mock_get)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance

        client.timeout = 0.05
        with pytest.raises(MinerUTimeoutError):
            await client._poll_batch_result("batch-123")


@pytest.mark.asyncio
async def test_download_and_extract_markdown(client, sample_zip_bytes):
    """下载 zip 并正确提取 full.md。"""
    async def mock_get(url, **kwargs):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.content = sample_zip_bytes
        return resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = MagicMock()
        instance.get = AsyncMock(side_effect=mock_get)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance

        result = await client._download_and_extract_markdown(
            {"full_zip_url": "https://cdn.example.com/result.zip"}
        )
        assert result == "# 简历\n\n张三\n北京大学"
