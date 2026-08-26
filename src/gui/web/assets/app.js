// ========================================
// 洛克王国 PVP 助手 · 大前端控制台逻辑 v2.1
// ========================================

const $ = (id) => document.getElementById(id);

// ---------- 全局状态 ----------
const CONFIG_KEYS = [
    'normal_min', 'normal_max',
    'bomber_charge_min', 'bomber_charge_max',
    'bomber_hover_min', 'bomber_hover_max',
    'skill_min', 'skill_max'
];
const SLIDERS_ACTIVE = new Set();   // 拖动中的滑杆,轮询不回写
const MODE_MAP = {
    normal: { btn: 'btnNormal', card: 'cardNormal', api: 'toggle_normal', running: 'normal_running', name: '普通丢球' },
    bomber: { btn: 'btnBomber', card: 'cardBomber', api: 'toggle_bomber', running: 'bomber_running', name: '轰炸机模式' },
    skill:  { btn: 'btnSkill',  card: 'cardSkill',  api: 'toggle_skill',  running: 'skill_running',  name: '自动技能' }
};
const ROI_COLORS = {
    enemy_name: '#f87171',
    enemy_elements: '#fbbf24',
    enemy_hp: '#4ade80',
    battle_left_indicator: '#a78bfa',
    battle_right_indicator: '#f472b6'
};
const ROI_LABELS = {
    enemy_name: '精灵名称',
    enemy_elements: '属性',
    enemy_hp: '敌方血量',
    battle_left_indicator: '战斗·左',
    battle_right_indicator: '战斗·右'
};

let currentRoi = null;      // 最近一次识别返回的 ROI 配置
let currentFile = null;     // 配置中心当前文件
let toolsCache = [];        // 工具列表缓存
let refreshing = false;

// ========================================
// Toast 通知系统
// ========================================

const TOAST_ICONS = {
    success: '✓',
    error: '✗',
    warning: '⚠',
    info: 'ℹ'
};

const TOAST_DURATION = {
    success: 3000,
    error: 5000,
    warning: 4000,
    info: 3000
};

function showToast(message, level = 'info', duration) {
    const container = $('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${level}`;

    const icon = TOAST_ICONS[level] || TOAST_ICONS.info;
    const dur = duration || TOAST_DURATION[level] || 3000;

    toast.innerHTML = `
        <span class="toast-icon">${icon}</span>
        <span class="toast-msg">${String(message).replace(/&/g, '&amp;').replace(/</g, '&lt;')}</span>
        <button class="toast-close" onclick="dismissToast(this.parentElement)">×</button>
    `;

    container.appendChild(toast);

    // 自动消除
    const timer = setTimeout(() => dismissToast(toast), dur);
    toast._timer = timer;

    // 限制最多 5 个 toast
    while (container.children.length > 5) {
        dismissToast(container.firstElementChild);
    }
}

function dismissToast(toast) {
    if (!toast || toast._dismissing) return;
    toast._dismissing = true;
    clearTimeout(toast._timer);
    toast.classList.add('removing');
    setTimeout(() => {
        if (toast.parentElement) toast.parentElement.removeChild(toast);
    }, 300);
}

// 暴露到全局
window.showToast = showToast;

// ========================================
// 日志
// ========================================

function addLog(message, level = 'info') {
    const body = $('logContent');
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    const now = new Date();
    const t = [now.getHours(), now.getMinutes(), now.getSeconds()]
        .map(n => String(n).padStart(2, '0')).join(':');
    const safe = String(message).replace(/&/g, '&amp;').replace(/</g, '&lt;');
    entry.innerHTML = `<span class="log-time">${t}</span><span class="log-msg ${level}">${safe}</span>`;
    body.appendChild(entry);
    body.scrollTop = body.scrollHeight;
    while (body.children.length > 300) body.removeChild(body.firstChild);

    // 任务栏最后一条日志
    const last = $('tbLastLog');
    last.textContent = `[${t}] ${safe}`;
    last.title = `[${t}] ${message}`;

    // 重要事件同时弹出 toast
    if (level === 'success' || level === 'error') {
        showToast(message, level);
    }
}
window.addLog = addLog;

function clearLog() { $('logContent').innerHTML = ''; $('tbLastLog').textContent = ''; }

function copyLogs() {
    const entries = [...$('logContent').children].map(el => el.innerText.replace(/\s+/g, ' ').trim());
    const text = entries.join('\n') || '(空)';
    const done = () => addLog(`已复制 ${entries.length} 条日志到剪贴板`, 'success');
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
    } else {
        fallbackCopy(text, done);
    }
}

function fallbackCopy(text, done) {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); done && done(); }
    catch (e) { addLog('复制失败,请手动选中文本复制', 'error'); }
    document.body.removeChild(ta);
}

function toggleLogDrawer() {
    const d = $('logDrawer');
    d.classList.toggle('open');
    if (d.classList.contains('open')) {
        $('logContent').scrollTop = $('logContent').scrollHeight;
    }
}

// ========================================
// 快捷键面板
// ========================================

function toggleShortcutPanel() {
    const overlay = $('shortcutOverlay');
    overlay.classList.toggle('show');
}

function closeShortcutPanel(e) {
    if (e && e.target !== $('shortcutOverlay')) return;
    $('shortcutOverlay').classList.remove('show');
}

// 全局键盘事件
document.addEventListener('keydown', (e) => {
    // ? 键打开快捷键面板
    if (e.key === '?' && !e.ctrlKey && !e.altKey && !e.metaKey &&
        document.activeElement === document.body) {
        e.preventDefault();
        toggleShortcutPanel();
    }
    // Escape 关闭面板
    if (e.key === 'Escape') {
        $('shortcutOverlay').classList.remove('show');
    }
});

// ========================================
// 挂机引擎
// ========================================

let engineOn = false;

async function engineToggle() {
    try {
        if (engineOn) {
            await pywebview.api.engine_stop();
            showToast('引擎已停止', 'warning');
        } else {
            const params = {
                catch_hp: Number($('engineCatchHp').value),
                skills: $('engineSkills').value,
                open_ball_key: $('engineOpenKey').value,
                ball_slot_key: $('engineBallKey').value,
                patrol_enabled: $('patrolEnabled').checked,
                patrol_move_key: $('patrolMoveKey').value,
                patrol_turn_mode: $('patrolTurnMode').value,
            };
            const dry = $('engineDry').checked;
            const r = await pywebview.api.engine_start(dry, params);
            if (!r.success) {
                addLog('引擎启动失败: ' + (r.message || ''), 'error');
            } else {
                showToast(dry ? '引擎已启动(模拟模式)' : '引擎已启动', 'success');
            }
        }
        refreshState();
    } catch (e) { addLog('引擎操作异常: ' + e.message, 'error'); }
}

function applyEngineStatus(s) {
    engineOn = !!s.running;
    const btn = $('btnEngineStart');
    btn.textContent = engineOn ? '■ 停止引擎' : '▶ 启动引擎';
    btn.classList.toggle('btn-danger', engineOn);
    $('engineDryBadge').style.display = s.dry_run ? '' : 'none';
    $('engineDry').disabled = engineOn;
    const stateNames = { stopped: '停止', waiting: '等战斗', fighting: '战斗中', throwing: '丢球', paused: '暂停' };
    $('engState').textContent = stateNames[s.state] || s.state;
    $('engDetail').textContent = s.detail || '—';
    $('engBattles').textContent = s.battles_done ?? 0;
    $('engBalls').textContent = s.catch_attempts ?? 0;
    $('engCatches').textContent = s.catches ?? 0;
}

// 捕获血线滑杆
document.addEventListener('DOMContentLoaded', () => {
    const el = $('engineCatchHp');
    const paint = () => {
        const pct = ((el.value - el.min) / (el.max - el.min)) * 100;
        el.style.setProperty('--fill', pct + '%');
        $('engineCatchHpVal').textContent = el.value + '%';
    };
    el.addEventListener('input', paint);
    paint();
});

// ========================================
// 页面导航
// ========================================

function switchPage(name) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const page = $(`page-${name}`);
    const nav = document.querySelector(`.nav-item[data-page="${name}"]`);

    if (page) page.classList.add('active');
    if (nav) nav.classList.add('active');
}

// ========================================
// 丢球助手
// ========================================

function paintSlider(el) {
    const pct = ((el.value - el.min) / (el.max - el.min)) * 100;
    el.style.setProperty('--fill', pct + '%');
    const valEl = $(el.id + '_val');
    if (valEl) valEl.textContent = Number(el.value).toFixed(2) + 's';
}

function collectConfig() {
    const cfg = {};
    CONFIG_KEYS.forEach(k => { cfg[k] = Number($(k).value); });
    return cfg;
}

async function pushConfig() {
    try {
        const r = await pywebview.api.update_config(collectConfig());
        if (!r.success) addLog('延迟参数保存失败: ' + (r.message || ''), 'error');
    } catch (e) { addLog('延迟参数保存异常: ' + e.message, 'error'); }
}

const PAIR_MAP = {
    normal_min: 'normal_max', normal_max: 'normal_min',
    bomber_charge_min: 'bomber_charge_max', bomber_charge_max: 'bomber_charge_min',
    bomber_hover_min: 'bomber_hover_max', bomber_hover_max: 'bomber_hover_min',
    skill_min: 'skill_max', skill_max: 'skill_min'
};

function crossClamp(id) {
    const el = $(id), other = $(PAIR_MAP[id]);
    if (!other) return;
    if (id.endsWith('_min') && Number(el.value) > Number(other.value)) { other.value = el.value; paintSlider(other); }
    if (id.endsWith('_max') && Number(el.value) < Number(other.value)) { other.value = el.value; paintSlider(other); }
}

CONFIG_KEYS.forEach(id => {
    const el = $(id);
    el.addEventListener('input', () => { crossClamp(id); paintSlider(el); });
    el.addEventListener('pointerdown', () => SLIDERS_ACTIVE.add(id));
    el.addEventListener('pointerup', () => SLIDERS_ACTIVE.delete(id));
    el.addEventListener('change', () => pushConfig());
});

async function toggleMode(mode) {
    const m = MODE_MAP[mode];
    try {
        const r = await pywebview.api[m.api]();
        addLog(`${m.name} ${r.running ? '已启动' : '已停止'}`, r.running ? 'success' : 'warning');
        refreshState();
    } catch (e) { addLog('操作异常: ' + e.message, 'error'); }
}

async function stopAll() {
    try {
        await pywebview.api.stop_all();
        showToast('已全部停止', 'warning');
        refreshState();
        refreshTools();
    } catch (e) { addLog('停止异常: ' + e.message, 'error'); }
}

function applyState(s) {
    // 模式卡片
    let runningCount = 0;
    Object.values(MODE_MAP).forEach(m => {
        const on = !!s[m.running];
        if (on) runningCount++;
        $(m.btn).textContent = on ? '停 止' : '启 动';
        $(m.card).classList.toggle('running', on);
    });
    $('btnStopAll').disabled = runningCount === 0;
    $('statModes').textContent = runningCount;

    // 计数
    $('statNormal').textContent = s.normal_count ?? 0;
    $('statBomber').textContent = s.bomber_count ?? 0;
    $('statSkill').textContent = s.skill_count ?? 0;

    // 游戏窗口
    $('gamePill').classList.toggle('active', !!s.game_active);
    $('gamePillText').textContent = s.game_active ? '游戏窗口前台' : '游戏窗口后台';

    // 滑杆回写(不干扰拖动中的)
    if (s.config) {
        CONFIG_KEYS.forEach(k => {
            if (SLIDERS_ACTIVE.has(k)) return;
            const el = $(k);
            if (Number(el.value) !== Number(s.config[k])) el.value = s.config[k];
            paintSlider(el);
        });
    }

    // 任务栏
    const box = $('tbTasks');
    const tasks = s.tasks || [];
    if (!tasks.length) {
        box.innerHTML = '<span class="tb-none">全部空闲</span>';
    } else {
        box.innerHTML = tasks.map(t =>
            `<span class="task-chip"><span class="tdot"></span>${t.name}<small>${t.detail || ''}</small></span>`
        ).join('');
    }
}

// ========================================
// 悬浮窗 / 置顶
// ========================================

let widgetVisible = false;

async function toggleWidget() {
    try {
        const r = await pywebview.api.widget_toggle();
        if (r.success) {
            widgetVisible = r.visible;
            const btn = $('btnWidget');
            btn.classList.toggle('pinned', widgetVisible);
            btn.textContent = widgetVisible ? '📱 已开' : '📱 悬浮窗';
        }
    } catch (e) { addLog('悬浮窗: ' + e, 'error'); }
}

let onTop = false;

async function toggleOnTop() {
    try {
        const r = await pywebview.api.set_on_top(!onTop);
        if (r.success) {
            onTop = !onTop;
            const btn = $('btnPin');
            btn.classList.toggle('pinned', onTop);
            btn.textContent = onTop ? '📌 已置顶' : '📌 置顶';
        }
    } catch (e) { addLog('置顶: ' + e, 'error'); }
}

// ========================================
// ROI 校准模式(截图上拖框 → 改坐标 → 保存 roi_config.json)
// ========================================

let calibMode = false;
let calibTarget = 'enemy_hp';
let calibDirty = false;
let calibDrag = null;  // {x0,y0,x1,y1} 归一化

function calibChipRender() {
    const chips = Object.entries(ROI_LABELS).map(([key, label]) =>
        `<button class="calib-chip ${key === calibTarget ? 'active' : ''}" data-roi="${key}"
                 style="--c:${ROI_COLORS[key] || '#6366f1'}" onclick="calibPick('${key}')">${label}</button>`);
    $('calibChips').innerHTML = chips.join('');
}

function calibPick(key) {
    calibTarget = key;
    calibChipRender();
}

function toggleCalib() {
    calibMode = !calibMode;
    $('btnCalib').classList.toggle('btn-danger', calibMode);
    $('calibBar').style.display = calibMode ? 'flex' : 'none';
    $('btnCalibSave').style.display = calibMode ? '' : 'none';
    const view = $('shotView');
    view.classList.toggle('calib', calibMode);
    if (calibMode) {
        if (!currentRoi) { currentRoi = {}; }
        $('roiToggle').checked = true;
        calibChipRender();
        renderRoiOverlay();
        setVisionStatus('校准模式: 选目标区域 → 截图上拖框');
        if ($('shotView').style.display === 'none') addLog('请先截图再校准', 'warning');
    } else {
        setVisionStatus('校准模式已退出');
    }
}

function calibNormalized(e) {
    const img = $('shotImg');
    const rect = img.getBoundingClientRect();
    return {
        x: Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)),
        y: Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height)),
    };
}

async function calibSave() {
    if (!calibDirty) { setVisionStatus('校准无改动'); return; }
    try {
        const r = await pywebview.api.config_save('roi_config.json',
            JSON.stringify(currentRoi, null, 2));
        if (r.success) {
            calibDirty = false;
            setVisionStatus('校准已保存 ✓');
            showToast('ROI 校准已保存', 'success');
            addLog('ROI 校准已保存到 roi_config.json', 'success');
        } else {
            setVisionStatus('保存失败: ' + r.message);
            addLog('校准保存失败: ' + r.message, 'error');
        }
    } catch (e) { addLog('校准保存异常: ' + e.message, 'error'); }
}

// 拖框事件绑定(校准模式下生效)
document.addEventListener('DOMContentLoaded', () => {
    const view = $('shotView');
    view.addEventListener('pointerdown', (e) => {
        if (!calibMode || e.button !== 0) return;
        const p = calibNormalized(e);
        calibDrag = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
        e.preventDefault();
    });
    view.addEventListener('pointermove', (e) => {
        if (!calibMode || !calibDrag) return;
        const p = calibNormalized(e);
        calibDrag.x1 = p.x; calibDrag.y1 = p.y;
        const layer = $('roiLayer');
        let ghost = document.getElementById('calibGhost');
        if (!ghost) {
            ghost = document.createElement('div');
            ghost.id = 'calibGhost';
            ghost.className = 'roi-box calib-ghost';
            layer.appendChild(ghost);
        }
        const x1 = Math.min(calibDrag.x0, calibDrag.x1), x2 = Math.max(calibDrag.x0, calibDrag.x1);
        const y1 = Math.min(calibDrag.y0, calibDrag.y1), y2 = Math.max(calibDrag.y0, calibDrag.y1);
        ghost.style.cssText = `left:${x1 * 100}%;top:${y1 * 100}%;width:${(x2 - x1) * 100}%;height:${(y2 - y1) * 100}%;border-color:${ROI_COLORS[calibTarget] || '#6366f1'}`;
    });
    view.addEventListener('pointerup', (e) => {
        if (!calibMode || !calibDrag) return;
        const x1 = Math.min(calibDrag.x0, calibDrag.x1), x2 = Math.max(calibDrag.x0, calibDrag.x1);
        const y1 = Math.min(calibDrag.y0, calibDrag.y1), y2 = Math.max(calibDrag.y0, calibDrag.y1);
        calibDrag = null;
        const ghost = document.getElementById('calibGhost');
        if (ghost) ghost.remove();
        if (x2 - x1 < 0.005 || y2 - y1 < 0.005) return;  // 过小忽略
        currentRoi[calibTarget] = {
            left: +x1.toFixed(4), top: +y1.toFixed(4),
            width: +(x2 - x1).toFixed(4), height: +(y2 - y1).toFixed(4),
        };
        calibDirty = true;
        renderRoiOverlay();
        setVisionStatus(`已更新「${ROI_LABELS[calibTarget]}」框,记得点保存校准`);
    });
});

// ========================================
// 实时识别(后端每 1.5s 推送一帧)
// ========================================

let liveRunning = false;

async function toggleLive() {
    try {
        if (liveRunning) {
            await pywebview.api.vision_live_stop();
            setLiveUI(false);
        } else {
            const r = await pywebview.api.vision_live_start();
            if (r.success) setLiveUI(true);
        }
        refreshState();
    } catch (e) { addLog('实时识别操作异常: ' + e.message, 'error'); }
}

function setLiveUI(on) {
    liveRunning = on;
    const btn = $('btnLive');
    btn.textContent = on ? '■ 停止实时' : '▶ 实时识别';
    btn.classList.toggle('btn-danger', on);
    if (!on) setVisionStatus(liveRunning ? '' : '实时识别已停止');
}

// 后端推送入口(evaluate_js 调用)
window.updateLiveResult = function (payload) {
    if (!payload || !liveRunning) return;
    showShot(payload.image, payload.width, payload.height, '实时画面');
    currentRoi = payload.roi || currentRoi;
    renderRoiOverlay();
    renderResults(payload.result);
    const b = payload.result.battle || {};
    const hp = payload.result.enemy_hp;
    setVisionStatus(`实时中 · 战斗:${b.in_battle ? '是' : '否'} · 敌方血量:${hp === null || hp === undefined ? '—' : hp + '%'}`);
};

// ========================================
// 视觉调试台
// ========================================

function setVisionStatus(text) { $('visionStatus').textContent = text; }

function showShot(image, w, h, title) {
    $('shotEmpty').style.display = 'none';
    const view = $('shotView');
    view.style.display = 'inline-block';
    $('shotImg').src = image;
    setVisionStatus(`${title || '游戏窗口'} · ${w}×${h}`);
}

function renderRoiOverlay() {
    const layer = $('roiLayer');
    layer.innerHTML = '';
    if (!$('roiToggle').checked || !currentRoi) return;
    Object.entries(currentRoi).forEach(([name, r]) => {
        const div = document.createElement('div');
        div.className = 'roi-box';
        const color = ROI_COLORS[name] || '#6366f1';
        div.style.cssText =
            `left:${r.left * 100}%;top:${r.top * 100}%;width:${r.width * 100}%;height:${r.height * 100}%;border-color:${color}`;
        div.innerHTML = `<span style="background:${color}">${ROI_LABELS[name] || name}</span>`;
        layer.appendChild(div);
    });
}

async function visionCapture() {
    const btn = $('btnVCap'); btn.disabled = true;
    setVisionStatus('截图中…');
    try {
        const r = await pywebview.api.vision_capture();
        if (r.success) showShot(r.image, r.width, r.height, r.title);
        else setVisionStatus('截图失败');
    } catch (e) { addLog('截图异常: ' + e.message, 'error'); setVisionStatus('截图异常'); }
    finally { btn.disabled = false; }
}

function renderResults(result) {
    // 战斗状态
    const b = result.battle || {};
    const badge = $('battleBadge');
    if (!b.configured) {
        badge.className = 'battle-badge idle'; badge.textContent = '未配置模板';
        $('battleNote').textContent = '战斗图标模板为空,请先用工具箱「模板裁剪工具」制作模板';
        $('battleNote').classList.add('show');
    } else if (b.in_battle) {
        badge.className = 'battle-badge yes'; badge.textContent = '● 战斗中';
        $('battleNote').classList.remove('show');
    } else {
        badge.className = 'battle-badge no'; badge.textContent = '○ 非战斗';
        $('battleNote').classList.remove('show');
    }
    $('scoreL').style.width = Math.min(100, (b.left_score || 0) * 100) + '%';
    $('scoreR').style.width = Math.min(100, (b.right_score || 0) * 100) + '%';
    $('scoreLv').textContent = (b.left_score || 0).toFixed(2);
    $('scoreRv').textContent = (b.right_score || 0).toFixed(2);

    // 识别值
    const nm = result.enemy_name;
    $('recName').textContent = nm ? nm : '—';
    $('recName').className = nm ? 'ok' : '';
    const elems = result.enemy_elements;
    $('recElements').textContent = Array.isArray(elems) && elems.length ? elems.join(' + ') : '—';
    $('recElements').className = elems && elems.length ? 'ok' : '';
    const hp = result.enemy_hp;
    $('recHp').textContent = hp === null || hp === undefined ? '—' : hp + '%';
    $('recHp').className = hp !== null && hp !== undefined ? 'ok' : '';
    const rawBits = [];
    if (result.raw && result.raw.name_raw) rawBits.push('名:' + result.raw.name_raw.trim());
    if (result.enemy_hp_raw) rawBits.push('血:' + result.enemy_hp_raw);
    $('recRaw').textContent = rawBits.join('  ') || '—';

    // 原始 JSON
    $('rawJson').textContent = JSON.stringify(result, null, 2);
}

async function visionAnalyze() {
    const btn = $('btnVAna'); btn.disabled = true;
    setVisionStatus('截图 + 识别中…');
    try {
        const r = await pywebview.api.vision_analyze();
        if (r.success) {
            showShot(r.image, r.width, r.height, r.title);
            currentRoi = r.roi || null;
            renderRoiOverlay();
            renderResults(r.result);
        } else {
            setVisionStatus('识别失败');
        }
    } catch (e) { addLog('识别异常: ' + e.message, 'error'); setVisionStatus('识别异常'); }
    finally { btn.disabled = false; }
}

async function visionSave() {
    try {
        const r = await pywebview.api.vision_save_shot();
        if (r.success) setVisionStatus(`已保存 ${r.path}`);
    } catch (e) { addLog('保存截图异常: ' + e.message, 'error'); }
}

// ========================================
// 工具箱
// ========================================

function renderTools(tools) {
    toolsCache = tools;
    const grid = $('toolGrid');
    grid.innerHTML = tools.map(t => `
        <div class="tool-card ${t.running ? 'running' : ''}" id="tool-${t.id}">
            <div class="tool-head">
                <div class="tool-icon">${t.gui ? '🖼' : '⌨'}</div>
                <div>
                    <div class="tool-name">${t.name}<span class="tool-tag">${t.gui ? 'GUI' : 'CLI'}</span></div>
                </div>
            </div>
            <div class="tool-desc">${t.desc}</div>
            <div class="tool-foot">
                <button class="tool-btn" onclick="toolToggle('${t.id}')">${t.running ? '停止' : '启动'}</button>
                <span class="tool-pid" id="toolpid-${t.id}"></span>
            </div>
        </div>`).join('');
}

async function refreshTools() {
    try {
        const r = await pywebview.api.tools_list();
        if (r.success) renderTools(r.tools);
    } catch (e) { /* 后端未就绪 */ }
}

async function toolToggle(id) {
    const t = toolsCache.find(x => x.id === id);
    if (!t) return;
    try {
        const r = t.running ? await pywebview.api.tool_stop(id)
                            : await pywebview.api.tool_start(id);
        if (!r.success) addLog(`${t.name}: ${r.message}`, 'warning');
        refreshTools();
        refreshState();
    } catch (e) { addLog('工具操作异常: ' + e.message, 'error'); }
}

// ========================================
// 配置中心
// ========================================

function markConfigActive(name) {
    document.querySelectorAll('.config-item').forEach(el => el.classList.remove('active'));
    const el = document.querySelector(`.config-item[data-name="${name}"]`);
    if (el) el.classList.add('active');
}

function renderConfigList(files) {
    $('configList').innerHTML = files.map(f => `
        <div class="config-item ${f.name === currentFile ? 'active' : ''}" data-name="${f.name}" onclick="openConfig('${f.name}')">
            <div class="ci-name">${f.name}<span class="ci-badge">${f.type.toUpperCase()}</span></div>
            <div class="ci-desc">${f.desc}${f.exists ? '' : '（尚未创建）'}</div>
        </div>`).join('');
}

async function refreshConfigList() {
    try {
        const r = await pywebview.api.config_list();
        if (r.success) renderConfigList(r.files);
    } catch (e) { /* ignore */ }
}

async function openConfig(name) {
    currentFile = name;
    markConfigActive(name);
    $('cfgMsg').textContent = '';
    try {
        const [meta] = (await pywebview.api.config_list()).files.filter(f => f.name === name);
        $('cfgDesc').textContent = meta ? meta.desc : '';
        const r = await pywebview.api.config_read(name);
        $('cfgText').value = r.success ? (r.content || '') : `读取失败: ${r.message}`;
    } catch (e) { $('cfgText').value = '读取异常: ' + e.message; }
}

function setCfgMsg(text, ok) {
    const el = $('cfgMsg');
    el.textContent = text;
    el.className = 'ce-msg ' + (ok ? 'ok' : 'err');
}

async function configSave() {
    if (!currentFile) return;
    try {
        const r = await pywebview.api.config_save(currentFile, $('cfgText').value);
        if (r.success) {
            setCfgMsg(`✓ 已保存 ${new Date().toLocaleTimeString()}`, true);
            refreshConfigList();
        } else {
            setCfgMsg('✗ ' + r.message, false);
        }
    } catch (e) { setCfgMsg('✗ 保存异常: ' + e.message, false); }
}

async function configReload() {
    if (currentFile) { openConfig(currentFile); setCfgMsg('已重新加载', true); }
}

function configFormat() {
    if (!currentFile || !currentFile.endsWith('.json')) {
        setCfgMsg('仅支持 JSON 文件格式化', false); return;
    }
    try {
        const obj = JSON.parse($('cfgText').value || '{}');
        $('cfgText').value = JSON.stringify(obj, null, 2);
        setCfgMsg('✓ 已格式化(尚未保存)', true);
    } catch (e) { setCfgMsg('✗ JSON 解析失败: ' + e.message, false); }
}

// ========================================
// 轮询
// ========================================

async function refreshState() {
    if (refreshing) return;
    refreshing = true;
    try { applyState(await pywebview.api.get_state()); }
    catch (e) { /* 后端未就绪 */ }
    try { applyEngineStatus(await pywebview.api.engine_status()); }
    catch (e) { /* ignore */ }
    finally { refreshing = false; }
}

// ========================================
// 初始化
// ========================================

window.addEventListener('pywebviewready', () => {
    addLog('后端已连接', 'success');
    refreshState();
    refreshTools();
    refreshConfigList().then(() => {
        // 默认打开第一个配置
        const first = document.querySelector('.config-item');
        if (first) openConfig(first.dataset.name);
    });
    setInterval(refreshState, 1000);
    setInterval(refreshTools, 2000);
});

document.addEventListener('DOMContentLoaded', () => {
    CONFIG_KEYS.forEach(k => paintSlider($(k)));
    addLog('控制台加载完成,等待后端连接…', 'info');
});