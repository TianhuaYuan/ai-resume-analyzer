"""Docling 本地版面解析（MIT License，LF AI & Data）。

A2：MinerU 在线 API 不可用时的本地版面感知解析兜底——布局分析
（DocLayNet）+ 表格结构恢复（TableFormer）+ 阅读顺序，输出 markdown
（表格保留为 markdown 表格）。

设计：
- 懒加载：首次调用才实例化 DocumentConverter（模型首次下载 ~500MB，
  常驻内存 ~600MB，2C4G 上避免启动即占用）
- do_ocr=False：扫描件走 RapidOCR（`utils/ocr_parser.py`），
  不常驻多套 OCR 引擎；文本型 PDF 不需要 OCR
- 异步包装：converter.convert 是同步阻塞（CPU 推理），用
  asyncio.to_thread 避免阻塞事件循环
- 优雅降级：未安装 / 模型加载失败 / 转换异常 → 返回 None，
  调用方回落 pdfplumber

参考：https://github.com/docling-project/docling
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


_converter = None


def _get_converter():
    """懒加载 Docling DocumentConverter（单例）。"""
    global _converter
    if _converter is None:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions

        # PDF 管线：布局分析 + 表格结构，扫描件 OCR 交给 RapidOCR
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False
        pipeline_options.do_table_structure = True

        _converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            },
        )
    return _converter


async def parse_pdf_with_docling(path: str) -> str | None:
    """用 Docling 解析 PDF，返回 markdown 文本（含表格/阅读顺序）。

    Args:
        path: PDF 文件路径

    Returns:
        markdown 文本，失败/不可用返回 None（调用方回落 pdfplumber）
    """
    try:
        converter = _get_converter()
        result = await asyncio.to_thread(converter.convert, path)
        text = result.document.export_to_markdown()
        return text.strip() or None
    except ImportError:
        logger.warning(
            "Docling 未安装（pip install docling），本地版面解析不可用: %s", path
        )
        return None
    except Exception as e:
        logger.warning("Docling 解析失败（降级返回 None）: %s: %s", path, e)
        return None
