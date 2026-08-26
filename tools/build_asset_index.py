"""构建素材索引文件"""
import json, re
from pathlib import Path

DST = Path(r"D:\洛克王国ai\lkwgai_pvp_assistant\src\pvp\data\assets")

# 1. 精灵头像索引 {seq: filename}
pet_index = {}
for f in sorted((DST / "pets").glob("*.webp")):
    m = re.match(r"(\d+)_", f.stem)
    if m:
        seq = int(m.group(1))
        if seq not in pet_index:
            pet_index[seq] = f.name
with open(DST / "pet_index.json", "w", encoding="utf-8") as fp:
    json.dump(pet_index, fp, ensure_ascii=False)
print(f"精灵头像索引: {len(pet_index)} 个 (去重后)")

# 2. 技能图标索引 {name: filename}
skill_index = {}
for f in sorted((DST / "skills").glob("*.webp")):
    skill_index[f.stem] = f.name
with open(DST / "skill_index.json", "w", encoding="utf-8") as fp:
    json.dump(skill_index, fp, ensure_ascii=False)
print(f"技能图标索引: {len(skill_index)} 个")

# 3. 属性图标映射 {english: chinese}
icon_map = {
    "fire": "火", "water": "水", "grass": "草", "electric": "电",
    "ice": "冰", "bug": "虫", "flying": "翼", "ground": "地",
    "fairy": "萌", "fighting": "武", "poison": "毒", "dragon": "龙",
    "ghost": "幽", "dark": "恶", "light": "光", "normal": "普通",
    "steel": "机械", "psychic": "幻",
}
with open(DST / "icon_map.json", "w", encoding="utf-8") as fp:
    json.dump(icon_map, fp, ensure_ascii=False)
print(f"属性图标映射: {len(icon_map)} 个")

# 4. 验证
for s in [1, 7, 4, 10, 20]:
    print(f"  seq={s} → {pet_index.get(s, 'N/A')} 存在={pet_index.get(s) and (DST / 'pets' / pet_index[s]).exists()}")
print(f"  火系图标 → fire.webp 存在={(DST / 'icons' / 'fire.webp').exists()}")