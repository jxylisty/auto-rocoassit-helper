"""Battle state data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.ocr.base import RecognitionResult


@dataclass
class BattleStateSnapshot:
    """Single-frame structured state extracted from the game UI."""

    enemy_avatar: RecognitionResult[str]
    enemy_elements: RecognitionResult[list[str]]
    current_energy: RecognitionResult[int]
    latest_damage: RecognitionResult[int]
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enemy_avatar": self.enemy_avatar.value,
            "enemy_avatar_confidence": self.enemy_avatar.confidence,
            "enemy_elements": self.enemy_elements.value,
            "enemy_elements_confidence": self.enemy_elements.confidence,
            "current_energy": self.current_energy.value,
            "current_energy_confidence": self.current_energy.confidence,
            "latest_damage": self.latest_damage.value,
            "latest_damage_confidence": self.latest_damage.confidence,
            "battle": self.raw.get("battle"),
            "raw": self.raw,
        }
