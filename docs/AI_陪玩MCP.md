# AI 陪玩 MCP 工具 · 使用说明

让 AI（ZCode / Claude Desktop / Cline 等支持 MCP 的客户端）实时读取你的 PVP 对局数据、理解游戏规则、给出战术建议，并在悬浮窗上以弹幕气泡的形式"陪你打"。

```
AI 客户端 ──MCP(stdio)── tools/pvp_mcp_server.py ──HTTP── 主程序(127.0.0.1:17365) ── 悬浮窗
```

## 一、接入 MCP 客户端

前提：主程序（`python main.py`）已启动，且悬浮窗上点过「启动识别」。

### ZCode（本机）
在 MCP 配置里加：
```json
{
  "mcpServers": {
    "lkw-pvp": {
      "command": "D:/anaconda/python.exe",
      "args": ["D:/洛克王国ai/lkwgai_pvp_assistant/tools/pvp_mcp_server.py"]
    }
  }
}
```

### Claude Desktop / 通用客户端
同结构，放各自配置文件（`claude_desktop_config.json` 等）。

## 二、MCP 工具清单（5 个）

| 工具 | 用途 |
|---|---|
| `pvp_snapshot` | 当前对局实时快照：双方精灵/血量/能量 + 伤害推演(斩杀标记) + 敌方威胁 + 先手结论 + 愿力推演 |
| `pvp_rules` | 完整规则知识包：60级/IV规则/性格修正/18系克制表/伤害公式/先手判定 |
| `pvp_analyze_matchup` | 指定双方精灵 seq 的完整推演（含 IV/性格配置） |
| `pvp_search` | 精灵/技能模糊搜索（查 seq 用） |
| `pvp_history` | 历史战报（分析对手风格） |

## 三、AI 陪玩弹幕

悬浮窗 PVP 标签底部有一条 **AI 弹幕气泡位**（💬），AI 伙伴会在关键事件时冒出一条评论：
- 🏁 进入对战 / 对局结束
- 🔥 有斩杀机会（"收了收了！"）
- 💚 被打死威胁 / 血量骤降（先安慰再建议）
- 🔄 双方换宠

### 启用配置
编辑 `data/config/ai_companion.json`（首次可自建）：
```json
{
  "enabled": true,
  "base_url": "https://api.deepseek.com/v1",
  "api_key": "sk-你的key",
  "model": "deepseek-chat",
  "persona": "tsundere",
  "interval_min": 20
}
```
- `base_url` 填任意 OpenAI 兼容服务（deepseek / 智谱 / 本地豆包桥 `http://127.0.0.1:7868/v1` 等）
- `persona` 内置三选一：`salty`（毒舌主播·有节目效果）/ `tsundere`（傲娇伙伴·嘴硬心软）/ `gentle`（温柔鼓励·治愈系）
- `custom_persona` 填自定义人设 prompt 则覆盖内置
- `enabled: false` 或不填 `api_key` = 完全关闭，零开销

### 频控
- 两条弹幕最少间隔 `interval_min` 秒（默认 20）
- 同类事件不重复触发
- API 超时/失败静默跳过，绝不影响游戏和识别引擎

## 四、典型用法示例

对 AI 说：
> 「用 pvp_snapshot 看一下当前局势，然后结合 pvp_rules 告诉我这回合该出哪个技能」

> 「对面换了一只宠，用 pvp_search 查一下它的属性，再 pvp_analyze_matchup 算算我该打谁」

AI 会先拉快照 → 查规则 → 给出"先手+1 / 克制 2 倍 / 预计伤害 XXX，足以斩杀"这类具体结论。

## 五、故障排查

| 现象 | 原因 |
|---|---|
| `pvp_snapshot` 返回无法连接 | 主程序没启动，或启动时 17365 端口被占 |
| `in_battle: false` 一直不变 | 没点悬浮窗「启动识别」，或游戏不在对战画面 |
| `calc_error: 精灵数据未就绪` | 用户版未激活卡密（数据密钥没下发），激活后自动恢复 |
| 弹幕不出现 | `ai_companion.json` 未启用/无 api_key；或悬浮窗未打开 |
