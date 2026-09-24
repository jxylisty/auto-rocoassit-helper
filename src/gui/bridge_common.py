"""AppBridge 共享模块级常量与配置注册表(路径 / CONFIG_FILES / DEV_MODE / TOOLS)。冻结模式下 app_entry.py 在导入 bridge 前补丁本模块的路径常量。"""

import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 前端资源目录: 源码=src/gui/web; 冻结版由 app_entry 重定向到 sys._MEIPASS/web
WEB_DIR = Path(__file__).resolve().parent / "web"
# 视觉工坊独立目录(不随主前端迭代变动): src/gui/studio; 冻结版同样重定向
STUDIO_DIR = Path(__file__).resolve().parent / "studio"


# ========================================
# 配置中心: 可编辑文件注册表
# ========================================

CONFIG_DIR = PROJECT_ROOT / "data" / "config"
CONFIG_FILES = {
    "throw_ball_config.json": {
        "title": "丢球与按键延时",
        "icon": "⚾",
        "type": "json",
        "desc": "普通丢球/轰炸机/技能按键延迟与遭遇战斗退出开关（丢球助手页面滑杆自动写入）",
        "page_hint": "丢球助手",
        "gui_page": "throw",
        "fields": [
            {"key": "normal_min / normal_max", "name": "普通蓄力时间", "desc": "普通丢球单次鼠标左键蓄力时间范围（秒），推荐 0.35s ~ 0.5s"},
            {"key": "bomber_charge_min / bomber_charge_max", "name": "轰炸机蓄力时间", "desc": "轰炸机模式丢球鼠标左键蓄力时间范围（秒），推荐 0.3s ~ 0.5s"},
            {"key": "bomber_hover_min / bomber_hover_max", "name": "悬浮按空格间隔", "desc": "轰炸机模式保持飞行高度的空格按键间隔（秒），推荐 2.0s ~ 2.2s"},
            {"key": "skill_min / skill_max", "name": "技能释放间隔", "desc": "自动技能模式交替按 3 与 X 键的时间间隔（秒），推荐 1.0s ~ 2.0s"},
            {"key": "exit_on_battle", "name": "遭遇战斗自动退出", "desc": "是否在检测到遭遇战斗画面时立即自动停止丢球与按键（true/false）"}
        ]
    },
    "ai_vision.json": {
        "title": "AI 视觉识别 (状态栏识图 + 战术决策)",
        "icon": "🤖",
        "type": "json",
        "desc": "多模态 AI 读状态栏识别状态/印记 + AI 战术决策引擎（PVP 对战页「AI 识别」标签页可视化配置）",
        "page_hint": "PVP 对战",
        "gui_page": "pvp",
        "fields": [
            {"key": "enabled", "name": "AI视觉总开关", "desc": "开启后 PVP 识别管线按间隔调用 AI 读状态栏（true/false）"},
            {"key": "base_url", "name": "API 地址(视觉)", "desc": "OpenAI 兼容接口地址，本地豆包桥为 http://127.0.0.1:7868/v1"},
            {"key": "api_key", "name": "API Key(视觉)", "desc": "接口密钥，本地豆包桥固定为 DoubaoAPI"},
            {"key": "model", "name": "视觉模型名", "desc": "多模态模型：doubao/vision-express（识图+推理）或 doubao/vision（纯识图）"},
            {"key": "prompt", "name": "识图提示词", "desc": "发给模型的识别要求，留空使用内置提示词"},
            {"key": "interval_s", "name": "识别间隔(秒)", "desc": "同一状态栏两次 AI 识别的最小间隔，避免刷接口"},
            {"key": "template", "name": "ROI 模板", "desc": "状态栏框位来源（视觉工坊画的模板名，如 pvp状态）"},
            {"key": "ai_decision_enabled", "name": "AI战术决策总开关", "desc": "开启后每2秒自动分析战局并推荐动作（true/false）"},
            {"key": "ai_decision_base_url", "name": "API 地址(决策)", "desc": "战术决策用的 LLM 接口，默认为 http://127.0.0.1:7863/v1"},
            {"key": "ai_decision_api_key", "name": "API Key(决策)", "desc": "战术决策 LLM 的密钥，默认为 WildWorkAPI"},
            {"key": "ai_decision_model", "name": "决策模型名", "desc": "战术决策用的 LLM 模型，默认为 codebuddy/deepseek-v4.1-flash"},
            {"key": "ai_decision_interval_s", "name": "决策刷新间隔(秒)", "desc": "AI 自动刷新建议的间隔，默认 2 秒"}
        ]
    },
    "ai_companion.json": {
        "title": "AI 陪玩伙伴 (对局弹幕伙伴)",
        "icon": "💬",
        "type": "json",
        "desc": "对局事件驱动 → OpenAI 兼容 LLM → 悬浮窗弹幕（PVP 对战页「AI 伙伴」标签页可视化配置）",
        "page_hint": "PVP 对战",
        "gui_page": "pvp",
        "fields": [
            {"key": "enabled", "name": "总开关", "desc": "开启后 AI 伙伴会在对局中根据事件发弹幕（true/false）"},
            {"key": "base_url", "name": "API 地址", "desc": "OpenAI 兼容接口地址，如 https://api.deepseek.com/v1"},
            {"key": "api_key", "name": "API Key", "desc": "调用 LLM 的 API 密钥"},
            {"key": "model", "name": "模型名", "desc": "LLM 模型名，如 deepseek-chat / gpt-4o-mini"},
            {"key": "persona", "name": "人设", "desc": "内置人设：salty(毒舌主播)/tsundere(傲娇伙伴)/gentle(温柔鼓励)"},
            {"key": "custom_persona", "name": "自定义人设提示词", "desc": "非空时覆盖内置人设，自由描述想要的角色风格"},
            {"key": "interval_min", "name": "弹幕最小间隔(秒)", "desc": "两条弹幕之间的最小间隔(秒)，防刷屏"}
        ]
    },
    "settings.yaml": {
        "title": "挂机引擎与全局设置",
        "icon": "⚔️",
        "type": "yaml",
        "desc": "挂机战斗策略、技能轮换、巡逻走动与全局超时设置（挂机引擎页面表单自动写入）",
        "page_hint": "挂机引擎",
        "gui_page": "engine",
        "fields": [
            {"key": "battle.catch_hp", "name": "捕获血线阈值", "desc": "敌方血量百分比小于等于此数值时自动按键丢球（默认 50%）"},
            {"key": "battle.open_ball_key", "name": "打开丢球界面键", "desc": "战斗中用于呼出丢球界面的键盘按键（默认 w）"},
            {"key": "battle.ball_slot_key", "name": "球槽按键", "desc": "丢球界面中对应球槽的数字键（默认 1）"},
            {"key": "battle.skills", "name": "技能轮换列表", "desc": "未到丢球血线时按顺序释放的技能按键列表（如 [\"1\"]）"},
            {"key": "patrol.enabled", "name": "巡逻找怪开关", "desc": "战斗间隙是否自动走动找怪（true/false）"},
            {"key": "patrol.move_key", "name": "巡逻走动键", "desc": "巡逻时持续按住的键盘走动键（默认 w）"},
            {"key": "patrol.turn_mode", "name": "巡逻转向方式", "desc": "mouse 为鼠标平滑转动镜头，keys 为 A/D 键侧移转向"}
        ]
    },
    "roi_config.json": {
        "title": "画面识别区域 (ROI)",
        "icon": "📐",
        "type": "json",
        "desc": "战斗中精灵名、血量、属性图标所在屏幕归一化百分比坐标（视觉调试台拖框标注同源）",
        "page_hint": "视觉调试台",
        "gui_page": "vision",
        "fields": [
            {"key": "enemy_name", "name": "敌方精灵名称区域", "desc": "对战 HUD 上方敌方精灵名字所在的坐标矩形 {left, top, width, height}"},
            {"key": "enemy_hp", "name": "敌方血量百分比区域", "desc": "敌方血条旁百分比数字（如 100%）所在的坐标矩形"},
            {"key": "enemy_elements", "name": "敌方属性图标区域", "desc": "敌方属性主图标所在区域"},
            {"key": "battle_left / battle_right", "name": "战斗判定角标", "desc": "用于模板匹配判断是否在战斗中的 UI 角标区域"}
        ]
    },
    "pet_names.txt": {
        "title": "精灵名称词库",
        "icon": "📖",
        "type": "txt",
        "desc": "OCR 精灵名识别纠错词库，每行一个精灵名。游戏出新精灵时可在此另起一行添加",
        "page_hint": "词库字典",
        "gui_page": "",
        "fields": [
            {"key": "每行一个精灵名称", "name": "精灵词条", "desc": "包含迪莫、喵喵、火神等 600+ 常见精灵全称。OCR 模糊识别时会优先在此名单中寻找最相似匹配。"}
        ]
    },
}

# 每个丢球延迟参数的合法范围（秒）
CONFIG_SCHEMA = {
    "normal_min":        (0.1, 3.0),
    "normal_max":        (0.1, 3.0),
    "bomber_charge_min": (0.05, 2.0),
    "bomber_charge_max": (0.05, 2.0),
    "bomber_hover_min":  (0.3, 8.0),
    "bomber_hover_max":  (0.3, 8.0),
    "skill_min":         (0.2, 10.0),
    "skill_max":         (0.2, 10.0),
    "stop_after_count":  (0, 99999),
    "stop_after_minutes": (0, 720),
}
CONFIG_PAIRS = [
    ("normal_min", "normal_max"),
    ("bomber_charge_min", "bomber_charge_max"),
    ("bomber_hover_min", "bomber_hover_max"),
    ("skill_min", "skill_max"),
]

# ========================================
# 运行模式: 源码运行默认开发者版; PyInstaller 打包强制用户版。
# 安全: 打包版不接受 LKW_DEV_MODE 环境变量(否则用户设 =1 即可白嫖付费功能);
# 开发者要预览用户版体验, 在源码运行时设 LKW_DEV_MODE=0。
# ========================================
if getattr(sys, "frozen", False):
    DEV_MODE = False
else:
    _env_dev = os.environ.get("LKW_DEV_MODE")
    DEV_MODE = (_env_dev != "0")

# ========================================
# 工具箱: 可启动工具注册表
# ========================================

TOOLS = [
    {"id": "snip", "name": "手动框选截图", "script": "tools/snip_capture.py",
     "gui": True, "arg": "none", "category": "visual", "tag": "GUI 标注",
     "desc": "全屏暗化拖拽框选任意区域，保存后自动打开裁剪工具（制作角标模板首选）"},
    {"id": "crop", "name": "模板裁剪工具", "script": "tools/crop_template_tool.py",
     "gui": True, "arg": "shot", "category": "visual", "tag": "GUI 标注",
     "desc": "自动截取游戏窗口并打开裁剪器（可视化裁剪并保存左右角标模板）"},
    {"id": "clicker", "name": "鼠标连点器", "script": "tools/auto_click_macro.py",
     "gui": True, "arg": "none", "category": "helper", "tag": "独立小窗",
     "desc": "独立置顶小窗连点器，F6 取坐标 / F7 开关 / F10 急停（全局热键）"},
    {"id": "envcheck", "name": "截图环境诊断", "script": "tools/check_capture_env.py",
     "gui": False, "arg": "none", "category": "diag", "tag": "环境诊断",
     "desc": "检查 Windows 窗口句柄获取能力与截图权限，诊断输出到运行日志"},
    {"id": "demovision", "name": "视觉管线测试", "script": "tools/demo_vision_pipeline.py",
     "gui": False, "arg": "last", "category": "diag", "tag": "管线自检",
     "desc": "对最新游戏画面测试 OCR 与战斗角标匹配，检测识别是否正常"},
    {"id": "roiexport", "name": "ROI 切片导出", "script": "tools/export_roi_samples.py",
     "gui": False, "arg": "last", "category": "diag", "tag": "切片导出",
     "desc": "按 ROI 配置把最近游戏画面切成小图批量导出到 data/vision/exports"},
    {"id": "diag_hp", "name": "血量 OCR 诊断", "script": "tools/diag_hp.py",
     "gui": False, "arg": "last", "category": "diag", "tag": "OCR 诊断",
     "desc": "截取敌方血量区域并打印 4 种二值化阈值与 Tesseract 识别细节"},
    {"id": "test_pvp", "name": "PVP 引擎自检", "script": "tools/test_pvp_full.py",
     "gui": False, "arg": "none", "category": "diag", "tag": "PVP 自检",
     "desc": "全量测试 PVP 伤害计算、属性克制倍率与精灵/技能数据库完整性"},
]
SCREENSHOT_DIR = PROJECT_ROOT / "data" / "screenshots"
