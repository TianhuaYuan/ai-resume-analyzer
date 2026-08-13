"""
Sensitive field filtering for AI inputs.

Prevents personal identifiable information (PII) from leaking into LLM calls
by recursively sanitizing structured content (dicts/lists) and applying
regex-based pattern replacement on freeform text.

Usage::

    from utils.privacy import sanitize_for_ai, sanitize_text_for_ai

    safe_content = sanitize_for_ai({"name": "张三", "email": "a@b.com"})
    # -> {"name": "[姓名]", "email": "[邮箱]"}

    safe_text = sanitize_text_for_ai("联系张三 13800138000")
    # -> "联系[姓名] [手机号]"
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Sensitive field definitions
# ---------------------------------------------------------------------------

#: Fields that are sensitive and should never be sent to LLMs.
SENSITIVE_FIELDS: set[str] = {
    "name",
    "phone",
    "email",
    "avatar",
    "gender",
    "age",
    "contact",
}

#: Chinese display labels for sensitive fields.
#: ``None`` means the field should be completely removed rather than replaced.
SENSITIVE_LABELS: dict[str, str | None] = {
    "name": "[姓名]",
    "phone": "[手机号]",
    "email": "[邮箱]",
    "avatar": None,
    "gender": None,
    "age": None,
    "contact": "[联系方式]",
}

# ---------------------------------------------------------------------------
# Text-level sanitization patterns (for freeform text passed to LLMs)
# ---------------------------------------------------------------------------

_PHONE_PATTERN = re.compile(
    r"(?<!\d)"                      # not preceded by digit
    r"(?:\+?86[-\s]?)?"            # optional China country code
    r"(1[3-9]\d{9})"               # 11-digit mobile number
    r"(?!\d)"                       # not followed by digit
)

_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)

_ID_CARD_PATTERN = re.compile(
    r"(?<!\d)"
    r"[1-9]\d{5}"                          # region code
    r"(?:19|20)\d{2}"                      # year 1900-2099
    r"(?:0[1-9]|1[0-2])"                   # month
    r"(?:0[1-9]|[12]\d|3[01])"             # day
    r"\d{3}[\dXx]"                         # sequence + check
    r"(?!\d)",
)

_BANK_CARD_PATTERN = re.compile(
    r"(?<!\d)"
    r"(?:62|45|51|35|60)\d{14,17}"         # common Chinese bank card prefixes
    r"(?!\d)",
)

# ---------------------------------------------------------------------------
# Structured content sanitization (dict / list)
# ---------------------------------------------------------------------------


def sanitize_for_ai(content: dict | list | Any) -> dict | list | Any:
    """Recursively filter sensitive fields from structured content.

    - For fields in :data:`SENSITIVE_FIELDS`:
      - If a Chinese label exists (e.g. ``"[姓名]"``), replaces the value.
      - If the label is ``None`` (avatar/gender/age), removes the field entirely.
    - Handles nested dicts and lists.
    - Returns a **new** object; the input is never mutated.

    Args:
        content: A dict, list, or primitive value to sanitize.

    Returns:
        The sanitized copy. Primitive values are returned as-is.
    """
    if isinstance(content, dict):
        result: dict[str, Any] = {}
        for key, value in content.items():
            if key in SENSITIVE_FIELDS:
                label = SENSITIVE_LABELS.get(key)
                if label is not None:
                    # Replace with Chinese placeholder
                    result[key] = label
                # else: field is omitted entirely (avatar, gender, age)
            else:
                result[key] = sanitize_for_ai(value)
        return result

    if isinstance(content, list):
        return [sanitize_for_ai(item) for item in content]

    # Primitive / None — pass through unchanged
    return content


def sanitize_resume_module_for_ai(module_type: str, content: Any) -> Any:
    """按简历模块语义脱敏，避免把项目名、技能名误当作候选人姓名。

    ``name`` 在 basic_info / recommendation 中是人名，但在 project_experience、
    skills、certificates 等模块中是业务内容。旧的无上下文递归脱敏会把这些值
    全部替换为 ``[姓名]``，直接破坏检查、改写与诊断质量。
    """
    if module_type == "basic_info":
        return sanitize_for_ai(content)

    person_name_modules = {"recommendation"}

    def _sanitize(value: Any, key: str | None = None) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for child_key, child_value in value.items():
                if child_key == "avatar":
                    continue
                if child_key in {"phone", "email", "contact"}:
                    result[child_key] = SENSITIVE_LABELS.get(child_key) or "[已脱敏]"
                    continue
                if child_key == "name" and module_type in person_name_modules:
                    result[child_key] = SENSITIVE_LABELS["name"]
                    continue
                result[child_key] = _sanitize(child_value, child_key)
            return result
        if isinstance(value, list):
            return [_sanitize(item, key) for item in value]
        if isinstance(value, str):
            return sanitize_text_for_ai(value)
        return value

    return _sanitize(content)


# ---------------------------------------------------------------------------
# Freeform text sanitization (regex-based)
# ---------------------------------------------------------------------------


def sanitize_text_for_ai(text: str) -> str:
    """Replace PII patterns in freeform text with placeholders.

    Detected patterns:

    - **Phone numbers** (Chinese mobile ``1xxxxxxxxxx``, with optional +86)
      -> ``[手机号]``
    - **Email addresses** -> ``[邮箱]``
    - **ID card numbers** (18-digit mainland China resident ID)
      -> ``[身份证号]``
    - **Bank card numbers** (common prefixes, 15-18 digits)
      -> ``[银行卡号]``

    Args:
        text: Freeform text that may contain PII.

    Returns:
        Sanitized text with PII replaced by placeholders.

    Note:
        This is a heuristic approach for text that cannot be structurally
        filtered (e.g. LLM prompts that include freeform descriptions).
        For structured resume content, prefer :func:`sanitize_for_ai`.
    """
    text = _PHONE_PATTERN.sub("[手机号]", text)
    text = _EMAIL_PATTERN.sub("[邮箱]", text)
    text = _ID_CARD_PATTERN.sub("[身份证号]", text)
    text = _BANK_CARD_PATTERN.sub("[银行卡号]", text)
    return text
