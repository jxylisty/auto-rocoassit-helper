"""Battle state data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from src.ocr.base import RecognitionResult


@dataclass
class BattleStateSnapshot:
    """Single-frame structured state extracted from the game UI."""

    enemy_name: RecognitionResult[str]
    enemy_elements: RecognitionResult[list[str]]
    enemy_hp: RecognitionResult[int]
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enemy_name": self.enemy_name.value,
            "enemy_name_confidence": self.enemy_name.confidence,
            "enemy_elements": self.enemy_elements.value,
            "enemy_elements_confidence": self.enemy_elements.confidence,
            "enemy_hp": self.enemy_hp.value,
            "enemy_hp_confidence": self.enemy_hp.confidence,
            "enemy_hp_raw": self.enemy_hp.debug.get("raw"),
            "battle": self.raw.get("battle"),
            "raw": self.raw,
        }
