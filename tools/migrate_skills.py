"""迁移旧项目技能数据 JS → JSON"""
import json, re

# 1. 技能数据
src = r"C:\Users\zzx05\Documents\HBuilderProjects\luokewangguo\data\skill\skills.js"
with open(src, 'r', encoding='utf-8') as f:
    text = f.read()
# 提取 JSON 对象
start = text.index('{')
depth = 0
end = start
for i in range(start, len(text)):
    if text[i] == '{': depth += 1
    elif text[i] == '}':
        depth -= 1
        if depth == 0:
            end = i + 1
            break
json_str = text[start:end]
# 修复 JS 格式 → JSON: 移除尾逗号
json_str = re.sub(r',\s*}', '}', json_str)
json_str = re.sub(r',\s*]', ']', json_str)
skills = json.loads(json_str)
print(f"技能数据: {len(skills)} 个")

# 2. 技能图标
src2 = r"C:\Users\zzx05\Documents\HBuilderProjects\luokewangguo\data\skill\skill_icons.js"
with open(src2, 'r', encoding='utf-8') as f:
    text2 = f.read()
start2 = text2.index('{')
depth2 = 0
end2 = start2
for i in range(start2, len(text2)):
    if text2[i] == '{': depth2 += 1
    elif text2[i] == '}':
        depth2 -= 1
        if depth2 == 0:
            end2 = i + 1
            break
json_str2 = text2[start2:end2]
json_str2 = re.sub(r',\s*}', '}', json_str2)
icons = json.loads(json_str2)
# 转换为本地路径
for k, v in icons.items():
    if v.startswith('http'):
        fn = v.split('/')[-1]
        icons[k] = f"data/pvp/skill_icons/{fn}"
    elif v.startswith('/cdn-assets/'):
        fn = v.split('/')[-1]
        icons[k] = f"data/pvp/skill_icons/{fn}"
print(f"技能图标: {len(icons)} 个")

# 3. 技能标签规则
src3 = r"C:\Users\zzx05\Documents\HBuilderProjects\luokewangguo\data\skill\skill_tag_rules.js"
with open(src3, 'r', encoding='utf-8') as f:
    text3 = f.read()
# 提取数组
order_match = re.search(r'\[([^\]]+)\]', text3)
rules_match = re.findall(r"\{ tag: '([^']+)', patterns: \[([^\]]+)\]", text3)
tag_order = re.findall(r"'([^']+)'", order_match.group(1))
tag_rules = []
for tag, patterns in rules_match:
    p_list = re.findall(r"/([^/]+)/", patterns)
    tag_rules.append({"tag": tag, "patterns": p_list})
tags_data = {"order": tag_order, "rules": tag_rules}
print(f"技能标签规则: {len(tag_rules)} 条")

# 4. 宠物技能映射
src4 = r"C:\Users\zzx05\Documents\HBuilderProjects\luokewangguo\crawler_official_api\pet_skills.json"
try:
    with open(src4, 'r', encoding='utf-8') as f:
        pet_skills_raw = json.load(f)
    pet_skills = {}
    for entry in pet_skills_raw:
        if isinstance(entry, list) and len(entry) >= 2:
            name = str(entry[0])
            pet_skills[name] = entry[1:]
    print(f"宠物技能映射: {len(pet_skills)} 个")
except Exception as e:
    print(f"宠物技能映射: {e}")
    pet_skills = {}

# 写入
out_dir = r"D:\洛克王国ai\lkwgai_pvp_assistant\data\pvp"
import os
os.makedirs(out_dir, exist_ok=True)

with open(os.path.join(out_dir, "skills.json"), 'w', encoding='utf-8') as f:
    json.dump(skills, f, ensure_ascii=False, indent=2)
print(f"  → data/pvp/skills.json")

with open(os.path.join(out_dir, "skill_icons.json"), 'w', encoding='utf-8') as f:
    json.dump(icons, f, ensure_ascii=False, indent=2)
print(f"  → data/pvp/skill_icons.json")

with open(os.path.join(out_dir, "skill_tags.json"), 'w', encoding='utf-8') as f:
    json.dump(tags_data, f, ensure_ascii=False, indent=2)
print(f"  → data/pvp/skill_tags.json")

with open(os.path.join(out_dir, "pet_skills.json"), 'w', encoding='utf-8') as f:
    json.dump(pet_skills, f, ensure_ascii=False, indent=2)
print(f"  → data/pvp/pet_skills.json")

print("\n✅ 迁移完成")