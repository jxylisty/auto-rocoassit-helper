# PVP 伤害计算引擎（JS 权威版）

自 `C:\Users\zzx05\Documents\HBuilderProjects\luokewangguo`（uni-app 数据收集工程）整体搬入，
保持原相对目录结构，子树内自包含、零外部依赖、无构建工具。

## 运行回归测试

```bash
cd src/pvp/engine
node scripts/run-pvp-breakpoint-tests.mjs
```

84 个纯 Node 用例（克制表口径 / 面板截断顺序 / 连击 / 伤害下限 / 星陨公式边界 /
动态威力 22 个分档边界 / S4 同速随机），当前 **84 通过 / 0 失败**。

`package.json` 的 `"type": "module"` 是必需的：本机 Node v20 下 `.js` 文件
必须由它声明才会按 ESM 解析（源工程同样如此）。

## 文件职责

| 文件 | 内容 |
| --- | --- |
| `utils/pvpDamageEngine.js` | 引擎主体：主伤害 `calculateDamageFull`、星陨引爆 `calculateStarfallDamage` / `starfallPowerForStacks`（层数²+24×层数−24，幻系拦阻/无本系/单次结算）、动态威力分档 `getDynamicPowerRule` / `resolveStatDiffTierPower`、面板 `calculatePanelValue` / `calculateAllPanels`、先手判定 `canActBeforeEnemy`（含 S4 同速随机）、技能解析 `normalizeBattleSkill` |
| `data/config/typeChart.js` | 18 系克制表（单克 2 / 双克 3 / 抗 0.5 / 双抗 0.25 连乘口径） |
| `config/pvpRuleConfig.js` | 全局常量（60 级 / 5 星 / 本系 1.25 / 性格 1.2~0.9 / 伤害常量） |
| `data/skill/dynamicPowerRules.js` | S4 分档规则表（鸣沙陷阱=物防差、闪击=速度差，11 档 60→200），文件头含 BWIKI nrc 站（2026-09-09）与 GitHub 180sans/roco-cal（2026-09-16 拟合）来源注释，下赛季复核从它开始 |
| `utils/buildOpponentFullConfig.js` / `buildSuggestedIvs.js` | 测试用配置构造器 |
| `utils/wishPowerAdvisor.js` | 许愿/威胁伤害分析（`analyzeWishOptions` / `estimateWishDamage`），依赖 `data/pet/pet_detail.js` |
| `data/pet/pet_detail.js` | 宠物详情数据模块（约 412KB，纯数据，随 `wishPowerAdvisor` 一并搬入） |
| `scripts/run-pvp-breakpoint-tests.mjs` | 回归测试入口 |

## 与 Python 侧的关系

`src/pvp/damage_calculator.py` 是本工程早期从同一 JS 引擎移植的 Python 版，
目前**缺**以下机制，需要对齐时以本目录 JS 版为权威参考：

- 星陨引爆（`calculateStarfallDamage` / `starfallPowerForStacks`）
- 动态威力的 S4 分档表解析（`resolveStatDiffTierPower`；Python 侧仅有技能类型识别，未接分档表）
- 先手判定无 S4 同速随机标注（Python 侧只返回 `tie` 文案）

克制表两处口径一致（`data/config/typeChart.js` ↔ `src/pvp/data/type_chart.json`）。

## 未搬入的部分（仍在源工程）

- `pages/pvp-breakpoint.vue` — uni-app 交互层，桌面端照抄逻辑不照抄代码
  （面板差→查档→自动填威力的 `dynamicPowerResolution` computed + watcher、
  主伤+星陨附加分开展示、分档迷你表、"S4 环境速选"），由前端改版时参考。
- `crawler_official_api/update_data.py`（官方 API 管线）与
  `tools/map-meta-pets.mjs` + `scripts/.meta-test/`（S4 环境名单→seq 映射→
  合并 metaTargetPets.json 流程）— 数据维护管线，下赛季复核时再决定是否引入。
