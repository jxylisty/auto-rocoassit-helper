"""High-level frame analysis pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.analysis.battle_detector import BattleDetector
from src.analysis.battle_state import BattleStateSnapshot
from src.ocr.base import ROI
from src.ocr.readers import AvatarMatcher, DamageReader, ElementMatcher, EnergyReader


DEFAULT_ROI_CONFIG = Path("data/vision/roi_config.json")


def load_roi_config(path: Path = DEFAULT_ROI_CONFIG) -> dict[str, ROI]:
    config = json.loads(path.read_text(encoding="utf-8"))
    return {name: ROI(name=name, **values) for name, values in config.items()}


class VisionPipeline:
    """Runs all frame readers and merges their outputs."""

    def __init__(self, roi_config_path: Path = DEFAULT_ROI_CONFIG):
        rois = load_roi_config(roi_config_path)
        self.damage_reader = DamageReader(rois["damage_number"])
        self.energy_reader = EnergyReader(rois["energy_number"])
        self.avatar_matcher = AvatarMatcher(rois["enemy_avatar"])
        self.element_matcher = ElementMatcher(rois["enemy_elements"])
        self.battle_detector = BattleDetector(
            rois["battle_left_indicator"],
            rois["battle_right_indicator"],
        )

    def analyze(self, frame: np.ndarray) -> BattleStateSnapshot:
        damage = self.damage_reader.read(frame)
        energy = self.energy_reader.read(frame)
        avatar = self.avatar_matcher.read(frame)
        elements = self.element_matcher.read(frame)
        battle = self.battle_detector.detect(frame)

        return BattleStateSnapshot(
            enemy_avatar=avatar,
            enemy_elements=elements,
            current_energy=energy,
            latest_damage=damage,
            raw={
                "battle": battle,
                "avatar_candidates": avatar.candidates,
                "element_candidates": elements.candidates,
                "energy_candidates": energy.candidates,
                "damage_candidates": damage.candidates,
            },
        )
