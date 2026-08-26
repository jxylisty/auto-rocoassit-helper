import sys; sys.path.insert(0,'.')
from src.gui.bridge import AppBridge
b=AppBridge()
r=b.pvp_calc_all_skills(7,4,
    atk_high_ivs=['attack','mattack','speed'],atk_iv_value=10,
    def_high_ivs=['attack','mattack','speed'],def_iv_value=10)
print('success:',r['success'])
print('atk:',r.get('atkName'),'panels:',{k:round(v) for k,v in r['atkPanels'].items()})
print('def:',r.get('defName'),'panels:',{k:round(v) for k,v in r['defPanels'].items()})
s=r['skills']
print(f'skills: {len(s)} total, {sum(1 for x in s if x["isDamage"])} damage')
for x in s[:10]:
    if x['isDamage']:
        print(f'  {x["name"]:8s} {x["type"]:3s} P={x["power"]:3d} mul={x["attrMultiplier"]:.1f} {x["minDamage"]:6.1f}~{x["maxDamage"]:6.1f}')
    else:
        print(f'  {x["name"]:8s} {x["type"]:3s} P=  0 mul=-   {x["minDamage"]:6.1f}~{x["maxDamage"]:6.1f} (status)')
print('\nTest IV=7:')
r2=b.pvp_calc_all_skills(7,4,atk_high_ivs=['attack','mattack','speed'],atk_iv_value=7,def_high_ivs=['attack','mattack','speed'],def_iv_value=10)
print(f'panels: { {k:round(v) for k,v in r2["atkPanels"].items()} }')
for x in r2['skills'][:3]:
    if x['isDamage']:
        print(f'  {x["name"]}: {x["minDamage"]:.1f}~{x["maxDamage"]:.1f}')