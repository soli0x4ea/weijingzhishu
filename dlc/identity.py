"""DLC Identity Module — Profile / Personality / Speech loaders."""
from __future__ import annotations

import json, os
from dataclasses import dataclass, field
from typing import Optional


class IdentityLoadError(Exception):
    """Raised when an identity config file is missing or invalid."""
    pass


# ═══════════════════════════════════════════════════════════════
# P1-01: Profile loader
# ═══════════════════════════════════════════════════════════════

@dataclass
class Appearance:
    summary: str = ""
    details: list[str] = field(default_factory=list)


@dataclass
class Profile:
    name: str
    aliases: list[str] = field(default_factory=list)
    pronouns: list[str] = field(default_factory=list)
    role: str = ""
    relationship_to_user: str = ""
    appearance: Appearance = field(default_factory=Appearance)
    background: str = ""
    core_beliefs: list[str] = field(default_factory=list)
    forbidden_words: list[str] = field(default_factory=list)
    welcome_message: str = ""


class ProfileLoader:
    """Load and validate identity/profile.json."""

    def __init__(self, identity_dir: str):
        self._dir = identity_dir

    def load(self) -> Profile:
        path = os.path.join(self._dir, "profile.json")
        if not os.path.isfile(path):
            raise IdentityLoadError(
                f"profile.json not found in {self._dir}"
            )
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise IdentityLoadError(f"Invalid JSON in profile.json: {e}") from e

        return self._parse(raw)

    def _parse(self, raw: dict) -> Profile:
        if "name" not in raw:
            raise IdentityLoadError("profile.json missing required field: 'name'")

        appearance = Appearance()
        app_raw = raw.get("appearance", {})
        if isinstance(app_raw, dict):
            appearance = Appearance(
                summary=app_raw.get("summary", ""),
                details=app_raw.get("details", []),
            )

        return Profile(
            name=raw["name"],
            aliases=raw.get("aliases", []),
            pronouns=raw.get("pronouns", []),
            role=raw.get("role", ""),
            relationship_to_user=raw.get("relationship_to_user", ""),
            appearance=appearance,
            background=raw.get("background", ""),
            core_beliefs=raw.get("core_beliefs", []),
            forbidden_words=raw.get("forbidden_words", []),
            welcome_message=raw.get("welcome_message", ""),
        )


# ═══════════════════════════════════════════════════════════════
# P1-02: Personality loader
# ═══════════════════════════════════════════════════════════════

@dataclass
class Trait:
    value: float
    description: str = ""
    volatile: bool = False


@dataclass
class MoralAxis:
    order_chaos: float = 0.0
    good_evil: float = 0.0


@dataclass
class Personality:
    traits: dict[str, Trait] = field(default_factory=dict)
    archetype: str = ""
    moral_axis: Optional[MoralAxis] = None


class PersonalityLoader:
    """Load and validate identity/personality.json."""

    def __init__(self, identity_dir: str):
        self._dir = identity_dir

    def load(self) -> Personality:
        path = os.path.join(self._dir, "personality.json")
        if not os.path.isfile(path):
            raise IdentityLoadError(f"personality.json not found in {self._dir}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise IdentityLoadError(f"Invalid JSON in personality.json: {e}") from e

        if "traits" not in raw:
            raise IdentityLoadError("personality.json missing required field: 'traits'")

        traits = {}
        for name, tdata in raw["traits"].items():
            traits[name] = Trait(
                value=float(tdata.get("value", 0.5)),
                description=tdata.get("description", ""),
                volatile=tdata.get("volatile", False),
            )

        moral_axis = None
        ma_raw = raw.get("moral_axis")
        if isinstance(ma_raw, dict):
            moral_axis = MoralAxis(
                order_chaos=float(ma_raw.get("order_chaos", 0)),
                good_evil=float(ma_raw.get("good_evil", 0)),
            )

        return Personality(
            traits=traits,
            archetype=raw.get("archetype", ""),
            moral_axis=moral_axis,
        )


# ═══════════════════════════════════════════════════════════════
# P1-03: Speech loader
# ═══════════════════════════════════════════════════════════════

@dataclass
class EmojiUsage:
    frequency: float = 0.0
    mapping: dict[str, str] = field(default_factory=dict)


@dataclass
class Speech:
    speech_style: str = ""
    address_user: list[str] = field(default_factory=list)
    address_self: list[str] = field(default_factory=list)
    sentence_length: str = "mixed"
    formality: float = 0.5
    emoji_usage: EmojiUsage = field(default_factory=EmojiUsage)
    catchphrases: list[str] = field(default_factory=list)
    language: str = "zh-CN"


class SpeechLoader:
    """Load and validate identity/speech.json."""

    _REQUIRED = {"speech_style", "address_user"}

    def __init__(self, identity_dir: str):
        self._dir = identity_dir

    def load(self) -> Speech:
        path = os.path.join(self._dir, "speech.json")
        if not os.path.isfile(path):
            raise IdentityLoadError(f"speech.json not found in {self._dir}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise IdentityLoadError(f"Invalid JSON in speech.json: {e}") from e

        missing = self._REQUIRED - set(raw.keys())
        if missing:
            raise IdentityLoadError(
                f"speech.json missing required fields: {missing}"
            )

        emoji_raw = raw.get("emoji_usage", {})
        emoji = EmojiUsage(
            frequency=float(emoji_raw.get("frequency", 0.0)),
            mapping=emoji_raw.get("mapping", {}),
        )

        return Speech(
            speech_style=raw["speech_style"],
            address_user=raw.get("address_user", []),
            address_self=raw.get("address_self", []),
            sentence_length=raw.get("sentence_length", "mixed"),
            formality=float(raw.get("formality", 0.5)),
            emoji_usage=emoji,
            catchphrases=raw.get("catchphrases", []),
            language=raw.get("language", "zh-CN"),
        )


# ═══════════════════════════════════════════════════════════════
# P1-04: System prompt generator
# ═══════════════════════════════════════════════════════════════

def generate_system_prompt(
    profile: Profile,
    personality: Personality,
    speech: Speech,
) -> str:
    """Generate a system prompt fragment from identity configs.

    The generated prompt can be injected directly into LLM context.
    """
    parts = []

    # 1. Identity header
    parts.append(f"你是 {profile.name}。")
    if profile.aliases:
        parts.append(f"你也可以被称为：{'、'.join(profile.aliases)}。")
    if profile.role:
        parts.append(f"你的角色定位是{profile.role}。")
    if profile.relationship_to_user:
        parts.append(f"你与用户的关系：{profile.relationship_to_user}。")

    # 2. Appearance
    if profile.appearance.summary:
        parts.append(f"外貌：{profile.appearance.summary}")

    # 3. Background
    if profile.background:
        parts.append(f"背景故事：{profile.background}")

    # 4. Personality traits
    if personality.traits:
        trait_lines = []
        for name, trait in personality.traits.items():
            trait_lines.append(f"  {name}: {trait.value:.0%}")
        parts.append("性格特质：\n" + "\n".join(trait_lines))
    if personality.archetype:
        parts.append(f"性格原型：{personality.archetype}")

    # 5. Core beliefs
    if profile.core_beliefs:
        parts.append(f"核心信条：{'、'.join(profile.core_beliefs)}")

    # 6. Speech style
    parts.append(f"语言风格：{speech.speech_style}。")
    if speech.address_user:
        parts.append(f"你称呼用户为：{'、'.join(speech.address_user)}。")
    if speech.address_self:
        parts.append(f"你自称：{'、'.join(speech.address_self)}。")
    if speech.catchphrases:
        parts.append(f"口头禅：{'、'.join(speech.catchphrases)}")

    # 7. Rules
    if profile.forbidden_words:
        parts.append(f"禁止使用的词汇：{'、'.join(profile.forbidden_words)}。")

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# P1-05: Forbidden words filter
# ═══════════════════════════════════════════════════════════════

def filter_forbidden_words(text: str, forbidden_words: list[str]) -> str:
    """Remove or replace forbidden words from output text.

    Returns the filtered text. Forbidden words are replaced with '***'.
    """
    if not forbidden_words or not text:
        return text
    result = text
    for word in forbidden_words:
        result = result.replace(word, "***")
    return result


# ═══════════════════════════════════════════════════════════════
# P1-06: Welcome message trigger
# ═══════════════════════════════════════════════════════════════

_WELCOME_FLAG_FILE = "_welcome_shown"


def get_welcome_message(profile: Profile, state_dir: str) -> str | None:
    """Return welcome_message on first load, None afterwards.

    Writes a flag file to state_dir to track first-load status.
    Returns None if the profile has no welcome_message.
    """
    if not profile.welcome_message:
        return None

    flag_path = os.path.join(state_dir, _WELCOME_FLAG_FILE)
    if os.path.isfile(flag_path):
        return None

    # Write flag so next call returns None
    os.makedirs(state_dir, exist_ok=True)
    with open(flag_path, "w") as f:
        f.write("1")
    return profile.welcome_message
