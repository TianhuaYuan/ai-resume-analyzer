"""E1: 简历编辑契约 — resume_modules 结构化骨架 + RFC 6902 JSON Patch 应用。

v2 阶段 4「简历 AI 安全编辑」第一步。设计来源：
- reactive-resume-main 的 zod schema 结构对照：简历 = 模块集合，每个模块
  有字段级约束（类型 / 长度 / 必填）
- Magic-Resume 的 patch 思路：MCP 层用 JSON Patch（RFC 6902）做增量编辑，
  "always patch-based, never full rewrites"——AI 只提交改动点，不整份覆盖

本文件职责：
1. `RESUME_MODULES_SKELETON` — 由 resume_module.py 的 15 个 pydantic schema
   推导出的字段级骨架（类型 / 必填 / max_length / 富文本字段），供前端表单、
   E2 diff 审阅、文档校验用（单一数据源，避免文案漂移）。
2. `validate_resume_modules(data)` — 全量校验简历模块文档。
3. `apply_resume_patch(data, ops)` — RFC 6902 JSON Patch 应用 + 应用后全量校验；
   非法 op / 路径越界 / 类型错误 → 抛 `ResumeEditError`（中文信息）。

纯函数，便于单测；不依赖 DB / LLM。
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import ValidationError

from schemas.resume_module import (
    DEFAULT_MODULE_LABELS,
    MODULE_CONTENT_SCHEMAS,
    ModuleType,
    validate_module_content,
)

# 合法的 JSON Patch 操作（RFC 6902 全集）
_PATCH_OPS = {"add", "remove", "replace", "move", "copy", "test"}

# 富文本字段（HTML / 长文本，E2 字段级 diff 重点比较对象）
# 值: {module_type: {field: max_length}}——与 resume_module.py schema 对齐
RICH_TEXT_FIELDS: dict[str, dict[str, int]] = {
    "basic_info": {"summary": 500},
    "education": {"description": 500},
    "work_experience": {"description": 2000, "achievements": -1},  # -1 = 列表，无单值上限
    "project_experience": {"description": 2000},
    "club_activities": {"description": 500},
    "honors": {"description": 500},
    "other": {"content": 5000},
    "custom": {"content": 5000},
}


class ResumeEditError(Exception):
    """简历编辑业务异常（中文信息）。

    JSON Patch 非法 op / 路径越界 / 类型错误 / 校验失败均抛此异常。
    API 层捕获后转 HTTP 400，携带可读中文信息。
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


# ═══════════════════════════════════════════════════════════
# 1. 结构化骨架（由 pydantic schema 推导，避免与 resume_module.py 漂移）
# ═══════════════════════════════════════════════════════════


def _field_info(props: dict) -> dict:
    """从 pydantic JSON schema property 提取精简字段信息。"""
    info: dict = {
        "type": props.get("type", "any"),
        "required": False,
    }
    if props.get("maxLength") is not None:
        info["max_length"] = props["maxLength"]
    if props.get("items"):
        # 数组元素类型（list[str] / list[object]）
        items = props["items"]
        if isinstance(items, dict) and items.get("type"):
            info["item_type"] = items["type"]
    return info


def build_modules_skeleton() -> dict[str, dict]:
    """生成 15 模块的字段级骨架。

    返回 {module_type: {label, kind, required_fields, fields: {field: info}}}
    kind 取值：flat（单值平铺，如 basic_info）/ list（items 数组，如 education）/
            custom（单板块+多板块，如 custom）
    """
    skeleton: dict[str, dict] = {}
    for mt in ModuleType:
        schema_cls = MODULE_CONTENT_SCHEMAS[mt]
        try:
            schema = schema_cls.model_json_schema()
        except Exception:
            schema = {}
        props = schema.get("properties", {})
        required = set(schema.get("required", []))

        fields: dict[str, dict] = {}
        for fname, fprops in props.items():
            info = _field_info(fprops)
            info["required"] = fname in required
            fields[fname] = info

        # kind 推断
        if "items" in fields:
            kind = "list"
        elif "content" in fields and "title" in fields:
            kind = "custom"
        else:
            kind = "flat"

        skeleton[mt.value] = {
            "label": DEFAULT_MODULE_LABELS.get(mt.value, mt.value),
            "kind": kind,
            "required_fields": sorted(required),
            "fields": fields,
            "rich_text_fields": RICH_TEXT_FIELDS.get(mt.value, {}),
        }
    return skeleton


# 模块级骨架（模块导入即计算一次；纯静态数据，无副作用）
RESUME_MODULES_SKELETON: dict[str, dict] = build_modules_skeleton()

# 核心模块骨架（E1 计划点名：basic_info / work_experience / education / skills）
CORE_MODULES: list[str] = [
    "basic_info",
    "work_experience",
    "education",
    "skills",
]


def get_rich_text_fields(module_type: str) -> dict[str, int]:
    """获取指定模块的富文本字段约束。未知模块返回空 dict。"""
    return dict(RICH_TEXT_FIELDS.get(module_type, {}))


# ═══════════════════════════════════════════════════════════
# 2. 全量校验
# ═══════════════════════════════════════════════════════════


def validate_resume_modules(modules_map: dict[str, dict]) -> dict[str, dict]:
    """全量校验简历模块文档（{module_type: content} map 形式）。

    逐模块调用 resume_module.validate_module_content 严格校验。
    未知 module_type / content 不符合 schema → 抛 ResumeEditError（中文信息）。

    Args:
        modules_map: {module_type: content_dict}

    Returns:
        校验通过后的模块 map（content 已按 schema 迁移/规范化）
    """
    if not isinstance(modules_map, dict):
        raise ResumeEditError("简历模块文档必须是 {module_type: content} 对象")

    validated: dict[str, dict] = {}
    for mt, content in modules_map.items():
        if not isinstance(mt, str):
            raise ResumeEditError(f"模块类型必须是字符串，收到 {type(mt).__name__}")
        try:
            mtype = ModuleType(mt)
        except ValueError:
            raise ResumeEditError(
                f"未知模块类型: {mt}，必须是 15 个固定枚举之一"
            ) from None

        if not isinstance(content, dict):
            raise ResumeEditError(f"模块 {mt} 的 content 必须是对象，收到 {type(content).__name__}")

        try:
            model = validate_module_content(mtype, content)
        except ValidationError as e:
            detail = _format_validation_errors(mt, e)
            raise ResumeEditError(detail) from None

        validated[mt] = model.model_dump()
    return validated


def _format_validation_errors(module_type: str, e: ValidationError) -> str:
    """pydantic ValidationError → 中文字段级信息。"""
    lines: list[str] = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err.get("loc", []))
        msg = err.get("msg", "校验失败")
        lines.append(f"  - {module_type}.{loc}: {msg}")
    return f"模块 {module_type} 内容校验失败:\n" + "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 3. JSON Pointer 解析（RFC 6901）
# ═══════════════════════════════════════════════════════════


def parse_json_pointer(pointer: str) -> list[str]:
    """RFC 6901 JSON Pointer → 路径段列表。

    - "" → []
    - "/a/b" → ["a", "b"]
    - "~1" → "/"、"~0" → "~"（转义还原）
    - 不以 / 开头 → ResumeEditError
    """
    if not pointer:
        return []
    if not pointer.startswith("/"):
        raise ResumeEditError(f"非法 JSON Pointer: {pointer!r}（必须以 / 开头）")
    parts = pointer[1:].split("/")
    out: list[str] = []
    for p in parts:
        p = p.replace("~1", "/").replace("~0", "~")
        out.append(p)
    return out


def _parse_index(token: str) -> int:
    """列表索引 token → int（非法 → ResumeEditError）。"""
    try:
        return int(token)
    except (ValueError, TypeError):
        raise ResumeEditError(f"列表索引非法: {token!r}（必须是整数）") from None


def resolve_path(root: Any, path: list[str]) -> Any:
    """沿路径解析值；任一环节缺失 → ResumeEditError（路径越界）。"""
    node = root
    for seg in path:
        if isinstance(node, dict):
            if seg not in node:
                raise ResumeEditError(f"路径越界：{_join_path(path)}（键 {seg!r} 不存在）")
            node = node[seg]
        elif isinstance(node, list):
            idx = _parse_index(seg)
            if idx < 0 or idx >= len(node):
                raise ResumeEditError(f"路径越界：{_join_path(path)}（索引 {idx} 越界）")
            node = node[idx]
        else:
            raise ResumeEditError(f"路径越界：{_join_path(path)}（{seg!r} 不是容器）")
    return node


def _join_path(path: list[str]) -> str:
    return "/" + "/".join(path) if path else ""


def _parent_ctx(root: Any, path: list[str]) -> tuple[Any, str | int]:
    """返回路径父容器 + 末段键。父容器必须是 dict / list，否则抛错。"""
    if not path:
        raise ResumeEditError("操作目标不能是文档根节点（空路径不支持该 op）")
    parent = root
    for seg in path[:-1]:
        if isinstance(parent, dict):
            if seg not in parent:
                raise ResumeEditError(f"路径越界：{_join_path(path)}（中间键 {seg!r} 不存在）")
            parent = parent[seg]
        elif isinstance(parent, list):
            idx = _parse_index(seg)
            if idx < 0 or idx >= len(parent):
                raise ResumeEditError(f"路径越界：{_join_path(path)}（中间索引 {idx} 越界）")
            parent = parent[idx]
        else:
            raise ResumeEditError(f"路径越界：{_join_path(path)}（{seg!r} 不是容器）")
    last = path[-1]
    if isinstance(parent, dict):
        return parent, last
    if isinstance(parent, list):
        return parent, _parse_index(last)
    raise ResumeEditError(f"路径越界：{_join_path(path)}（父节点不是 dict/list）")


# ═══════════════════════════════════════════════════════════
# 4. RFC 6902 JSON Patch 应用
# ═══════════════════════════════════════════════════════════


def _op_path(op: dict) -> str:
    p = op.get("path")
    if not isinstance(p, str):
        raise ResumeEditError("每个 op 必须含 string 类型 path 字段")
    return p


def _apply_single_op(root: Any, op: dict) -> Any:
    """应用单个 JSON Patch op（返回修改后的文档）。"""
    if not isinstance(op, dict) or "op" not in op:
        raise ResumeEditError(f"非法 op：{op!r}（必须为含 op 字段的对象）")
    op_name = op.get("op")
    if op_name not in _PATCH_OPS:
        raise ResumeEditError(
            f"非法 op 类型: {op_name!r}（合法: {', '.join(sorted(_PATCH_OPS))}）"
        )

    path = parse_json_pointer(_op_path(op))

    # ── test ──
    if op_name == "test":
        actual = resolve_path(root, path)
        expected = op.get("value")
        if actual != expected:
            raise ResumeEditError(f"test 失败：{_join_path(path)} 实际值 {actual!r} ≠ 期望值 {expected!r}")
        return root

    # ── move / copy 先解析源值 ──
    if op_name in ("move", "copy"):
        from_path = op.get("from")
        if not isinstance(from_path, str):
            raise ResumeEditError(f"{op_name} 必须含 string 类型 from 字段")
        src_path = parse_json_pointer(from_path)
        value = copy.deepcopy(resolve_path(root, src_path))
        if op_name == "move":
            root = _remove_path(root, src_path)

    # ── remove ──
    if op_name == "remove":
        return _remove_path(root, path)

    # ── add / replace / move / copy ──
    if op_name == "replace":
        if not path:
            raise ResumeEditError("replace 不能作用于文档根节点")
        value = op.get("value")
        parent, key = _parent_ctx(root, path)
        if isinstance(parent, dict):
            if key not in parent:
                raise ResumeEditError(f"replace 目标不存在：{_join_path(path)}")
            parent[key] = copy.deepcopy(value)
        else:  # list
            parent[key] = copy.deepcopy(value)
        return root

    if op_name == "add":
        if not path:
            if not isinstance(op.get("value"), dict):
                raise ResumeEditError("add 到根节点时 value 必须是对象")
            return copy.deepcopy(op.get("value"))
        value = op.get("value")
        parent, key = _parent_ctx(root, path)
        if isinstance(parent, dict):
            parent[key] = copy.deepcopy(value)
        else:  # list：add 为插入语义
            idx = key if isinstance(key, int) else _parse_index(key)
            parent.insert(idx, copy.deepcopy(value))
        return root

    if op_name in ("move", "copy"):
        if not path:
            raise ResumeEditError(f"{op_name} 不能作用于文档根节点")
        parent, key = _parent_ctx(root, path)
        if isinstance(parent, dict):
            parent[key] = copy.deepcopy(value)
        else:
            parent.insert(key, copy.deepcopy(value))
        return root

    raise ResumeEditError(f"未实现的 op: {op_name}")  # 理论上不可达


def _remove_path(root: Any, path: list[str]) -> Any:
    """按路径删除节点；目标不存在 → ResumeEditError。"""
    parent, key = _parent_ctx(root, path)
    if isinstance(parent, dict):
        if key not in parent:
            raise ResumeEditError(f"remove 目标不存在：{_join_path(path)}")
        del parent[key]
    else:
        parent.pop(key)
    return root


def apply_resume_patch(data: dict, ops: list[dict]) -> dict:
    """RFC 6902 JSON Patch 应用到简历模块文档。

    入参 data 为模块 map（{module_type: content}）。逐 op 应用，
    全部应用后调用 validate_resume_modules 全量校验：
    - 非法 op / 路径越界 / 类型错误 → ResumeEditError（中文信息）
    - content 不符合 schema → ResumeEditError（字段级中文信息）

    Args:
        data: 简历模块文档（{module_type: content}）
        ops: JSON Patch 操作数组（RFC 6902）

    Returns:
        应用并校验后的新模块文档（原始 data 不被修改）

    Raises:
        ResumeEditError: 任何非法操作 / 校验失败
    """
    if not isinstance(data, dict):
        raise ResumeEditError("简历模块文档必须是对象（{module_type: content}）")
    if not isinstance(ops, list):
        raise ResumeEditError("ops 必须是数组")

    work = copy.deepcopy(data)
    for op in ops:
        work = _apply_single_op(work, op)

    # 应用后全量校验（类型 / 必填 / 越界兜底）
    return validate_resume_modules(work)


# ═══════════════════════════════════════════════════════════
# 5. 列表形式 ↔ map 形式转换（对接 builder 模块 API）
# ═══════════════════════════════════════════════════════════


def modules_list_to_map(modules: list[dict]) -> dict[str, dict]:
    """[{module_type, content, sort_order}] → {module_type: content}（保持输入序）。

    非 dict 项 / 缺 module_type / content 非 dict → ResumeEditError。
    """
    if not isinstance(modules, list):
        raise ResumeEditError("模块列表必须是数组")
    out: dict[str, dict] = {}
    for m in modules:
        if not isinstance(m, dict) or not isinstance(m.get("module_type"), str):
            raise ResumeEditError(f"模块项非法：{m!r}（必须含 string module_type）")
        content = m.get("content", {})
        if not isinstance(content, dict):
            raise ResumeEditError(f"模块 {m['module_type']} 的 content 必须是对象")
        out[m["module_type"]] = content
    return out


def modules_map_to_list(modules_map: dict[str, dict]) -> list[dict]:
    """{module_type: content} → [{module_type, content}]（保持输入序）。"""
    return [
        {"module_type": mt, "content": copy.deepcopy(content)}
        for mt, content in modules_map.items()
    ]


def build_resume_patch(
    modules_map: dict[str, dict],
    *,
    replace_map: dict[str, dict] | None = None,
    remove_modules: list[str] | None = None,
) -> list[dict]:
    """构造整份模块替换/删除的 JSON Patch ops（模块级增量）。

    供 E2「改写落库处附加 PendingChange」与 builder 全量替换之外的安全增量编辑使用：
    只生成 /basic_info、/work_experience/items 等模块级 path 的 replace / remove op，
    不做字段级猜测。

    Args:
        modules_map: 目标完整模块 map（{module_type: content}）
        replace_map: 仅替换这些模块（None = 全量 replace）
        remove_modules: 删除这些模块（replace_map 优先级更高）

    Returns:
        RFC 6902 ops 数组
    """
    ops: list[dict] = []
    targets = replace_map if replace_map is not None else modules_map
    for mt, content in targets.items():
        ops.append({"op": "replace", "path": f"/{mt}", "value": content})
    for mt in remove_modules or []:
        if mt not in (replace_map or {}):
            ops.append({"op": "remove", "path": f"/{mt}"})
    return ops
