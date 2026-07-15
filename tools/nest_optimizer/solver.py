from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

from ortools.sat.python import cp_model

SINGLE_SHINY_PERCENT_CENTI = 72
DOUBLE_SHINY_PERCENT_CENTI = 144


SPECIES = [
    {"name": "粉星仔", "aliases": ["粉耳星兔", "落陨星兔"], "groups": ["妖精"]},
    {"name": "粉粉星", "aliases": ["小皮球"], "groups": ["妖精"]},
    {"name": "酷拉", "aliases": ["拉特"], "groups": ["妖精"]},
    {"name": "雪影娃娃", "aliases": ["大耳帽兜"], "groups": ["妖精", "拟人"]},
    {"name": "治愈兔", "aliases": ["红绒十字"], "groups": ["妖精", "动物"]},
    {"name": "格兰球", "aliases": [], "groups": ["妖精", "植物"]},
    {"name": "月牙雪熊", "aliases": [], "groups": ["动物", "怪兽"]},
    {"name": "恶魔狼", "aliases": [], "groups": ["动物"]},
    {"name": "獠牙猪", "aliases": ["呼呼猪"], "groups": ["动物"]},
    {"name": "奇丽花", "aliases": [], "groups": ["植物"]},
    {"name": "燃薪虫", "aliases": ["柴渣虫"], "groups": ["植物", "昆虫"]},
    {"name": "窃光蚊", "aliases": ["嗜光嗡嗡"], "groups": ["昆虫"]},
    {"name": "空空颅", "aliases": ["夜宿颅", "夜枭"], "groups": ["怪兽"]},
    {"name": "机械方方", "aliases": [], "groups": ["机械", "拟人"]},
    {"name": "贝瑟", "aliases": ["贝古斯", "贝加尔"], "groups": ["机械"]},
    {"name": "利灯鱼", "aliases": ["双灯鱼"], "groups": ["海洋"]},
]


def _species_label(species: dict) -> str:
    return f'{species["name"]}（{" / ".join(species["aliases"])}）' if species["aliases"] else species["name"]


SPECIES_BY_INDEX = [{**species, "index": i, "label": _species_label(species)} for i, species in enumerate(SPECIES)]


def _share_group(left: int, right: int) -> bool:
    return bool(set(SPECIES_BY_INDEX[left]["groups"]) & set(SPECIES_BY_INDEX[right]["groups"]))


@dataclass(frozen=True)
class Variant:
    variant_id: str
    species_index: int
    sex: str
    is_shiny: bool
    stock: int
    role: str


@dataclass(frozen=True)
class Position:
    position_id: int
    x: int
    y: int

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x * 2 + 1, self.y * 2 + 1)


def default_board_size(max_nests: int) -> Tuple[int, int]:
    side = max(4, math.ceil(math.sqrt(max_nests)) * 2)
    return side, side


def generate_candidate_positions(board_width: int, board_height: int) -> List[Position]:
    positions: List[Position] = []
    pid = 0
    for y in range(board_height):
        for x in range(board_width):
            positions.append(Position(position_id=pid, x=x, y=y))
            pid += 1
    return positions


def overlap(left: Position, right: Position) -> bool:
    return not (
        left.x + 2 <= right.x
        or right.x + 2 <= left.x
        or left.y + 2 <= right.y
        or right.y + 2 <= left.y
    )


def near(left: Position, right: Position) -> bool:
    lx, ly = left.center
    rx, ry = right.center
    return abs(lx - rx) + abs(ly - ry) <= 5


def build_request_from_web(data: dict) -> dict:
    max_nests = int(data["nestCount"])
    board_width, board_height = default_board_size(max_nests)
    return {
        "max_nests": max_nests,
        "max_male": int(data["maleCount"]),
        "max_female": int(data["femaleCount"]),
        "mode": data.get("mode", "collection"),
        "inventory": data["inventory"],
        "board_width": board_width,
        "board_height": board_height,
    }


def build_variants(payload: dict) -> Tuple[List[Variant], List[int]]:
    statuses = payload["inventory"]["statuses"]
    shiny_males = payload["inventory"]["shinyMaleStocks"]
    shiny_females = payload["inventory"]["shinyFemaleStocks"]
    max_nests = int(payload["max_nests"])

    variants: List[Variant] = []
    target_species_indices: List[int] = []
    for species in SPECIES_BY_INDEX:
        index = species["index"]
        status = statuses[index]
        if status == "ignore":
            continue
        if status == "missing":
            target_species_indices.append(index)

        variants.append(Variant(f"{index}:male:normal", index, "male", False, max_nests, status))
        variants.append(Variant(f"{index}:female:normal", index, "female", False, max_nests, status))

        if shiny_males[index] > 0:
            variants.append(Variant(f"{index}:male:shiny", index, "male", True, int(shiny_males[index]), status))
        if shiny_females[index] > 0:
            variants.append(Variant(f"{index}:female:shiny", index, "female", True, int(shiny_females[index]), status))

    return variants, target_species_indices


def _build_model(payload: dict) -> dict:
    model = cp_model.CpModel()
    variants, target_species = build_variants(payload)
    positions = generate_candidate_positions(payload["board_width"], payload["board_height"])

    if not variants:
        raise ValueError("没有可用的精灵库存。")

    male_variants = [variant for variant in variants if variant.sex == "male"]
    female_variants = [variant for variant in variants if variant.sex == "female"]
    if not male_variants or not female_variants:
        raise ValueError("至少需要一个可用公本和一个可用母本。")

    assign_vars: Dict[Tuple[int, str], cp_model.IntVar] = {}
    active_vars: Dict[int, cp_model.IntVar] = {}

    for position in positions:
        active_vars[position.position_id] = model.NewBoolVar(f"active_{position.position_id}")
        local_vars = []
        for variant in variants:
            var = model.NewBoolVar(f"a_{position.position_id}_{variant.variant_id}")
            assign_vars[(position.position_id, variant.variant_id)] = var
            local_vars.append(var)
        model.Add(sum(local_vars) == active_vars[position.position_id])

    model.Add(sum(active_vars.values()) == int(payload["max_nests"]))
    model.Add(
        sum(assign_vars[(position.position_id, variant.variant_id)] for position in positions for variant in male_variants)
        == int(payload["max_male"])
    )
    model.Add(
        sum(assign_vars[(position.position_id, variant.variant_id)] for position in positions for variant in female_variants)
        == int(payload["max_female"])
    )

    for variant in variants:
        model.Add(sum(assign_vars[(position.position_id, variant.variant_id)] for position in positions) <= variant.stock)

    for i, left in enumerate(positions):
        for right in positions[i + 1 :]:
            if overlap(left, right):
                model.Add(active_vars[left.position_id] + active_vars[right.position_id] <= 1)

    edge_vars: Dict[Tuple[int, int, str, str], cp_model.IntVar] = {}
    target_edge_vars: List[cp_model.IntVar] = []
    total_edge_vars: List[cp_model.IntVar] = []
    double_shiny_terms: List[cp_model.LinearExpr] = []

    for female_pos in positions:
        for male_pos in positions:
            if female_pos.position_id == male_pos.position_id or not near(female_pos, male_pos):
                continue
            for female_variant in female_variants:
                for male_variant in male_variants:
                    if not _share_group(female_variant.species_index, male_variant.species_index):
                        continue
                    edge = model.NewBoolVar(
                        f"edge_{female_pos.position_id}_{male_pos.position_id}_{female_variant.variant_id}_{male_variant.variant_id}"
                    )
                    edge_vars[(female_pos.position_id, male_pos.position_id, female_variant.variant_id, male_variant.variant_id)] = edge
                    f_assign = assign_vars[(female_pos.position_id, female_variant.variant_id)]
                    m_assign = assign_vars[(male_pos.position_id, male_variant.variant_id)]
                    model.Add(edge <= f_assign)
                    model.Add(edge <= m_assign)
                    model.Add(edge >= f_assign + m_assign - 1)
                    total_edge_vars.append(edge)
                    if female_variant.species_index in target_species:
                        target_edge_vars.append(edge)
                    if female_variant.is_shiny and male_variant.is_shiny:
                        double_shiny_terms.append(edge * 2)
                    elif female_variant.is_shiny or male_variant.is_shiny:
                        double_shiny_terms.append(edge)

    cover_vars: Dict[int, cp_model.IntVar] = {}
    female_variant_by_id = {variant.variant_id: variant for variant in female_variants}
    for species_index in target_species:
        relevant = [
            edge
            for (female_pos, male_pos, female_variant_id, male_variant_id), edge in edge_vars.items()
            if female_variant_by_id[female_variant_id].species_index == species_index
        ]
        cover = model.NewBoolVar(f"cover_{species_index}")
        cover_vars[species_index] = cover
        if relevant:
            model.Add(sum(relevant) >= cover)
            model.Add(sum(relevant) <= len(relevant) * cover)
        else:
            model.Add(cover == 0)

    return {
        "model": model,
        "positions": positions,
        "variants": variants,
        "assign_vars": assign_vars,
        "edge_vars": edge_vars,
        "cover_vars": cover_vars,
        "z1": sum(cover_vars.values()) if cover_vars else 0,
        "z2": sum(target_edge_vars) if target_edge_vars else 0,
        "z3": sum(total_edge_vars) if total_edge_vars else 0,
        "z4": sum(double_shiny_terms) if double_shiny_terms else 0,
    }


def _solve_stage(model: cp_model.CpModel, objective: cp_model.LinearExpr, time_limit: float) -> Tuple[cp_model.CpSolver, int]:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 8
    model.Maximize(objective)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("求解失败，当前精确模型没有找到可行解。")
    return solver, int(round(solver.ObjectiveValue()))


def _pick_non_overlapping_positions(positions: List[Position], count: int) -> List[Position]:
    chosen: List[Position] = []
    for position in positions:
        if all(not overlap(position, existing) for existing in chosen):
            chosen.append(position)
            if len(chosen) == count:
                return chosen
    raise RuntimeError("候选窝位不足。")


def _pick_variants(variants: List[Variant], sex: str, count: int) -> List[Variant]:
    pool = [variant for variant in variants if variant.sex == sex]
    pool.sort(key=lambda item: (0 if item.role == "missing" else 1, 0 if item.is_shiny else 1, item.species_index))
    chosen: List[Variant] = []
    used: Dict[str, int] = {}

    # First pass: spread across species so fallback does not degenerate into
    # "fill every slot with the first target species".
    seen_species: set[int] = set()
    for variant in pool:
        if variant.species_index in seen_species:
            continue
        if used.get(variant.variant_id, 0) >= variant.stock:
            continue
        chosen.append(variant)
        used[variant.variant_id] = used.get(variant.variant_id, 0) + 1
        seen_species.add(variant.species_index)
        if len(chosen) == count:
            return chosen

    # Second pass: fill remaining slots by quality priority.
    for variant in pool:
        available = variant.stock - used.get(variant.variant_id, 0)
        while available > 0 and len(chosen) < count:
            chosen.append(variant)
            used[variant.variant_id] = used.get(variant.variant_id, 0) + 1
            available -= 1
        if len(chosen) == count:
            return chosen

    raise RuntimeError("可用精灵不足。")


def _build_result(payload: dict, positions: List[Position], assigned_pairs: List[Tuple[Position, Variant]], solver_status: str, is_optimal: bool, seconds: float) -> dict:
    assignments = []
    selected_positions = []
    covered_species = set()
    feasible_edges = []

    for position, variant in assigned_pairs:
        selected_positions.append(
            {
                "position_id": position.position_id,
                "x": position.x * 2,
                "y": position.y * 2,
                "sex": variant.sex,
            }
        )
        assignments.append(
            {
                "position_id": position.position_id,
                "x": position.x * 2,
                "y": position.y * 2,
                "sex": variant.sex,
                "sex_label": "雄性" if variant.sex == "male" else "雌性",
                "species_index": variant.species_index,
                "species_name": SPECIES_BY_INDEX[variant.species_index]["name"],
                "species_label": SPECIES_BY_INDEX[variant.species_index]["label"],
                "groups": SPECIES_BY_INDEX[variant.species_index]["groups"],
                "is_shiny": variant.is_shiny,
                "rarity_label": "异色" if variant.is_shiny else "普通",
                "role": variant.role,
            }
        )

    females = [(position, variant) for position, variant in assigned_pairs if variant.sex == "female"]
    males = [(position, variant) for position, variant in assigned_pairs if variant.sex == "male"]
    for female_pos, female_variant in females:
        for male_pos, male_variant in males:
            if not near(female_pos, male_pos):
                continue
            if not _share_group(female_variant.species_index, male_variant.species_index):
                continue
            feasible_edges.append(
                {
                    "female_position_id": female_pos.position_id,
                    "male_position_id": male_pos.position_id,
                    "female_species": SPECIES_BY_INDEX[female_variant.species_index]["name"],
                    "male_species": SPECIES_BY_INDEX[male_variant.species_index]["name"],
                    "female_rarity": "异色" if female_variant.is_shiny else "普通",
                    "male_rarity": "异色" if male_variant.is_shiny else "普通",
                    "offspring_species": SPECIES_BY_INDEX[female_variant.species_index]["name"],
                    "distance": abs(female_pos.center[0] - male_pos.center[0]) + abs(female_pos.center[1] - male_pos.center[1]),
                }
            )
            if female_variant.role == "missing":
                covered_species.add(female_variant.species_index)

    target_pairs = sum(1 for edge in feasible_edges for female_pos, female_variant in females if female_pos.position_id == edge["female_position_id"] and female_variant.role == "missing")
    single_pairs = sum(1 for edge in feasible_edges if (edge["female_rarity"] == "异色") ^ (edge["male_rarity"] == "异色"))
    double_pairs = sum(1 for edge in feasible_edges if edge["female_rarity"] == "异色" and edge["male_rarity"] == "异色")
    double_score = single_pairs + double_pairs * 2

    return {
        "solver_status": solver_status,
        "is_globally_optimal": is_optimal,
        "solve_seconds": round(seconds, 3),
        "objective_values": {
            "Z1": len(covered_species),
            "Z2": target_pairs,
            "Z3": len(feasible_edges),
            "Z4": double_score,
            "covered_target_species": len(covered_species),
            "target_pairs": target_pairs,
            "total_pairs": len(feasible_edges),
            "double_shiny_score": double_score,
            "expected_shiny_percent_centi": single_pairs * SINGLE_SHINY_PERCENT_CENTI + double_pairs * DOUBLE_SHINY_PERCENT_CENTI,
            "single_shiny_percent_centi": SINGLE_SHINY_PERCENT_CENTI,
            "double_shiny_percent_centi": DOUBLE_SHINY_PERCENT_CENTI,
        },
        "selected_positions": selected_positions,
        "assignments": assignments,
        "feasible_mating_edges": feasible_edges,
        "covered_target_species": [SPECIES_BY_INDEX[index]["name"] for index in sorted(covered_species)],
        "board": {
            "width": payload["board_width"],
            "height": payload["board_height"],
        },
        "meta": {
            "max_nests": payload["max_nests"],
            "max_male": payload["max_male"],
            "max_female": payload["max_female"],
            "candidate_position_count": len(positions),
        },
    }


def _safe_fallback(payload: dict, built: dict, started: float) -> dict:
    chosen_positions = _pick_non_overlapping_positions(built["positions"], int(payload["max_nests"]))
    female_variants = _pick_variants(built["variants"], "female", int(payload["max_female"]))
    male_variants = _pick_variants(built["variants"], "male", int(payload["max_male"]))
    assigned_pairs: List[Tuple[Position, Variant]] = []
    for position, variant in zip(chosen_positions[: int(payload["max_female"])], female_variants):
        assigned_pairs.append((position, variant))
    for position, variant in zip(chosen_positions[int(payload["max_female"]) :], male_variants):
        assigned_pairs.append((position, variant))
    return _build_result(payload, built["positions"], assigned_pairs, "SAFE_FALLBACK", False, time.perf_counter() - started)


def solve_exact(payload: dict, progress_callback: Callable[[str, int, int], None] | None = None) -> dict:
    started = time.perf_counter()
    built = _build_model(payload)
    model: cp_model.CpModel = built["model"]
    try:
        if progress_callback:
            progress_callback("第 1 步：先最大化目标异色种类", 1, 4)
        solver1, z1 = _solve_stage(model, built["z1"], 5.0)
        model.Add(built["z1"] == z1)
        if progress_callback:
            progress_callback("第 2 步：固定种类数，再最大化目标蛋数", 2, 4)
        solver2, z2 = _solve_stage(model, built["z2"], 5.0)
        model.Add(built["z2"] == z2)
        if progress_callback:
            progress_callback("第 3 步：固定前两项，再最大化总蛋数", 3, 4)
        solver3, z3 = _solve_stage(model, built["z3"], 5.0)
        model.Add(built["z3"] == z3)
        if progress_callback:
            progress_callback("第 4 步：最后比较异色加成", 4, 4)
        solver4, _ = _solve_stage(model, built["z4"], 6.0)
    except RuntimeError:
        return _safe_fallback(payload, built, started)

    assigned_pairs: List[Tuple[Position, Variant]] = []
    for position in built["positions"]:
        for variant in built["variants"]:
            if solver4.Value(built["assign_vars"][(position.position_id, variant.variant_id)]):
                assigned_pairs.append((position, variant))
                break

    return _build_result(
        payload,
        built["positions"],
        assigned_pairs,
        solver4.StatusName(),
        solver4.StatusName() == "OPTIMAL",
        time.perf_counter() - started,
    )
