# 洛克王国 PVP 助手 (lkwgai_pvp_assistant)

洛克王国自动化辅助工具。当前核心功能为 **自动丢球助手**（interception 内核级键鼠模拟 + 拟人化随机延迟），并配有**大前端控制台**：丢球助手 / 视觉调试台 / 工具箱 / 配置中心四个页面 + 底部实时任务栏。

> ⚠️ 运行环境：请使用 **Anaconda base 环境**（`D:\anaconda\python.exe`，依赖已齐全）。
> 项目自带的 `.venv` 已废弃（opencv 与 numpy 版本冲突）。

## 启动方式

```bash
# 用 Anaconda 环境运行（推荐）
D:\anaconda\python.exe main.py            # 大前端控制台（1150×780）

# 纯快捷键模式（无界面，ESC 退出）
D:\anaconda\python.exe main.py --throw
```

## 大前端控制台

左侧导航四个页面，底部任务栏实时显示正在运行的任务（模式丢球数 / 工具 PID），
「日志」按钮展开全局日志抽屉，「全部停止」一键停止所有模式。

### 🎯 丢球助手页

| 模式 | 快捷键 | 说明 |
|------|--------|------|
| 普通丢球 | `F4` | 持续蓄力丢球（默认蓄力 0.5~0.8s 随机） |
| 轰炸机模式 | `F9` | 双击空格起飞，悬浮保持高度 + 高频丢球轰炸 |
| 自动技能 | `F10` | 交替按 `3` 和 `X`（默认间隔 1.0~2.0s 随机） |
| 框选截图 | `F8` | 全屏框选截图 → 自动打开模板裁剪工具 |

- 8 个延迟滑杆实时生效（运行中可调），自动持久化到 `data/config/throw_ball_config.json`
- 快捷键全局生效，与界面按钮等效可混用
- 仅当「洛克王国：世界」窗口在前台时执行，切出自动暂停并记录日志

### 👁 视觉调试台页

- **截图预览 / 截图并识别**：PrintWindow+BitBlt 窗口截图，跑完整识别管线（战斗检测/头像/属性/精力/伤害）
- **显示 ROI 框**：叠加显示识别区域（与 `roi_config.json` 同源）
- **保存截图**：存到 `data/screenshots/`，供裁剪工具和演示脚本使用
- 识别依赖模板：模板为空时会明确提示，请先用工具箱「模板裁剪工具」制作模板

### 🧰 工具箱页

一键启动独立工具（GUI 工具打开自己的窗口，CLI 工具输出回流日志抽屉）：

- **模板裁剪工具**：自动截一张游戏画面并打开裁剪器，框选保存识别模板
- **截图环境诊断**：检查窗口截图能力
- **视觉管线演示 / ROI 切片导出**：对最近一张截图跑识别 / 批量切 ROI
- **鼠标连点器**：F6 取坐标 / F7 开关 / F10 急停（全局热键）

### ⚙️ 配置中心页

- 查看/编辑 `settings.yaml`、`roi_config.json`、`throw_ball_config.json`
- 保存前自动校验格式（YAML/JSON），丢球配置保存后热应用到运行中的工具

## 环境要求

- Windows + [Interception 驱动](https://github.com/oblitum/Interception)（键鼠内核级模拟必需）
- 依赖（Anaconda base 已具备）：`pywebview`、`keyboard`、`interception-python`、`opencv-python`、`numpy`、`pywin32`、`PyYAML`

## 目录结构

```
lkwgai_pvp_assistant/
├── main.py                    # 启动入口（大前端 / 快捷键模式）
├── auto_throw_ball.py         # 自动丢球核心逻辑（三种模式，延迟可调）
├── src/
│   ├── gui/
│   │   ├── bridge.py          # AppBridge：丢球/视觉/工具/配置/任务栏 桥接层
│   │   └── web/               # 前端（index.html + assets/app.css + app.js）
│   ├── capture/               # 窗口截图（PrintWindow/BitBlt）
│   ├── perception/            # 模板匹配、数字/头像/属性识别、战斗检测
│   ├── ocr/                   # 识别数据结构（ROI / RecognitionResult）
│   ├── analysis/              # 单帧战斗状态快照
│   ├── driver/                # 键鼠驱动封装
│   └── states/                # FSM 状态机（未接线，后续功能）
├── data/
│   ├── config/                # settings.yaml / roi_config.json / throw_ball_config.json
│   ├── vision/                # 识别模板（digits/elements/avatars/battle，裁剪工具生成）
│   └── screenshots/           # 调试台保存的截图
├── tools/                     # 独立小工具（裁剪/连点/诊断/演示）
└── tests/
```
