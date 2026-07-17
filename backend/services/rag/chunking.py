"""简历文本 → 结构化分块。

阶段11 从 rag_service.py 拆出：纯文本处理，无外部依赖（除 jieba 分词），
是整条 RAG 链路里最易单测、最不该被网络 IO 污染的部分。
"""
import logging
import re

import jieba

logger = logging.getLogger(__name__)

SECTION_HEADERS = [
    # 教育
    "教育背景", "教育经历", "学历", "教育", "学习经历",
    # 工作 / 实习
    "工作经历", "工作经验", "实习经历", "实习经验", "工作", "实习",
    # 项目
    "项目经历", "项目经验", "项目展示", "项目",
    # 技能
    "专业技能", "技能", "技术栈", "技术能力", "个人技能", "掌握技能",
    # 评价 / 总结
    "自我评价", "个人总结", "自我介绍", "个人评价", "自我总结",
    # 其他
    "开源贡献", "开源", "证书", "获奖", "荣誉", "证书与奖项",
]
# 行首 + 可选的序号（一/1.） + 标题 + 冒号 + 换行
SECTION_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:(?:[一二三四五六七八九十]+|\d+)[、.）\)]?\s*)?("
    + "|".join(re.escape(h) for h in SECTION_HEADERS)
    + r")[\s:：]*\n",
    re.IGNORECASE,
)


def _tokenize(text: str) -> list[str]:
    return list(jieba.cut_for_search(text))


def _split_by_sections(text: str) -> list[tuple[str, str]]:
    """按简历节段标题切分，无标题则整体返回"""
    if not SECTION_PATTERN.search(text):
        return [("正文", text)]

    parts = SECTION_PATTERN.split(text)
    sections = [("基本信息", parts[0].strip())]
    i = 1
    while i + 1 < len(parts):
        sections.append((parts[i].strip(), parts[i + 1].strip()))
        i += 2
    return sections


def _find_split(text: str, chunk_size: int, separators: list[str]) -> int:
    for sep in separators:
        pos = text.rfind(sep, int(chunk_size * 0.5), chunk_size)
        if pos > 0:
            return pos + len(sep)
    return chunk_size


def _recursive_split(text: str, chunk_size: int, overlap: int) -> list[str]:
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) must be < chunk_size ({chunk_size})")
    separators = ["\n\n", "\n", "。", "，", " "]  # 按优先级切分
    result = []
    current = text
    while len(current) > chunk_size:
        split_pos = _find_split(current, chunk_size, separators)
        result.append(current[:split_pos])
        current = current[max(0, split_pos - overlap):]
    if current.strip():
        result.append(current)
    return result


def _make_chunk(text: str, section: str, index: int, offset: int) -> dict:
    return {
        "text": text,
        "section": section,
        "chunk_index": index,
        "start_char": offset,
        "end_char": offset + len(text),
    }


def chunk_by_sections(text: str, chunk_size: int = 1200, overlap: int = 50) -> list[dict]:
    """结构感知分块：先按节段切，超长节段内部再递归细分"""
    sections = _split_by_sections(text)
    chunks = []
    idx = 0
    offset = 0
    for section, body in sections:
        body = body.strip()
        if not body:
            continue
        if len(body) <= chunk_size:
            chunks.append(_make_chunk(body, section, idx, offset))
            idx += 1
            offset += len(body)
        else:
            for sub in _recursive_split(body, chunk_size, overlap):
                chunks.append(_make_chunk(sub, section, idx, offset))
                idx += 1
                offset += len(sub)
    return chunks


def fixed_chunk(text: str, chunk_size: int, overlap: int = 50) -> list[dict]:
    """固定长度分块（对照实验用）"""
    chunks = []
    idx = 0
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(_make_chunk(text[start:end], "正文", idx, start))
        idx += 1
        start += chunk_size - overlap
    return chunks
