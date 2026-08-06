"""B1+B2 面经知识库导入脚本：遍历三个数据集 md → 分块 + embedding → 写入公共 Chroma 集合。

数据源（``third_party/``，已 clone）→ 公共集合 / asset_type：

    agent-interview-hub/                  → interview_hub    / interview
    Algorithm_Interview_Notes-Chinese/    → interview_qa     / interview
    ResumeSample/                         → resume_samples   / resume_sample

设计：
- 每个 md 文件 = 一个 asset：
  - ``asset_id = int(sha256(相对路径).hexdigest()[:8], 16)``
    （相对各数据集根；同一集合内路径唯一 → asset_id 稳定唯一、可重跑幂等）
  - ``version=1``，``user_id=0``（公共资产，所有用户可检索）
  - 复用 ``index_asset``（分块 + embedding + 写入，含同 asset 旧版本退役）
- 幂等：``--write`` 时先 ``delete_collection`` 重建（集合为脚本专用，无其他数据），
  再逐文件 ``index_asset``；删除后调 ``cleanup_orphan_segments`` 清 Windows 孤儿 HNSW 目录
- 跳过：非 ``.md`` / 隐藏目录（``.git`` 等）/ 超过 200KB 的超大文件（提示跳过）

默认 **dry-run**（不写库、不调 embedding API，只遍历统计 + 精确分块计数）；
加 ``--write`` 显式写入（消耗 embedding 额度）。

用法（在 backend/ 下）：
    python -m scripts.import_interview_hub --dataset hub --dry-run
    python -m scripts.import_interview_hub --dataset all --dry-run
    python -m scripts.import_interview_hub --dataset all --write
"""

import argparse
import asyncio
import hashlib
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

# ── 保证 services.* 可导入：脚本可能从任意 cwd 运行，把 backend/ 插入 sys.path ──
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from services.rag.chunking import chunk_by_sections
from services.rag.clients import cleanup_orphan_segments, corpus_collection_name
from services.rag.indexer import index_asset
from services.vector_store import get_vector_store

logging.basicConfig(level=logging.INFO, format="%(levelname)-5.5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

# 数据集根目录（backend/ 的上两级 = 仓库根 → third_party/）
_THIRD_PARTY_DIR = _BACKEND_DIR.parent / "third_party"

# 超大文件阈值：>200KB 提示跳过（数据集最大文件约 159KB，正常情况不会触发）
MAX_FILE_BYTES = 200 * 1024

# 公共集合统一 user_id（公共资产，所有用户可检索；与 per-user 集合隔离）
PUBLIC_USER_ID = 0


@dataclass(frozen=True)
class _Dataset:
    key: str        # CLI 参数值（--dataset）
    kind: str       # 公共语料类型/集合名（interview_hub 等，与 clients.CORPUS_KINDS 对齐）
    rel_dir: str    # 相对 third_party 的目录
    asset_type: str # 写入 metadata 的资产类型


# 集合名统一走 clients.corpus_collection_name（kind = 集合名）
DATASETS: dict[str, _Dataset] = {
    "hub": _Dataset("hub", "interview_hub", "agent-interview-hub", "interview"),
    "notes": _Dataset("notes", "interview_qa", "Algorithm_Interview_Notes-Chinese", "interview"),
    "samples": _Dataset("samples", "resume_samples", "ResumeSample", "resume_sample"),
}


def _iter_md_files(root: Path):
    """递归遍历 md 文件，跳过隐藏目录（.git/.github/.vscode 等）。"""
    for p in sorted(root.rglob("*.md")):
        rel_parts = p.relative_to(root).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        yield p


def _scan_dataset(ds: _Dataset) -> tuple[list[dict], int]:
    """遍历数据集，返回文件清单与跳过数（不写库、不调 embedding）。

    文件清单项: ``{rel_path, text, bytes}``
    """
    root = _THIRD_PARTY_DIR / ds.rel_dir
    if not root.is_dir():
        logger.warning("数据集目录不存在，跳过 %s: %s", ds.key, root)
        return [], 0

    files: list[dict] = []
    skipped = 0
    for p in _iter_md_files(root):
        rel = p.relative_to(root).as_posix()
        size = p.stat().st_size
        if size > MAX_FILE_BYTES:
            logger.info("跳过超大文件（%.1fKB > 200KB）: %s", size / 1024, rel)
            skipped += 1
            continue
        # errors="replace"：个别文件含非法 UTF-8 字节时不中断整批导入
        text = p.read_text(encoding="utf-8", errors="replace")
        files.append({"rel_path": rel, "text": text, "bytes": size})
    return files, skipped


def _estimate_chunks(text: str) -> int:
    """精确分块计数（chunk_by_sections 为纯 CPU 分块，不调 embedding API）。"""
    return len(chunk_by_sections(text))


def _asset_id(rel_path: str) -> int:
    """稳定唯一 asset_id：sha256(相对路径) 截断取前 8 个 hex 字符转 int。

    - 同一集合内相对路径唯一 → asset_id 唯一
    - 取 32 位（int64 内），~600 文件碰撞概率约 4e-5，可忽略
    - 重跑不变 → 幂等复用 index_asset 的旧版本退役
    """
    return int(hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:8], 16)


async def _import_one(ds: _Dataset, entry: dict) -> int:
    """写入单个 asset，返回写入的 chunk 数。"""
    rel_path = entry["rel_path"]
    text = entry["text"]
    return await index_asset(
        collection=corpus_collection_name(ds.kind),
        user_id=PUBLIC_USER_ID,
        asset_id=_asset_id(rel_path),
        asset_type=ds.asset_type,
        text=text,
        version=1,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _dry_run_dataset(ds: _Dataset) -> dict:
    """dry-run：遍历统计 + 精确分块计数，不写库、不调 embedding。"""
    files, skipped = _scan_dataset(ds)
    total_chars = sum(len(f["text"]) for f in files)
    total_bytes = sum(f["bytes"] for f in files)
    total_chunks = sum(_estimate_chunks(f["text"]) for f in files)
    return {
        "files": len(files),
        "chars": total_chars,
        "bytes": total_bytes,
        "chunks": total_chunks,
        "skipped": skipped,
    }


async def _write_dataset(ds: _Dataset, limit: int = 0) -> dict:
    """--write：delete_collection 重建 → 逐文件 index_asset 写入。

    Args:
        limit: 每数据集最多导入文件数（0=不限；>0 用于部分导入测试）。
    """
    files, skipped = _scan_dataset(ds)
    if limit and limit > 0:
        files = files[:limit]
    collection = corpus_collection_name(ds.kind)

    store = get_vector_store()
    logger.info("重建集合 %s（删除旧数据）...", collection)
    await store.delete_collection(collection)
    cleanup_orphan_segments()  # 同步函数：清理 Windows 孤儿 segment（不 await）

    total_chunks = 0
    errors: list[str] = []
    for entry in files:
        try:
            n = await _import_one(ds, entry)
            total_chunks += n
        except Exception as e:  # 单文件失败不中断整批，记录后继续
            logger.warning("导入失败: %s: %s", entry["rel_path"], e)
            errors.append(entry["rel_path"])
    logger.info(
        "写入完成: collection=%s files=%d chunks=%d errors=%d",
        collection, len(files), total_chunks, len(errors),
    )
    return {
        "files": len(files),
        "chunks": total_chunks,
        "skipped": skipped,
        "errors": errors,
    }


def _resolve_datasets(keys: list[str]) -> list[_Dataset]:
    ds_list = [DATASETS[k] for k in keys]
    # 保持注册顺序（hub → notes → samples），而非命令行顺序
    return [d for d in DATASETS.values() if d in ds_list]


def _fmt(n: int) -> str:
    return f"{n:,}"


def main() -> None:
    parser = argparse.ArgumentParser(description="面经知识库导入（B1+B2）")
    parser.add_argument(
        "--dataset",
        choices=["hub", "notes", "samples", "all"],
        default="all",
        help="hub=agent-interview-hub / notes=Algorithm_Interview_Notes / samples=ResumeSample / all=全部",
    )
    mode = parser.add_mutually_exclusive_group(required=False)
    mode.add_argument("--dry-run", action="store_true", help="只遍历统计，不写库（默认）")
    mode.add_argument("--write", action="store_true", help="显式写入（delete_collection 重建 + 调 embedding API）")
    parser.add_argument("--limit", type=int, default=0, help="每数据集最多导入文件数（0=不限，>0 用于部分导入测试）")
    args = parser.parse_args()

    keys = list(DATASETS) if args.dataset == "all" else [args.dataset]
    datasets = _resolve_datasets(keys)
    write = args.write

    logger.info("数据目录: %s", _THIRD_PARTY_DIR)
    logger.info("模式: %s", "WRITE（写库，消耗 embedding 额度）" if write else "DRY-RUN（仅统计，不写库）")

    grand = {"files": 0, "chars": 0, "bytes": 0, "chunks": 0, "skipped": 0, "errors": []}
    for ds in datasets:
        collection = corpus_collection_name(ds.kind)
        if write:
            stats = asyncio.run(_write_dataset(ds, limit=args.limit))
            print(
                f"[{ds.key}] {collection}: {stats['files']} 文件 → {_fmt(stats['chunks'])} chunks"
                f"（跳过 {stats['skipped']}，失败 {len(stats['errors'])}）"
            )
            grand["files"] += stats["files"]
            grand["chunks"] += stats["chunks"]
            grand["skipped"] += stats["skipped"]
            grand["errors"].extend(stats["errors"])
        else:
            stats = _dry_run_dataset(ds)
            print(
                f"[{ds.key}] {collection}: {stats['files']} 文件 / {_fmt(stats['chars'])} 字符"
                f" / {_fmt(stats['bytes'])} 字节 → 预计 {_fmt(stats['chunks'])} chunks"
                f"（跳过 {stats['skipped']}）"
            )
            grand["files"] += stats["files"]
            grand["chars"] += stats["chars"]
            grand["bytes"] += stats["bytes"]
            grand["chunks"] += stats["chunks"]
            grand["skipped"] += stats["skipped"]

    if write:
        print(
            f"汇总: {grand['files']} 文件 → {_fmt(grand['chunks'])} chunks"
            f"（跳过 {grand['skipped']}，失败 {len(grand['errors'])}）"
        )
    else:
        print(
            f"汇总: {grand['files']} 文件 / {_fmt(grand['chars'])} 字符 / {_fmt(grand['bytes'])} 字节"
            f" → 预计 {_fmt(grand['chunks'])} chunks（跳过 {grand['skipped']}）"
        )
    if grand["errors"]:
        print("失败文件列表:")
        for e in grand["errors"]:
            print(f"  - {e}")


if __name__ == "__main__":
    main()
