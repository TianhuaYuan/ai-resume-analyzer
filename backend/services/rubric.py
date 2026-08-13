"""I2: 可编辑 rubric 配置加载器（热重载）。

评分权重 / 角色权重 / JD fit 维度 / 6-block 报告开关从 `backend/data/rubric.json`
读取（参考 JobMcp modes/rubric.md 运行时加载思路）。按 mtime 缓存，改文件即热重载，
无需重启 / 改代码。

所有消费方（analyze_service 多角色聚合、match_jd_service 四维 fit、JDMatchTool
6-block 报告）统一走 `load_rubric()`，权重不再硬编码。
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

# (mtime, data) 缓存；mtime 变化即重载
_rubric_cache: tuple[float, dict] | None = None

# 缺省配置（文件缺失 / 解析失败时的兜底，与 rubric.json 保持一致）
_DEFAULT_RUBRIC: dict = {
    "schema_version": 1,
    "score_bands": {"excellent": 85, "good": 70, "medium": 50},
    "score_dimensions": {
        "ats_match": 0.35,
        "keyword_coverage": 0.25,
        "skill_density": 0.20,
        "overall": 0.20,
    },
    "roles": {
        "peer": {"weight": 0.35, "label": "同级别评估"},
        "lead": {"weight": 0.35, "label": "团队负责人评估"},
        "hrbp": {"weight": 0.30, "label": "HRBP 评估"},
    },
    "jd_fit_dims": {
        "technical": 0.35,
        "experience": 0.30,
        "behavioral": 0.20,
        "career": 0.15,
    },
    "jd_report_blocks": [
        {"key": "role_summary", "label": "角色摘要", "enabled": True},
        {"key": "cv_match", "label": "CV 匹配表", "enabled": True},
        {"key": "level_strategy", "label": "级别策略", "enabled": True},
        {"key": "comp_market", "label": "薪酬市场", "enabled": True},
        {"key": "personalization_plan", "label": "个性化计划", "enabled": True},
        {"key": "interview_stories", "label": "面试故事映射", "enabled": True},
        {"key": "job_credibility", "label": "岗位可信度防坑", "enabled": True},
    ],
}


def _rubric_path() -> str:
    """rubric.json 绝对路径（backend/data/rubric.json）。"""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(backend_dir, "data", "rubric.json")


def load_rubric() -> dict:
    """加载 rubric 配置（mtime 热重载）。解析失败回退默认配置。"""
    global _rubric_cache
    path = _rubric_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        logger.warning("rubric.json 不存在（%s），使用默认配置", path)
        return dict(_DEFAULT_RUBRIC)

    if _rubric_cache is not None and _rubric_cache[0] == mtime:
        return _rubric_cache[1]

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("rubric 必须是 JSON 对象")
        _rubric_cache = (mtime, data)
        return data
    except Exception as e:
        logger.warning("rubric.json 解析失败（使用默认配置）: %s", e)
        return dict(_DEFAULT_RUBRIC)


def get_role_weights() -> dict[str, dict]:
    """多角色评估权重与标签（peer/lead/hrbp）。"""
    return load_rubric().get("roles", _DEFAULT_RUBRIC["roles"])


def get_jd_fit_dims() -> dict[str, float]:
    """JD fit 四维权重（technical/experience/behavioral/career）。"""
    return load_rubric().get("jd_fit_dims", _DEFAULT_RUBRIC["jd_fit_dims"])


def role_aggregate(role_scores: dict[str, int]) -> int:
    """多角色分数 → 加权聚合。角色权重来自 rubric。"""
    weights = get_role_weights()
    total_w = 0.0
    acc = 0.0
    for role, weight_cfg in weights.items():
        w = float(weight_cfg.get("weight", 0))
        score = role_scores.get(role)
        if isinstance(score, int):
            acc += w * score
            total_w += w
    if total_w <= 0:
        return 0
    return max(0, min(100, round(acc / total_w)))


def jd_fit_overall(dims: dict[str, int]) -> int:
    """JD fit 四维 → 加权 overall。维度权重来自 rubric。"""
    dim_weights = get_jd_fit_dims()
    total_w = 0.0
    acc = 0.0
    for dim, w in dim_weights.items():
        score = dims.get(dim)
        if isinstance(score, int):
            acc += float(w) * score
            total_w += float(w)
    if total_w <= 0:
        return 0
    return max(0, min(100, round(acc / total_w)))
