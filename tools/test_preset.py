"""测试智能预设对各种精灵的推荐"""
import sys; sys.path.insert(0, '.')
from src.gui.bridge import AppBridge

b = AppBridge()

test_cases = [
    (7, "火神"),       # 高速: atk=130, matk=120, speed=130
    (4, "魔力猫"),     # 均衡: atk=109, matk=109, speed=55
    (1, "迪莫"),       # 肉盾: atk=80, matk=80, speed=92, hp+def+mdef=330
    (10, "水灵"),      # 低速高攻: matk=127, speed=85
    (75, "瞌睡王"),    # 低速高攻: atk=167, speed=75
    (20, "岚鸟"),      # 高速: speed=115 (边界)
    (62, "巨噬针鼹"),  # 肉盾: atk=93, matk=41, speed=85, hp+def+mdef=343
    (29, "布克棱岩"),  # 低速高攻: atk=135, speed=70
    (81, "暴力兔"),    # 高速: speed=135
    (2, "喵喵"),       # 低速均衡: atk=66, matk=66, speed=33
]

for seq, name in test_cases:
    r = b.pvp_get_pet_preset(seq)
    if r['success']:
        print(f"#{seq:3d} {name:8s} "
              f"IV=[{','.join(h[:2] for h in r['high_ivs'])}] "
              f"性格: {r['nature_up']}+ {r['nature_down']}- "
              f"(速={r['race']['speed']} 攻={r['race']['attack']} 魔攻={r['race']['mattack']})")
    else:
        print(f"#{seq} {name}: FAIL - {r['message']}")