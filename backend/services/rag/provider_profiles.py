"""Provider request profiles.

Keep scenario policy in one place.  Profiles are provider-neutral; the
OpenAI-compatible adapter translates enabled thinking to DeepSeek's
``extra_body.thinking`` shape and leaves unsupported fields out.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    thinking: bool = False
    effort: str = "high"
    use_tools: bool = False
    strict_tools: bool = False
    temperature: float | None = 0.1
    max_tokens: int | None = None


_PROFILES: dict[str, ProviderProfile] = {
    "resume_extract": ProviderProfile("resume_extract", max_tokens=4096),
    "qa_simple": ProviderProfile("qa_simple", max_tokens=1200),
    "qa_complex": ProviderProfile("qa_complex", thinking=True, effort="high", max_tokens=2400),
    "field_rewrite": ProviderProfile("field_rewrite", max_tokens=1200),
    "resume_compare": ProviderProfile("resume_compare", thinking=True, effort="high", max_tokens=2400),
    "tool_call": ProviderProfile("tool_call", use_tools=True, max_tokens=2400),
    "judge": ProviderProfile("judge", max_tokens=1200),
}


def get_provider_profile(name: str | None, *, use_tools: bool = False) -> ProviderProfile:
    """Return a safe profile; unknown scenarios degrade to ``qa_simple``."""
    profile = _PROFILES.get(name or "qa_simple", _PROFILES["qa_simple"])
    if use_tools and not profile.use_tools:
        return ProviderProfile(
            name=profile.name,
            thinking=profile.thinking,
            effort=profile.effort,
            use_tools=True,
            strict_tools=profile.strict_tools,
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
        )
    return profile


def list_provider_profiles() -> dict[str, ProviderProfile]:
    return dict(_PROFILES)
