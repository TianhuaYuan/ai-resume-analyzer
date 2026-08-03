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
