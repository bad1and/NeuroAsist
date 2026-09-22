from __future__ import annotations


DEEPSEEK_FLASH_MODEL = "deepseek-flash"
DEEPSEEK_PRO_MODEL = "deepseek-v4-pro"
SUPPORTED_DEEPSEEK_MODELS = frozenset(
    {DEEPSEEK_FLASH_MODEL, DEEPSEEK_PRO_MODEL}
)

# DeepSeek V4.1 is the product/version name, not part of the public Flash API
# identifier. Keep accepting names previously persisted by Iris and aliases
# retired by DeepSeek, but always send the current canonical identifier.
_DEEPSEEK_MODEL_ALIASES = {
    "deepseek-v4.1-flash": DEEPSEEK_FLASH_MODEL,
    "deepseek-v4-flash": DEEPSEEK_FLASH_MODEL,
    "deepseek-v4-flash-vision-exp": DEEPSEEK_FLASH_MODEL,
    "deepseek-chat": DEEPSEEK_FLASH_MODEL,
    "deepseek-reasoner": DEEPSEEK_FLASH_MODEL,
    "deepseek-v4.1-pro": DEEPSEEK_PRO_MODEL,
}


def canonical_deepseek_model(model: object) -> str:
    """Return the current API identifier while preserving custom model IDs."""
    value = str(model or "").strip().lower()
    if not value:
        return DEEPSEEK_FLASH_MODEL
    return _DEEPSEEK_MODEL_ALIASES.get(value, value)
