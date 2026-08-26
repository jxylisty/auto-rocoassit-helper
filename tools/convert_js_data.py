# -*- coding: utf-8 -*-
"""将 luokewangguo 项目的 JS 数据文件转换为 JSON"""

import json
import re
from pathlib import Path

SRC = Path(r"C:\Users\zzx05\Documents\HBuilderProjects\luokewangguo")
DST = Path(r"D:\洛克王国ai\lkwgai_pvp_assistant\src\pvp\data")
DST.mkdir(parents=True, exist_ok=True)


def js_export_to_json(js_path: Path, var_name: str):
    """Extract `export const varName = {...};` or `export const varName = [...];` from JS file."""
    content = js_path.read_text(encoding="utf-8")

    pattern = rf"export\s+const\s+{var_name}\s*=\s*"
    match = re.search(pattern, content)
    if not match:
        print(f"  [SKIP] {var_name} not found in {js_path.name}")
        return None

    start = match.end()
    depth = 0
    in_string = False
    escape_next = False
    json_start = start

    for i in range(start, len(content)):
        ch = content[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            if depth == 0:
                json_start = i
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                json_str = content[json_start : i + 1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError as e:
                    print(f"  [WARN] JSON parse error for {var_name}: {e}")
                    print(f"  First 200 chars: {json_str[:200]}")
                    return None

    print(f"  [WARN] Could not find end of {var_name}")
    return None


def save_json(data, filename):
    if data is None:
        return
    path = DST / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    size_kb = path.stat().st_size / 1024
    if isinstance(data, dict):
        print(f"  ✓ {filename} ({len(data)} entries, {size_kb:.0f} KB)")
    elif isinstance(data, list):
        print(f"  ✓ {filename} ({len(data)} items, {size_kb:.0f} KB)")
    else:
        print(f"  ✓ {filename} ({size_kb:.0f} KB)")


# ---- 1. pet_detail.js (also exports petTypes, rarityColors) ----
print("1. pet_detail.js")
save_json(js_export_to_json(SRC / "data/pet/pet_detail.js", "petTypes"), "pet_types.json")
save_json(js_export_to_json(SRC / "data/pet/pet_detail.js", "petDetail"), "pet_detail.json")
save_json(js_export_to_json(SRC / "data/pet/pet_detail.js", "rarityColors"), "rarity_colors.json")

# ---- 2. pet_index.js ----
print("2. pet_index.js")
save_json(js_export_to_json(SRC / "data/pet/pet_index.js", "petIndex"), "pet_index.json")

# ---- 3. pet_skills.js ----
print("3. pet_skills.js")
save_json(js_export_to_json(SRC / "data/pet/pet_skills.js", "petSkills"), "pet_skills.json")

# ---- 4. pet_race_speed.js ----
print("4. pet_race_speed.js")
save_json(js_export_to_json(SRC / "data/pet/pet_race_speed.js", "petRaceSpeed"), "pet_race_speed.json")

# ---- 5. skills.js ----
print("5. skills.js")
save_json(js_export_to_json(SRC / "data/skill/skills.js", "skillsData"), "skills.json")

# ---- 6. typeChart.js ----
print("6. typeChart.js")
save_json(js_export_to_json(SRC / "data/config/typeChart.js", "rawTypeEffectChart"), "type_chart.json")

# ---- 7. leader_forms.js ----
print("7. leader_forms.js")
save_json(js_export_to_json(SRC / "data/pet/leader_forms.js", "leaderFormPetIds"), "leader_forms.json")

# ---- 8. pvpRuleConfig.js ----
print("8. pvpRuleConfig.js")
save_json(js_export_to_json(SRC / "config/pvpRuleConfig.js", "PVP_RULES"), "pvp_rules.json")

print("\n✅ 全部转换完成！")