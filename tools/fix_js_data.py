# -*- coding: utf-8 -*-
"""Fix type_chart.js and pvpRuleConfig.js conversions"""
import json, re

DST = r"D:\洛克王国ai\lkwgai_pvp_assistant\src\pvp\data"

# ---- Fix typeChart.js (uses 'const' not 'export const') ----
src = open(r"C:\Users\zzx05\Documents\HBuilderProjects\luokewangguo\data\config\typeChart.js", "r", encoding="utf-8").read()
m = re.search(r"const\s+rawTypeEffectChart\s*=\s*", src)
if m:
    start = m.end()
    depth = 0; in_str = False; esc = False; jstart = start
    for i in range(start, len(src)):
        ch = src[i]
        if esc: esc = False; continue
        if ch == "\\": esc = True; continue
        if ch == "'" and not esc: in_str = not in_str; continue
        if in_str: continue
        if ch == "{":
            if depth == 0: jstart = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                js_str = src[jstart:i+1]
                py_str = js_str.replace("'", '"')
                py_str = re.sub(r"(\w+):", r'"\1":', py_str)
                data = json.loads(py_str)
                with open(DST + "\\type_chart.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"type_chart.json: {len(data)} types")
                break

# ---- Fix pvpRuleConfig.js (unquoted keys) ----
src2 = open(r"C:\Users\zzx05\Documents\HBuilderProjects\luokewangguo\config\pvpRuleConfig.js", "r", encoding="utf-8").read()
m2 = re.search(r"export\s+const\s+PVP_RULES\s*=\s*", src2)
if m2:
    start = m2.end()
    depth = 0; in_str = False; esc = False; jstart = start
    for i in range(start, len(src2)):
        ch = src2[i]
        if esc: esc = False; continue
        if ch == "\\": esc = True; continue
        if ch == "'" and not esc: in_str = not in_str; continue
        if in_str: continue
        if ch == "{":
            if depth == 0: jstart = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                js_str = src2[jstart:i+1]
                py_str = js_str.replace("'", '"')
                py_str = re.sub(r"(\w+):", r'"\1":', py_str)
                data = json.loads(py_str)
                with open(DST + "\\pvp_rules.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print("pvp_rules.json: OK")
                break

print("Done!")