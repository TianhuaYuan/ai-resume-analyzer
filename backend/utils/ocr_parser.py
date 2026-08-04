"""扫描件简历 OCR — RapidOCR（PaddleOCR 模型 ONNX 轻量版）。

A2：pdfplumber 提取文本过短（疑似扫描件 PDF）时的本地 OCR 兜底。
RapidOCR 与 PaddleOCR 同一套模型（det + rec），onnxruntime 推理，
依赖 ~100MB，2C4G 服务器友好（用户拍板替代 paddlepaddle 方案）。

设计：
- 懒加载：首次调用才实例化引擎（模型下载/加载 ~10s），避免启动内存占用
- 优雅降级：未安装依赖 / 模型下载失败 / OCR 异常 → 返回 None，调用方保持原行为
- 部署注意：RapidOCR 首次实例化从 GitHub release 下载模型（det ~4.7MB + rec ~12MB），
  国内服务器如超时可预置模型文件到本地路径（det_model_path / rec_model_path 参数）

参考：https://github.com/RapidAI/RapidOCR
"""

import logging

logger = logging.getLogger(__name__)

# OCR 渲染分辨率（200 DPI 足够识别小字，又不至于太慢）
_OCR_RESOLUTION = 200


_engine = None


def _get_ocr_engine():
    """懒加载 RapidOCR 引擎（单例）。"""
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine


async def ocr_pdf(path: str) -> str | None:
    """扫描件 PDF 逐页 OCR，返回拼接文本。

    Args:
        path: PDF 文件路径

    Returns:
        OCR 识别文本（每行一条），失败/不可用返回 None
    """
    import pdfplumber

    try:
        engine = _get_ocr_engine()
        parts: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                # pdfplumber 0.10+ 的 to_image 基于 pypdfium2 渲染（pdfplumber 自带依赖）
                image = page.to_image(resolution=_OCR_RESOLUTION).original
                result, _elapse = engine(image)
                if result:
                    for _box, text, _score in result:
                        text = text.strip()
                        if text:
                            parts.append(text)
        text = "\n".join(parts).strip()
        return text or None
    except ImportError:
        logger.warning(
            "RapidOCR 未安装（pip install rapidocr-onnxruntime），扫描件 OCR 不可用: %s", path
        )
        return None
    except Exception as e:
        logger.warning("扫描件 OCR 失败（降级返回 None）: %s: %s", path, e)
        return None
