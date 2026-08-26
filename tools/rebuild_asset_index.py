"""重建素材索引（含 title 映射）"""
import json, re
from pathlib import Path

DST = Path(r"D:\洛克王国ai\lkwgai_pvp_assistant\src\pvp\data\assets")

# 1. 精灵头像: seq → filename + title → filename
pet_index = {}
title_index = {}
for f in sorted((DST / "pets").glob("*.webp")):
    m = re.match(r"(\d+)_(.+)\.webp", f.stem)
    if m:
        seq = int(m.group(1))
        title = m.group(2)
        if seq not in pet_index:
            pet_index[seq] = f.name
        title_index[title] = f.name

with open(DST / "pet_index.json", "w", encoding="utf-8") as fp:
    json.dump(pet_index, fp, ensure_ascii=False)
with open(DST / "pet_title_index.json", "w", encoding="utf-8") as fp:
    json.dump(title_index, fp, ensure_ascii=False)
print(f"精灵头像: seq={len(pet_index)} title={len(title_index)}")

# 2. 技能: name → filename
skill_index = {f.stem: f.name for f in sorted((DST / "skills").glob("*.webp"))}
with open(DST / "skill_index.json", "w", encoding="utf-8") as fp:
    json.dump(skill_index, fp, ensure_ascii=False)
print(f"技能图标: {len(skill_index)}")

# 3. 验证
for t in ["迪莫", "火神", "烈火战神", "魔力猫", "水灵", "瞌睡王"]:
    fn = f"{title_index.get(t, 'N/A')}"
    ok = (DST / "pets" / fn).exists() if fn != "N/A" else False
    print(f"  {t:6s} → {fn:30s} 存在={ok}")