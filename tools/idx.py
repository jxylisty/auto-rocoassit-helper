import json, re
from pathlib import Path

d = Path(r"D:\洛克王国ai\lkwgai_pvp_assistant\src\pvp\data\assets")

pi, ti = {}, {}
for f in sorted((d / "pets").glob("*.webp")):
    m = re.match(r"(\d+)_(.+)\.webp", f.name)
    if m:
        seq = int(m.group(1))
        title = m.group(2)
        if seq not in pi:
            pi[seq] = f.name
        ti[title] = f.name

json.dump(pi, open(d / "pet_index.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump(ti, open(d / "pet_title_index.json", "w", encoding="utf-8"), ensure_ascii=False)
print(f"seq={len(pi)} title={len(ti)}")
for t in ["迪莫", "火神", "烈火战神", "魔力猫", "水灵"]:
    print(f"  {t}: {ti.get(t, '?')}")