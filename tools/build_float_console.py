# -*- coding: utf-8 -*-
"""
生成合并版悬浮窗 float_console.html

把 挂机悬浮窗(widget.html) 和 PVP实时推演悬浮窗(pvp_float_overlay.html)
合并为一个双标签悬浮窗: 🎯 挂机 | ⚔️ PVP,含 PVP 识别引擎开关。

- PVP 内容样式全部 scoped 在 .pv-root 下,与挂机样式零冲突
- 挂机/PVP 各自的 JS 标识符冲突处已改名(pvGetPetAvatar 等)
- 重复生成安全(每次从两个源文件重新合成)
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "gui" / "web"
OUT = WEB / "float_console.html"


def extract(html: str, start: str, end: str) -> str:
    i = html.index(start)
    j = html.index(end, i)
    return html[i + len(start):j]


def main() -> None:
    widget = (WEB / "widget.html").read_text(encoding="utf-8")
    overlay = (WEB / "pvp_float_overlay.html").read_text(encoding="utf-8")

    # ================= 1. PVP CSS: 抽取并 scoped 到 .pv-root =================
    css = extract(overlay, "<style>", "</style>")
    drop_tokens = ("*", ":root", "html", "body", ".card", ".head", ".title",
                   ".fold-btn", ".badge")
    kept_rules: list[str] = []

    # 先摘出 @keyframes(嵌套大括号,单独保留)
    kf_spans = []
    for m in re.finditer(r"@keyframes\s+[\w-]+\s*\{", css):
        depth, j = 1, m.end()
        while depth and j < len(css):
            depth += (css[j] == "{") or -(css[j] == "}")
            j += 1
        kf_spans.append((m.start(), j))

    pieces, cursor = [], 0
    for a, b in kf_spans:
        pieces.append(css[cursor:a])
        pieces.append(css[a:b])  # keyframes 原样保留
        cursor = b
    pieces.append(css[cursor:])
    flat = "".join(pieces)

    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", flat):
        sel, body = m.group(1).strip(), m.group(2)
        parts = [x.strip() for x in sel.split(",")]
        if any(part == "*" or part in drop_tokens for part in parts):
            continue
        sel = sel.replace(".dot", ".pv-dot")  # 状态点改名避免与挂机头部冲突
        scoped = ", ".join(".pv-root " + part.strip() for part in sel.split(","))
        kept_rules.append(f"{scoped} {{{body}}}")
    pv_css = "\n".join(kept_rules)

    # ================= 2. PVP JS: 抽取并去壳 =================
    js = extract(overlay, "<script>", "</script>")
    # 去掉壳层常量: 与挂机脚本的 H_EXPANDED/H_FOLDED 跨块重复声明
    # 会让第二个 script 块整体抛异常报废(标签/推送全挂)
    js = js.replace("const PVP_W = 360, H_EXPANDED = 540, H_FOLDED = 42;", "")
    js = js[js.index("const ATTR_MAP"):]                    # 从属性映射开始
    # 截到 updatePVPData 块结尾 —— updatePVPData/onStarfallSelect 必须保留
    # (合并版悬浮窗全靠 updatePVPData 渲染 500ms 推送; 曾按"// 初始尺寸校准"
    # 锚点截断导致 updatePVPData 被截丢, 悬浮窗 PVP tab 永远停在"等待进入对战")
    # updatePVPData 是 js 中最后一个函数, 尾部特征: 星陨下拉监听器收尾两行
    tail_anchor = ("newSelect.addEventListener('blur', () => { newSelect._open = false; });\n"
                   "    }\n}")
    i = js.find(tail_anchor)
    if i != -1:
        js = js[:i + len(tail_anchor)]
    # 只剔除壳层三件套(toggleFold/syncPvpSize/waitInit): 合并版尺寸校准由外壳 syncSize 接管
    a = js.find("async function toggleFold")
    b = js.find("// ===== AI 陪玩弹幕条")
    if a != -1 and b != -1 and b > a:
        js = js[:a] + js[b:]
    for must in ("function updatePVPData", "function pushAiComment"):
        if must not in js:
            raise SystemExit(f"build_float_console: 剔除壳层后缺失 {must!r}")
    # 必要函数自检: 缺了说明 overlay 结构又变了, 立刻报错而不是产出残废文件
    for must in ("function updatePVPData", "function onStarfallSelect"):
        if must not in js:
            raise SystemExit(f"build_float_console: 产物缺失关键函数 {must!r}, overlay 源结构已变, 请检查截断锚点")
    js = js.replace("statusDot.className = 'dot off'", "statusDot.className = 'pv-dot off'")
    js = js.replace("statusDot.className = 'dot'", "statusDot.className = 'pv-dot'")
    js = js.replace("getPetAvatar", "pvGetPetAvatar")
    # 内容更新后的窗口尺寸校准改走外壳 syncSize
    js = js.replace("setTimeout(syncPvpSize, 50)", "setTimeout(syncSize, 50)")

    # ================= 3. 组装合并页 =================
    widget_body_inner = extract(widget, '<div class="body" id="wBody">', "</div>\n</div>")
    widget_js = extract(widget, "<script>", "</script>")

    pv_root = """
        <div id="pvRoot" style="display:none" class="pv-root">
            <div class="pv-status-row">
                <div class="pv-dot off" id="statusDot"></div>
                <span style="font-size:11px;color:var(--dim);flex:1;">PVP 实时推演</span>
                <div class="speed-badge" id="speedBadge">--</div>
            </div>
            <div class="pv-engine-row">
                <button class="pv-engine-btn" id="pvEngineBtn" onclick="pvEngineToggle()">▶ 启动识别</button>
                <span style="font-size:10px;color:#555c6e;" id="pvEngineHint">需先在主控台 PVP 页确认配置</span>
            </div>
            <div id="pvpBody">
                <div class="empty-state">
                    <div style="font-size: 24px; margin-bottom: 8px;">⚔️</div>
                    <div>等待进入 PVP 对战画面…</div>
                    <div style="font-size: 10px; color: var(--dim); margin-top: 4px;">点上方「启动识别」开始监视</div>
                </div>
            </div>
            <div class="ai-chat" id="aiChat">
                <div class="ai-empty">💬 AI 伙伴待命中…</div>
            </div>
        </div>
"""

    tab_css = """
        /* ===== 合并版: 标签页 + PVP 引擎开关 ===== */
        .tabs { display: flex; gap: 4px; margin-left: 2px; }
        .tab-btn {
            border: 1px solid rgba(255,255,255,0.10); background: transparent;
            color: #8b93a7; font-size: 10px; font-family: inherit;
            padding: 3px 9px; border-radius: 999px; cursor: pointer;
            transition: all 0.15s ease;
        }
        .tab-btn.active {
            color: #fff; background: linear-gradient(135deg, #6366f1, #22d3ee);
            border-color: transparent; font-weight: 700;
        }
        .drag-underlay {
            position: absolute; inset: 0; z-index: 0;
        }
        .head { position: relative; }
        .head .tabs, .head .fold-btn, .head .title, .head .dot {
            position: relative; z-index: 1;
        }
        .pv-status-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
        .pv-dot {
            width: 9px; height: 9px; border-radius: 50%;
            background: #4ade80; box-shadow: 0 0 8px #4ade80;
        }
        .pv-dot.off { background: #555c6e; box-shadow: none; }
        .pv-engine-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
        .pv-engine-btn {
            border: none; cursor: pointer; border-radius: 8px;
            font-size: 11px; font-weight: 700; font-family: inherit;
            padding: 5px 12px; color: #fff;
            background: linear-gradient(135deg, #6366f1, #4f46e5);
        }
        .pv-engine-btn.on { background: linear-gradient(135deg, #ef4444, #b91c1c); }
"""

    head_tabs = """
        <div class="drag-underlay pywebview-drag-region"></div>
        <div class="tabs">
            <button class="tab-btn active" id="tabAfk" onclick="switchTab('afk')">🎯 挂机</button>
            <button class="tab-btn" id="tabPvp" onclick="switchTab('pvp')">⚔️ PVP</button>
        </div>
"""

    # 头部插入标签页(fold 按钮前)
    widget = widget.replace('<button class="fold-btn"',
                            head_tabs + '        <button class="fold-btn"', 1)
    # 样式追加
    widget = widget.replace("</style>", tab_css + pv_css + "\n</style>", 1)
    # PVP 标签页内容(在 wBody 结束后、card 结束前插入)
    widget = widget.replace('</div>\n</div>\n<script>',
                            '</div>\n' + pv_root + '</div>\n<script>', 1)
    # JS: 挂机脚本 + PVP 脚本拼接
    widget = widget.replace("</script>\n</body>",
                            "</script>\n<script>\n" + js + "\n</script>\n</body>", 1)
    widget = widget.replace("<title>状态悬浮窗</title>", "<title>悬浮控制台</title>")

    # ================= 4. 外壳 JS: 标签切换 + PVP 引擎开关 =================
    shell_js = """
    // ===== 合并版: 标签切换 =====
    let activeTab = 'afk';
    function switchTab(tab) {
        activeTab = tab;
        $('wBody').style.display = tab === 'afk' ? '' : 'none';
        $('pvRoot').style.display = tab === 'pvp' ? '' : 'none';
        $('tabAfk').classList.toggle('active', tab === 'afk');
        $('tabPvp').classList.toggle('active', tab === 'pvp');
        requestAnimationFrame(() => setTimeout(syncSize, 30));
    }

    // ===== PVP 识别引擎开关(悬浮窗直达) =====
    let pvEngineOn = false;
    async function pvEngineToggle() {
        try {
            if (pvEngineOn) await pywebview.api.pvp_engine_stop();
            else await pywebview.api.pvp_engine_start();
        } catch (e) {}
        refreshPvEngine();
    }
    async function refreshPvEngine() {
        if (!window.pywebview || !pywebview.api.pvp_engine_status) return;
        try {
            const s = await pywebview.api.pvp_engine_status();
            pvEngineOn = !!s.running;
            const btn = $('pvEngineBtn');
            if (btn) {
                btn.textContent = pvEngineOn ? '■ 停止识别' : '▶ 启动识别';
                btn.classList.toggle('on', pvEngineOn);
            }
        } catch (e) {}
    }
    setInterval(refreshPvEngine, 2000);

    // ===== 自研拖拽: 标题条按下拖动,不依赖 pywebview 拖拽区/窗口焦点 =====
    (function initDrag() {
        let dragging = false, lx = 0, ly = 0, px = 0, py = 0, raf = 0;
        function bind() {
            const el = document.querySelector('.drag-underlay');
            if (!el) { setTimeout(bind, 300); return; }
            el.addEventListener('mousedown', (e) => {
                if (e.button !== 0) return;
                dragging = true;
                lx = e.screenX; ly = e.screenY; px = py = 0;
                e.preventDefault();
            });
            window.addEventListener('mousemove', (e) => {
                if (!dragging) return;
                px += e.screenX - lx; py += e.screenY - ly;
                lx = e.screenX; ly = e.screenY;
                if (!raf) raf = requestAnimationFrame(flush);
            });
            window.addEventListener('mouseup', () => {
                if (dragging) { flush(); dragging = false; }
            });
        }
        function flush() {
            raf = 0;
            if ((px || py) && window.pywebview && pywebview.api.move_window_by) {
                pywebview.api.move_window_by(Math.round(px), Math.round(py));
                px = py = 0;
            }
        }
        bind();
    })();
"""
    widget = widget.replace("</script>\n</body>",
                            shell_js + "</script>\n</body>", 1)

    # 深色底: 用 !important 插在样式表最前(级联必赢),不做脆弱的正则改写
    widget = widget.replace("<style>",
                            "<style>\n    html, body { background: #0a0e1a !important; }", 1)

    # 产物自检: 关键 JS 合约缺失 = 生成残废, 立刻失败(勿静默写出)
    for must in ("function updatePVPData", "function onStarfallSelect",
                 "function switchTab", "pvEngineToggle"):
        if must not in widget:
            raise SystemExit(f"build_float_console: 产物缺失 {must!r}")
    if "document.getElementById('pvpBody').style.display" in widget:
        raise SystemExit("build_float_console: PVP 版 toggleFold 残留(壳层剔除失效)")

    OUT.write_text(widget, encoding="utf-8")
    print(f"已生成 {OUT} ({len(widget)} 字符), 自检通过")


if __name__ == "__main__":
    main()
