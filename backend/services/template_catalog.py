"""简历模板画廊目录 — 公开模板元数据 + 零数据渲染预览。

真实模板在 backend/templates/*.html（11 套），由 TemplateRegistry 懒加载。
本模块提供画廊展示所需的元数据（中文名/描述/tags/layout）与预览 HTML：
用占位模块（全部符合 resume_module schema）经 render_resume_from_dict 渲染，
无需真实简历数据即可看到模板框架效果。

注意：模板是 WeasyPrint 打印样式（@page 被浏览器忽略），画廊预览为近似效果，
PDF 导出才是权威渲染。
"""

import logging
from functools import lru_cache

from schemas.resume_module import ResumeStyle
from services.resume_template import TemplateRegistry, render_resume_from_dict

logger = logging.getLogger(__name__)

# 模板 ID → 画廊元数据（缺省回退 name=id / 空描述）
_TEMPLATE_META: dict[str, dict] = {
    "default": {
        "name": "经典",
        "description": "经典单栏布局，信息密度高，适合大多数岗位的标准选择。",
        "tags": ["单栏", "通用", "求职通用"],
        "layout": "单栏",
    },
    "minimal": {
        "name": "极简",
        "description": "大留白极简风格，突出内容本身，适合设计/创意类岗位。",
        "tags": ["单栏", "极简", "设计向"],
        "layout": "单栏",
    },
    "business": {
        "name": "商务",
        "description": "稳重商务风，深色强调标题，适合金融/咨询/管理类岗位。",
        "tags": ["单栏", "商务", "金融咨询"],
        "layout": "单栏",
    },
    "professional": {
        "name": "专业",
        "description": "双栏专业布局，侧栏放基本信息/技能，适合研发/技术岗。",
        "tags": ["双栏", "技术", "研发"],
        "layout": "双栏",
    },
    "elegant": {
        "name": "优雅",
        "description": "细线分隔优雅版式，适合品牌/市场/运营类岗位。",
        "tags": ["单栏", "优雅", "市场运营"],
        "layout": "单栏",
    },
    "steady": {
        "name": "沉稳",
        "description": "深色头带突出姓名与求职意向，适合国企/事业单位风格。",
        "tags": ["头带", "沉稳", "国企"],
        "layout": "头带",
    },
    "vibrant": {
        "name": "活力",
        "description": "彩色头带 + 强调色点缀，适合互联网/新媒体等活力岗位。",
        "tags": ["头带", "活力", "互联网"],
        "layout": "头带",
    },
    "timeline": {
        "name": "时间线",
        "description": "经历以时间线呈现，突出职业成长轨迹，适合经历丰富的候选人。",
        "tags": ["单栏", "时间线", "成长轨迹"],
        "layout": "单栏",
    },
    "twocolumn": {
        "name": "双栏",
        "description": "左右双栏布局，信息分区清晰，适合经历全面的候选人。",
        "tags": ["双栏", "分区", "全面"],
        "layout": "双栏",
    },
    "card": {
        "name": "卡片",
        "description": "模块卡片化呈现，视觉层次分明，适合创意/产品类岗位。",
        "tags": ["单栏", "卡片", "产品创意"],
        "layout": "单栏",
    },
    "editorial": {
        "name": "编辑",
        "description": "编辑排版风格，大字标题 + 专栏布局，适合设计/内容类岗位。",
        "tags": ["单栏", "编辑", "设计"],
        "layout": "单栏",
    },
}


def _placeholder_modules() -> list[dict]:
    """5 个占位模块（全部符合 resume_module schema），供零数据预览渲染。

    basic_info/skills 进侧栏（双栏模板），education/work/project 进主栏；
    头带模板（steady/vibrant）把 basic_info 提取为深色头带。
    """
    return [
        {
            "module_type": "basic_info",
            "content": {
                "name": "示例姓名",
                "job_title": "目标岗位",
                "location": "示例城市",
                "summary": "具备扎实专业基础与项目实践经验的候选人示例。",
            },
            "sort_order": 0,
        },
        {
            "module_type": "education",
            "content": {
                "entries": [
                    {
                        "school": "示例大学",
                        "degree": "本科",
                        "major": "计算机科学与技术",
                        "start_date": "2021-09",
                        "end_date": "2025-06",
                    }
                ]
            },
            "sort_order": 1,
        },
        {
            "module_type": "work_experience",
            "content": {
                "entries": [
                    {
                        "company": "示例科技公司",
                        "position": "开发工程师",
                        "start_date": "2025-07",
                        "end_date": "至今",
                        "description": "负责核心模块设计与开发，优化系统性能。",
                    }
                ]
            },
            "sort_order": 2,
        },
        {
            "module_type": "project_experience",
            "content": {
                "entries": [
                    {
                        "name": "示例项目",
                        "role": "核心开发",
                        "start_date": "2024-03",
                        "end_date": "2024-09",
                        "description": "独立负责后端服务开发与部署上线。",
                        "tech_stack": ["Python", "FastAPI"],
                    }
                ]
            },
            "sort_order": 3,
        },
        {
            "module_type": "skills",
            "content": {
                "categories": [
                    {"name": "编程语言", "items": ["Python", "TypeScript"]},
                    {"name": "框架工具", "items": ["FastAPI", "React"]},
                ]
            },
            "sort_order": 4,
        },
    ]


@lru_cache(maxsize=32)
def render_template_preview(template_id: str) -> str:
    """零数据渲染模板框架 HTML。未知模板返回空串（不抛异常）。"""
    try:
        style = ResumeStyle(template_id=template_id)
        return render_resume_from_dict(
            _placeholder_modules(), style=style, filename="简历预览"
        )
    except ValueError:
        logger.warning("preview template not found: %s", template_id)
        return ""


def list_template_infos() -> list[dict]:
    """画廊列表：真实注册模板 + 元数据 + 预览 HTML（按模板名排序）。"""
    infos = []
    for tid in TemplateRegistry.list_names():
        meta = _TEMPLATE_META.get(tid, {})
        infos.append(
            {
                "id": tid,
                "name": meta.get("name", tid),
                "description": meta.get("description", ""),
                "tags": meta.get("tags", []),
                "layout": meta.get("layout", ""),
                "preview_html": render_template_preview(tid),
            }
        )
    return infos


def get_template_info(template_id: str) -> dict | None:
    """单套模板信息。不存在返回 None。"""
    if template_id not in TemplateRegistry.list_names():
        return None
    meta = _TEMPLATE_META.get(template_id, {})
    return {
        "id": template_id,
        "name": meta.get("name", template_id),
        "description": meta.get("description", ""),
        "tags": meta.get("tags", []),
        "layout": meta.get("layout", ""),
        "preview_html": render_template_preview(template_id),
    }
