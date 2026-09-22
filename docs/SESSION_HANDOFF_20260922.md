# 会话交接 · 2026-09-22（接手前必读）

## 项目一句话
洛克王国 PVP/挂机助手：pywebview(WebView2) + Python + Interception 内核级键鼠。
源码运行 `python main.py`；分发打包 `python tools/build_hardened.py`（六阶段：密钥→Cython→数据加密→冒烟→PyInstaller→11项检查）。
**日常构建一律用 build_hardened.py，不要用 build_main_app.py（无加固）**。

## 关键路径
- 主前端: `src/gui/web/`（index.html + assets/app.js/theme.js/pvp.js/history.js）
- **视觉工坊已抽离**: `src/gui/studio/`（roi_studio.html/js/css，用户要求独立不再随主前端改；资源引用 ../web/assets；bridge.STUDIO_DIR + app_entry 重定向 + build_main_app --add-data 三处已接）
- 悬浮窗 `float_console.html` 是**生成产物**：由 `tools/build_float_console.py` 从 widget.html + pvp_float_overlay.html 拼接。**改悬浮窗必须改 overlay 源文件后重跑生成器**，产物自检会报错缺函数/声明
- PVP 管线: `src/pvp/pvp_pipeline.py`（500ms 截图→OCR→推演→推悬浮窗）
- 本地 HTTP 桥: `src/gui/local_api.py`（127.0.0.1:17365，7+2 端点）
- MCP: `tools/pvp_mcp_server.py`（手写 stdio JSON-RPC，零依赖，7 工具）
- AI 陪玩: `src/gui/ai_companion.py`（3 人设 salty/tsundere/gentle，OpenAI 兼容 API，弹幕推悬浮窗）
- 回合日志: `src/pvp/round_logger.py`（data/rounds/<日期>/*.jsonl，自动写战报）
- 卡密: `src/gui/auth.py` + `auth_core.pyd`(Cython) + `server/worker.js`(CF Workers)
- 加密数据: `src/pvp/data/*.bin`（7个，seadata.py 解密；开发明文用 `tools/seal_assets.py --unseal --seed <keys.json 的 data_seed>`）

## 最近修的 bug（都已推送，全部验证过）
1. `_pvp_float_visible` 从未置 True → 悬浮窗不推送。三条显示路径(F2/PVP按钮/自动弹出)已同步
2. 生成器两个截断 bug：`updatePVPData` 整函数被截丢；`let starfallMode/_lastStarfallTable/_lastEnemyHp/_lastPayload` 声明区(在 ATTR_MAP 之前)被截丢。**生成器截取起点现在是 `let starfallMode = 'auto';`，产物自检含声明+函数断言，缺了直接报错**
3. in_battle 判定改为**左下角聚能按钮模板匹配**（聚能图标.png + ROI 在 PVP标准模板.json；阈值0.72；只搜左下1/4）。非战斗帧的精灵名/技能**不采信**（用户明确要求：不是清空，是压根不识别）——根治地图/菜单文字被当精灵名
4. 启动"卡死"= 残留进程/WebView2 占锁。main.py 已加看门狗（20s 未 shown → boot_watchdog.log + 弹窗）
5. 视觉工坊 404 = 路径错一级；工坊保存同步键名 rx/ry→left/top/width/height 已修

## 用户环境
- Python: `D:/anaconda/python.exe`（用这个跑，别用系统 python）
- 编译器: MSVC 在 `D:\vsstudio`（vcvars64）
- Windows 11，1920x1245 游戏窗口
- GitHub: jxylisty/auto-rocoassit-helper（已推送至 1ec981c）
- CF Worker: auth.my123.bond（主）+ lucky-cell-cd0b...workers.dev（备用，DNS 国内会 11s 失败）
- 密钥: `build/_hardened/keys.json`（**绝不入库**，.gitignore 已盖）

## 游戏规则（用户口述，已进 pvp_rules 知识包 battle_structure）
6 宠/4 心制（死一只扣一心，部分特性影响）/聚能=变化类操作+5 能量不攻击/
愿力冲击=2 能耗 80 威力第 6 技能（属性随血脉）/自由换宠任意存活精灵/每回合只有出招|聚能|换宠三种操作

## AI 变强的路线共识（已与用户讨论定案）
**记忆系统而非 RL**（无可模拟环境、reward 脏、伤害已有解析解）：
1. ✅ 回合日志自动落盘（已完成）
2. ✅ 敌方手牌追踪 + 心数估算（snapshot.hands）+ 能量线推演（snapshot.energy_plan）
3. ⬜ 出招预测统计（回合日志攒够后：敌方精灵×能量/血量区间→出招分布）
4. ⬜ 2-3 回合 minimax 推演（确定性结算+评分函数：心数差×血量差×能量差）
5. ⬜ 校准回路（用实际掉血反向解敌方 IV/性格）

## 待办 / 用户提过还没做的
- **状态/印记识别**（燃烧/冻结/中毒/印记系统）：用户要自己框模板，**等他框完再做**（ROI 留口：pvp状态.json 已有"状态/我方状态栏位"）
- 敌方实际出招识别（战斗日志区闪现技能名）：需要新 ROI，等用户框
- PVP数据采集器（tools/build_collector.py）打包如需分发，套 build_hardened 流程

## 重要教训（详见 docs/AI_EDITING_LESSONS.md）
- bridge.py 双层结构：Api 转发层 + AppBridge 实现，**新接口两处都要加**（前端 61 个调用已有核对脚本模式）
- float_console.html 是生成物——**绝不当源文件改**
- 中文路径 cv2.imread 会失败，用 `cv2.imdecode(np.fromfile(...))`
- 试用版 PyArmor：无 --mix-str、文件>32KB 混淆失败、授权有冷却
- pip install 时注意 `WARNING: Ignoring invalid distribution ~umpy`（无害但说明 anaconda 有残缺包）

## 当前 git 状态
最新提交 1ec981c（widget_state 快照），工作区干净，已推送 origin/main。
