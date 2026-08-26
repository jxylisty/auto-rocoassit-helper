import json
from pathlib import Path

BASE = Path(r"D:\洛克王国ai\lkwgai_pvp_assistant\src\pvp\data")
with open(BASE / "avatar_map.json", "r", encoding="utf-8") as f:
    avatar_map = json.load(f)

av_dir = BASE / "avatars"
seq_to_file = {}
for entry in avatar_map:
    seq = entry["seq"]
    name = entry["page_title"]
    filename = f"{seq:03d}_{name}.png"
    if (av_dir / filename).exists() and seq not in seq_to_file:
        seq_to_file[seq] = filename

with open(BASE / "avatar_index.json", "w", encoding="utf-8") as f:
    json.dump(seq_to_file, f, ensure_ascii=False)

print(f"头像映射: {len(seq_to_file)} 个精灵")
for s in [1, 7, 4, 10, 20]:
    print(f"  seq={s} -> {seq_to_file.get(s, 'N/A')}")