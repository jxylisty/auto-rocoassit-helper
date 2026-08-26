import json
from pathlib import Path

data = json.load(open(Path(r"D:\洛克王国ai\lkwgai_pvp_assistant\src\pvp\data\pet_detail.json"), "r", encoding="utf-8"))

pets = []
for seq_str, forms in data.items():
    for f in forms:
        race = f.get("race", {})
        if race:
            pets.append({
                "seq": int(seq_str), "name": f.get("page_title", ""),
                "hp": race.get("hp", 0), "atk": race.get("attack", 0),
                "matk": race.get("mattack", 0), "def": race.get("defense", 0),
                "mdef": race.get("mdefense", 0), "speed": race.get("speed", 0),
                "total": race.get("total", 0),
            })
            break

print(f"总精灵: {len(pets)}")
speeds = [p["speed"] for p in pets]
print(f"速度: min={min(speeds)} max={max(speeds)} avg={sum(speeds)/len(speeds):.0f}")

fast = [p for p in pets if p["speed"] > 115]
print(f"高速(>115): {len(fast)}只 ({len(fast)/len(pets)*100:.1f}%)")

tanks = [p for p in pets if p["atk"]<100 and p["matk"]<100 and p["speed"]<100 and (p["hp"]+p["def"]+p["mdef"])>300]
print(f"\n肉盾: {len(tanks)}只")
for t in tanks[:8]:
    print(f"  #{t['seq']} {t['name']}: HP={t['hp']} 攻={t['atk']} 魔攻={t['matk']} 防={t['def']} 魔防={t['mdef']} 速={t['speed']}")

slow_atk = [p for p in pets if p["speed"]<100 and (p["atk"]>120 or p["matk"]>120) and p not in tanks]
print(f"\n低速高攻: {len(slow_atk)}只")
for s in slow_atk[:8]:
    print(f"  #{s['seq']} {s['name']}: 攻={s['atk']} 魔攻={s['matk']} 速={s['speed']}")

bal = [p for p in pets if p not in tanks and p["speed"]<=115 and p not in slow_atk]
print(f"\n均衡型: {len(bal)}只")
for b in bal[:5]:
    print(f"  #{b['seq']} {b['name']}: 攻={b['atk']} 魔攻={b['matk']} 速={b['speed']}")

phys = sum(1 for p in pets if p["atk"] > p["matk"])
spec = sum(1 for p in pets if p["matk"] > p["atk"])
eq = sum(1 for p in pets if p["atk"] == p["matk"])
print(f"\n物攻>魔攻:{phys} 魔攻>物攻:{spec} 相等:{eq}")