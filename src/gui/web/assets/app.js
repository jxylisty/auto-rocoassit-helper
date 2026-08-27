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
    // 挂机 (AFK)
    enemy_name: '#f87171',
    enemy_elements: '#fbbf24',
    enemy_hp: '#4ade80',
    // PVP 对战
    self_avatar: '#6366f1',
    self_name: '#818cf8',
    enemy_avatar: '#f97316',
    enemy_name_pvp: '#fb923c',
    self_skill: '#10b981',
    lineup_self: '#22d3ee',
    lineup_enemy: '#e879f9',
};
const ROI_LABELS = {
    // 挂机 (AFK)
    enemy_name: '精灵名称',
    enemy_elements: '属性',
    enemy_hp: '敌方血量',
    // PVP 对战
    self_avatar: '我方头像',
    self_name: '我方名称',
    enemy_avatar: '敌方头像',
    enemy_name_pvp: 'PVP敌方名称',
    self_skill: '我方技能',
    lineup_self: '我方阵容',
    lineup_enemy: '敌方阵容',
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

    // 切换到视觉调试台时刷新模板列表
    if (name === 'vision' && typeof tmplRefreshList === 'function') {
        setTimeout(tmplRefreshList, 200);
    }
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
// ========================================
// SVG ROI 交互式标注工坊 (替代旧校准模式)
// ========================================

let roiSelected = null;       // 当前选中的 ROI id
let roiDragging = null;       // 当前拖拽状态: {type:'move'|'resize', id, handle, sx, sy, ...}
let roiDragCreate = null;     // 拖框创建模式: ROI 名称 (非 null 时进入创建)
let roiGhost = null;          // 拖拽创建中的 ghost rect

// 从 roi_config.json 加载的初始 ROI
function roiLoadConfig() {
    if (!currentRoi) return;
    Object.keys(currentRoi || {}).forEach(id => {
        if (!ROI_COLORS[id]) {
            ROI_COLORS[id] = '#6366f1';
            ROI_LABELS[id] = id;
        }
    });
    renderRoiManager();
    renderRoiOverlay();
}

function roiAddNew() {
    const name = prompt('ROI 名称 (英文ID):', 'roi_' + (Object.keys(currentRoi || {}).length + 1));
    if (!name) return;
    if (currentRoi[name]) { showToast('ROI 已存在: ' + name, 'warning'); return; }
    // 进入拖框创建模式
    roiDragCreate = name;
    const svg = $('roiSvg');
    if (svg) svg.classList.add('selecting');
    $('shotView').style.cursor = 'crosshair';
    setVisionStatus(`拖框创建「${name}」: 在截图上按住鼠标拖拽`);
}

function roiAddNewAt(name, x0, y0, x1, y1) {
    const left = Math.min(x0, x1), top = Math.min(y0, y1);
    const width = Math.abs(x1 - x0), height = Math.abs(y1 - y0);
    if (width < 0.005 || height < 0.005) { showToast('框太小，请重新拖拽', 'warning'); return; }
    currentRoi[name] = { left: +left.toFixed(4), top: +top.toFixed(4), width: +width.toFixed(4), height: +height.toFixed(4) };
    ROI_COLORS[name] = '#' + Math.floor(Math.random() * 0xffffff).toString(16).padStart(6, '0');
    ROI_LABELS[name] = name;
    roiSelected = name;
    renderRoiManager();
    renderRoiOverlay();
    showToast('已创建 ROI: ' + name, 'success');
}

function roiDelete(id) {
    if (!confirm(`删除 ROI「${id}」？`)) return;
    delete currentRoi[id];
    if (roiSelected === id) roiSelected = null;
    renderRoiManager();
    renderRoiOverlay();
}

function roiToggleVis(id) {
    if (!currentRoi[id]) return;
    currentRoi[id]._hidden = !currentRoi[id]._hidden;
    renderRoiManager();
    renderRoiOverlay();
}

function roiSelect(id) {
    roiSelected = (roiSelected === id) ? null : id;
    renderRoiManager();
    renderRoiOverlay();
}

function roiRename(id, newName) {
    newName = newName.trim();
    if (!newName || newName === id) return;
    if (currentRoi[newName]) { showToast('名称已存在', 'warning'); return; }
    currentRoi[newName] = currentRoi[id];
    ROI_COLORS[newName] = ROI_COLORS[id] || '#6366f1';
    ROI_LABELS[newName] = ROI_LABELS[id] || newName;
    delete currentRoi[id];
    delete ROI_COLORS[id];
    delete ROI_LABELS[id];
    if (roiSelected === id) roiSelected = newName;
    renderRoiManager();
    renderRoiOverlay();
}

function roiColorChange(id, color) {
    ROI_COLORS[id] = color;
    renderRoiManager();
    renderRoiOverlay();
}

// ---- SVG 渲染 ----
function renderRoiOverlay() {
    const svg = $('roiSvg');
    if (!svg) return;
    svg.innerHTML = '';
    if (!$('roiToggle').checked || !currentRoi) return;

    const img = $('shotImg');
    const iw = img.naturalWidth || 1920, ih = img.naturalHeight || 1080;
    svg.setAttribute('viewBox', `0 0 ${iw} ${ih}`);

    Object.entries(currentRoi || {}).forEach(([id, box]) => {
        if (!box || !box.width || !box.height || box._hidden) return;
        const color = ROI_COLORS[id] || '#6366f1';
        const label = ROI_LABELS[id] || id;
        const x = box.left * iw, y = box.top * ih;
        const w = box.width * iw, h = box.height * ih;
        const sel = (roiSelected === id);

        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        if (sel) g.classList.add('selected');
        g.setAttribute('data-id', id);
        g.setAttribute('color', color);

        // 主矩形
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.classList.add('roi-rect');
        rect.setAttribute('x', x); rect.setAttribute('y', y);
        rect.setAttribute('width', w); rect.setAttribute('height', h);
        rect.setAttribute('stroke', color);
        rect.style.cursor = 'move';
        g.appendChild(rect);

        // 标签
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.classList.add('roi-label');
        text.setAttribute('x', x + 2); text.setAttribute('y', y - 4);
        text.textContent = label;
        g.appendChild(text);

        if (sel) {
            // 8 个拖拽手柄
            const handles = [
                { cls: 'nw', x: x - 4, y: y - 4 },
                { cls: 'n', x: x + w / 2 - 4, y: y - 4 },
                { cls: 'ne', x: x + w - 4, y: y - 4 },
                { cls: 'e', x: x + w - 4, y: y + h / 2 - 4 },
                { cls: 'se', x: x + w - 4, y: y + h - 4 },
                { cls: 's', x: x + w / 2 - 4, y: y + h - 4 },
                { cls: 'sw', x: x - 4, y: y + h - 4 },
                { cls: 'w', x: x - 4, y: y + h / 2 - 4 },
            ];
            handles.forEach(h => {
                const hr = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                hr.classList.add('roi-handle', h.cls);
                hr.setAttribute('x', h.x); hr.setAttribute('y', h.y);
                hr.setAttribute('stroke', color);
                hr.setAttribute('data-handle', h.cls);
                g.appendChild(hr);
            });
        }

        // 事件
        g.addEventListener('pointerdown', (e) => roiOnPointerDown(e, id));
        svg.appendChild(g);
    });
}

// ---- 拖拽交互 ----
function roiImgPos(e) {
    const svg = $('roiSvg');
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const p = pt.matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
}

function roiOnPointerDown(e, id) {
    e.preventDefault(); e.stopPropagation();
    // 如果正在拖框创建模式，点击已有 ROI 则取消创建
    if (roiDragCreate) {
        exitRoiCreate();
        setVisionStatus('创建已取消');
    }
    const p = roiImgPos(e);
    const handle = e.target.getAttribute('data-handle');
    const box = currentRoi[id];
    if (!box) return;
    const img = $('shotImg');
    const iw = img.naturalWidth || 1920, ih = img.naturalHeight || 1080;

    roiSelected = id;
    renderRoiManager();
    renderRoiOverlay();

    if (handle) {
        roiDragging = { type: 'resize', id, handle, sx: p.x, sy: p.y,
            ox: box.left * iw, oy: box.top * ih, ow: box.width * iw, oh: box.height * ih };
    } else {
        roiDragging = { type: 'move', id, sx: p.x, sy: p.y,
            ox: box.left * iw, oy: box.top * ih };
    }
    document.addEventListener('pointermove', roiOnPointerMove);
    document.addEventListener('pointerup', roiOnPointerUp);
}

function roiOnPointerMove(e) {
    if (!roiDragging) return;
    const p = roiImgPos(e);
    const img = $('shotImg');
    const iw = img.naturalWidth || 1920, ih = img.naturalHeight || 1080;
    const dx = p.x - roiDragging.sx, dy = p.y - roiDragging.sy;
    const box = currentRoi[roiDragging.id];
    if (!box) return;

    if (roiDragging.type === 'move') {
        let nx = roiDragging.ox + dx, ny = roiDragging.oy + dy;
        box.left = Math.max(0, Math.min(1, nx / iw));
        box.top = Math.max(0, Math.min(1, ny / ih));
    } else {
        let ox = roiDragging.ox, oy = roiDragging.oy, ow = roiDragging.ow, oh = roiDragging.oh;
        const h = roiDragging.handle;
        if (h.includes('n')) { oy += dy; oh -= dy; }
        if (h.includes('s')) { oh += dy; }
        if (h.includes('w')) { ox += dx; ow -= dx; }
        if (h.includes('e')) { ow += dx; }
        if (ow < 5) ow = 5; if (oh < 5) oh = 5;
        box.left = Math.max(0, ox / iw);
        box.top = Math.max(0, oy / ih);
        box.width = Math.min(1 - box.left, ow / iw);
        box.height = Math.min(1 - box.top, oh / ih);
    }
    renderRoiOverlay();
}

function roiOnPointerUp(e) {
    document.removeEventListener('pointermove', roiOnPointerMove);
    document.removeEventListener('pointerup', roiOnPointerUp);
    roiDragging = null;
}

// 画布空白区域点击: 拖框创建 或 取消选中
$('roiSvg') && $('roiSvg').addEventListener('pointerdown', function(e) {
    if (e.target !== this) return;  // 只处理空白区域
    if (roiDragCreate) {
        // 拖框创建模式
        const p = roiImgPos(e);
        const img = $('shotImg');
        const iw = img.naturalWidth || 1920, ih = img.naturalHeight || 1080;
        roiDragging = { type: 'create', name: roiDragCreate, sx: p.x, sy: p.y };
        // 创建幽灵框
        const ghost = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        ghost.id = 'roiCreateGhost';
        ghost.setAttribute('fill', 'rgba(100,200,255,0.2)');
        ghost.setAttribute('stroke', '#64b5f6');
        ghost.setAttribute('stroke-dasharray', '6,3');
        ghost.setAttribute('x', p.x); ghost.setAttribute('y', p.y);
        ghost.setAttribute('width', 0); ghost.setAttribute('height', 0);
        this.appendChild(ghost);
        document.addEventListener('pointermove', roiOnCreateMove);
        document.addEventListener('pointerup', roiOnCreateUp);
    } else {
        roiSelected = null;
        renderRoiManager();
        renderRoiOverlay();
    }
});

function roiOnCreateMove(e) {
    const ghost = document.getElementById('roiCreateGhost');
    if (!ghost || !roiDragging) return;
    const p = roiImgPos(e);
    const x = Math.min(roiDragging.sx, p.x), y = Math.min(roiDragging.sy, p.y);
    const w = Math.abs(p.x - roiDragging.sx), h = Math.abs(p.y - roiDragging.sy);
    ghost.setAttribute('x', x); ghost.setAttribute('y', y);
    ghost.setAttribute('width', w); ghost.setAttribute('height', h);
}

function exitRoiCreate() {
    roiDragCreate = null;
    const svg = $('roiSvg');
    if (svg) svg.classList.remove('selecting');
    $('shotView').style.cursor = 'default';
}

function roiOnCreateUp(e) {
    document.removeEventListener('pointermove', roiOnCreateMove);
    document.removeEventListener('pointerup', roiOnCreateUp);
    const ghost = document.getElementById('roiCreateGhost');
    if (ghost) ghost.remove();
    if (!roiDragging) return;
    const p = roiImgPos(e);
    const img = $('shotImg');
    const iw = img.naturalWidth || 1920, ih = img.naturalHeight || 1080;
    const name = roiDragging.name;
    const sx = roiDragging.sx, sy = roiDragging.sy;
    roiDragging = null;
    exitRoiCreate();
    const left = Math.min(sx, p.x) / iw, top = Math.min(sy, p.y) / ih;
    const width = Math.abs(p.x - sx) / iw, height = Math.abs(p.y - sy) / ih;
    if (width < 0.005 || height < 0.005) { showToast('框太小，请重新拖拽', 'warning'); return; }
    currentRoi[name] = { left: +left.toFixed(4), top: +top.toFixed(4), width: +width.toFixed(4), height: +height.toFixed(4) };
    ROI_COLORS[name] = '#' + Math.floor(Math.random() * 0xffffff).toString(16).padStart(6, '0');
    ROI_LABELS[name] = name;
    roiSelected = name;
    renderRoiManager();
    renderRoiOverlay();
    showToast('已创建 ROI: ' + name, 'success');
}

// ---- ROI 管理器列表 ----
function renderRoiManager() {
    const list = $('rmList');
    if (!list) return;
    const ids = Object.keys(currentRoi || {}).filter(id => currentRoi[id] && currentRoi[id].width);
    $('rmCount').textContent = ids.length;
    list.innerHTML = ids.map(id => {
        const box = currentRoi[id];
        const color = ROI_COLORS[id] || '#6366f1';
        const label = ROI_LABELS[id] || id;
        const hidden = box._hidden;
        const active = (roiSelected === id);
        return `<div class="rm-item${active ? ' active' : ''}" onclick="roiSelect('${id}')">
            <span class="rm-swatch" style="background:${color}" onclick="event.stopPropagation();roiColorChange('${id}',prompt('颜色 (#hex):',color)||color)"></span>
            <input class="rm-name" value="${label}" onfocus="this.select()"
                onchange="roiRename('${id}',this.value)" onclick="event.stopPropagation()">
            <span class="rm-vis" onclick="event.stopPropagation();roiToggleVis('${id}')" title="显隐">${hidden ? '👁' : '👁'}</span>
            <span class="rm-del" onclick="event.stopPropagation();roiDelete('${id}')" title="删除">✕</span>
        </div>`;
    }).join('');
}

// ========================================
// ROI 模板管理 (保持兼容)
// ========================================
let tmplRois = [];
let tmplBaseRes = [1920, 1080];
let tmplName = '';
let tmplTags = [];
let tmplTagFilter = {};

async function tmplRefreshList() {
    try {
        const r = await pywebview.api.roi_template_list();
        if (!r.success) return;
        const sel = $('tmplSelect');
        sel.innerHTML = '<option value="">-- 选择模板 --</option>' +
            r.templates.map(t => `<option value="${t.name}">${t.name} (${t.roi_count}ROI)</option>`).join('');
    } catch (e) { /* 静默 */ }
}

async function tmplLoad(name) {
    name = name || $('tmplSelect').value;
    if (!name) { tmplRois = []; renderRoiOverlay(); renderRoiManager(); return; }
    try {
        const r = await pywebview.api.roi_template_load(name);
        if (!r.success) { showToast(r.message, 'error'); return; }
        // 清空旧 ROI，全新加载模板
        currentRoi = {};
        tmplName = r.template.name;
        tmplBaseRes = r.template.base_resolution || [1920, 1080];
        tmplRois = r.template.rois || [];
        tmplRois.forEach(roi => {
            currentRoi[roi.id] = { left: roi.rx, top: roi.ry, width: roi.rw, height: roi.rh };
            if (roi.color) ROI_COLORS[roi.id] = roi.color;
            if (roi.label) ROI_LABELS[roi.id] = roi.label;
        });
        roiSelected = null;
        tmplTags = [...new Set(tmplRois.map(r => r.tag || ''))].filter(Boolean);
        tmplTagFilter = {};
        tmplTags.forEach(t => tmplTagFilter[t] = true);
        renderTagFilters();
        renderRoiManager();
        renderRoiOverlay();
        $('tmplNameInput').value = tmplName;
        setVisionStatus(`已加载模板: ${tmplName} (${tmplRois.length} ROI)`);
    } catch (e) { showToast('加载模板失败: ' + e, 'error'); }
}

function renderTagFilters() {
    const el = $('tagFilters');
    if (!el) return;
    el.innerHTML = tmplTags.map(t =>
        `<label class="chk" style="margin-right:6px"><input type="checkbox" ${tmplTagFilter[t] ? 'checked' : ''} onchange="tmplTagFilter['${t}']=this.checked;renderRoiOverlay()">${t}</label>`
    ).join('');
}

async function tmplSaveDialog() {
    const name = $('tmplNameInput').value.trim() || tmplName || prompt('模板名称:', '新模板');
    if (!name) return;
    const rois = [];
    Object.keys(currentRoi || {}).forEach(id => {
        const box = currentRoi[id];
        if (!box || !box.width || !box.height) return;
        rois.push({
            id, label: ROI_LABELS[id] || id, color: ROI_COLORS[id] || '#6366f1',
            tag: id.includes('enemy') ? 'enemy_team' : (id.includes('battle') ? 'battle_hud' : 'player_team'),
            rx: box.left, ry: box.top, rw: box.width, rh: box.height,
        });
    });
    if (!rois.length) { showToast('请先创建至少一个 ROI', 'warning'); return; }
    const img = $('shotImg');
    const baseRes = img ? [img.naturalWidth, img.naturalHeight] : [1920, 1080];
    try {
        const r = await pywebview.api.roi_template_save(name, baseRes, rois);
        if (r.success) {
            tmplName = name; tmplBaseRes = baseRes; tmplRois = rois;
            tmplTags = [...new Set(rois.map(r => r.tag || ''))].filter(Boolean);
            tmplTagFilter = {};
            tmplTags.forEach(t => tmplTagFilter[t] = true);
            renderTagFilters(); tmplRefreshList();
            $('tmplNameInput').value = name;
            showToast('模板已保存: ' + name, 'success');
        }
    } catch (e) { showToast('保存失败: ' + e, 'error'); }
}

async function tmplExport() {
    if (!tmplName) { showToast('请先加载或保存模板', 'warning'); return; }
    try {
        const r = await pywebview.api.roi_template_export(tmplName);
        if (!r.success) { showToast(r.message, 'error'); return; }
        await navigator.clipboard.writeText(r.json);
        showToast('模板 JSON 已复制到剪贴板', 'success');
    } catch (e) { showToast('导出失败: ' + e, 'error'); }
}

async function tmplImport() {
    try {
        const text = await navigator.clipboard.readText();
        if (!text || !text.includes('"rois"')) { showToast('剪贴板无有效模板 JSON', 'warning'); return; }
        const r = await pywebview.api.roi_template_import(text);
        if (r.success) { tmplRefreshList(); showToast('模板已导入', 'success'); tmplLoad(r.filename.replace('.json', '')); }
    } catch (e) { showToast('导入失败: ' + e, 'error'); }
}

function tmplNewBlank() {
    const name = prompt('新模板名称:', 'PVP模板_' + new Date().toISOString().slice(5, 10).replace(/-/g, ''));
    if (!name) return;
    currentRoi = {};
    tmplRois = []; tmplName = name; tmplTags = [];
    tmplTagFilter = {}; roiSelected = null; exitRoiCreate();
    $('tmplSelect').value = '';
    $('tmplNameInput').value = name;
    renderTagFilters();
    renderRoiManager();
    renderRoiOverlay();
    setVisionStatus(`空白模板: ${name} · 点击 [+ 新建] 开始标注`);
    showToast('已创建空白模板: ' + name, 'success');
}

async function tmplDelete() {
    const name = $('tmplSelect').value;
    if (!name) { showToast('请先选择模板', 'warning'); return; }
    if (!confirm(`确定删除模板「${name}」？`)) return;
    try {
        const r = await pywebview.api.roi_template_delete(name);
        if (r.success) { tmplRefreshList(); showToast('模板已删除', 'success'); }
        else { showToast(r.message, 'error'); }
    } catch (e) { showToast('删除失败: ' + e, 'error'); }
}

// ---- 截图后自动加载 roi_config 到交互系统 ----
const _orig_showShot = showShot;
showShot = function(image, w, h, title) {
    _orig_showShot(image, w, h, title);
    $('shotImg').onload = () => {
        shotNaturalW = $('shotImg').naturalWidth;
        shotNaturalH = $('shotImg').naturalHeight;
        fitShotToPanel();
        // 延迟渲染 ROI (等待 SVG 就绪)
        setTimeout(() => { renderRoiManager(); renderRoiOverlay(); }, 100);
    };
};

// ========================================
// 实时识别(后端推送)
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
    renderRoiManager();
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

let shotScale = 1.0;
let shotNaturalW = 0, shotNaturalH = 0;

function showShot(image, w, h, title) {
    $('shotEmpty').style.display = 'none';
    const view = $('shotView');
    view.style.display = 'inline-block';
    const img = $('shotImg');
    img.src = image;
    img.onload = () => {
        shotNaturalW = img.naturalWidth;
        shotNaturalH = img.naturalHeight;
        fitShotToPanel();
        renderRoiManager();
    };
    setVisionStatus(`${title || '游戏窗口'} · ${w}×${h}`);
}

function shotZoom(delta, setAbsolute) {
    if (setAbsolute) { shotScale = delta; }
    else { shotScale = Math.max(0.25, Math.min(4.0, shotScale + delta)); }
    applyShotScale();
}

function applyShotScale() {
    const view = $('shotView');
    const img = $('shotImg');
    const svg = $('roiSvg');
    if (!shotNaturalW || !shotNaturalH) return;
    const dw = Math.round(shotNaturalW * shotScale);
    const dh = Math.round(shotNaturalH * shotScale);
    // 显式设置 view / img / svg 三者宽高完全一致
    view.style.width = dw + 'px';
    view.style.height = dh + 'px';
    img.style.width = dw + 'px';
    img.style.height = dh + 'px';
    img.style.maxWidth = 'none';
    img.style.maxHeight = 'none';
    if (svg) {
        svg.style.width = dw + 'px';
        svg.style.height = dh + 'px';
        svg.setAttribute('preserveAspectRatio', 'none'); // 宽高比已保证一致，无需再缩放
    }
    $('shotZoomVal').textContent = Math.round(shotScale * 100) + '%';
    renderRoiOverlay();
}

function fitShotToPanel() {
    const panel = $('shotPanel');
    if (!panel || !shotNaturalW || !shotNaturalH) return;
    const pw = panel.clientWidth, ph = panel.clientHeight;
    const page = document.querySelector('.page.active');
    const availW = pw > 24 ? pw - 24 : (page ? page.clientWidth - 24 : 800);
    const availH = Math.max(ph > 24 ? ph - 24 : 0, page ? page.clientHeight - 60 : 400, 400);
    shotScale = Math.min(availW / shotNaturalW, availH / shotNaturalH, 1.0);
    shotScale = Math.max(0.25, shotScale);
    applyShotScale();
}

window.addEventListener('resize', () => { if ($('shotImg').src) fitShotToPanel(); });

async function visionCapture() {
    const btn = $('btnVCap'); btn.disabled = true;
    setVisionStatus('截图中…');
    try {
        const r = await pywebview.api.vision_capture();
        if (r.success) {
            // 加载 ROI 配置（失败也保证 currentRoi 不为 null）
            if (!currentRoi || !Object.keys(currentRoi).length) {
                try {
                    const cr = await pywebview.api.config_load('roi_config.json');
                    if (cr.success && cr.data) currentRoi = cr.data;
                } catch (e) { /* 忽略 */ }
                if (!currentRoi) currentRoi = {};
            }
            showShot(r.image, r.width, r.height, r.title);
            renderRoiManager();
        } else setVisionStatus('截图失败');
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
    const elRaw = $('recRaw'); if (elRaw) elRaw.textContent = rawBits.join('  ') || '—';

    // 原始 JSON
    const elJson = $('rawJson'); if (elJson) elJson.textContent = JSON.stringify(result, null, 2);
}

async function visionAnalyze() {
    const btn = $('btnVAna'); btn.disabled = true;
    setVisionStatus('截图 + 识别中…');
    try {
        const r = await pywebview.api.vision_analyze();
        if (r.success) {
            showShot(r.image, r.width, r.height, r.title);
            currentRoi = r.roi || {};
            renderRoiManager();
            renderRoiOverlay();
            renderResults(r.result);
        } else {
            setVisionStatus('识别失败');
        }
    } catch (e) { addLog('识别异常: ' + e.message, 'error'); setVisionStatus('识别异常'); }
    finally { btn.disabled = false; }
}

// ---- OCR 预览（结果输出到日志，不在图上显示）----
async function visionOcrPreview() {
    const btn = $('btnOcr'); btn.disabled = true;
    if (!currentRoi || !Object.keys(currentRoi).length) {
        showToast('请先截图或加载模板', 'warning');
        btn.disabled = false; return;
    }
    setVisionStatus('OCR 识别中…');
    try {
        const r = await pywebview.api.vision_ocr_preview(currentRoi);
        if (!r.success) { setVisionStatus('OCR 失败: ' + r.message); return; }
        addLog('OCR识别结果:', 'info');
        Object.entries(r.results).forEach(([id, result]) => {
            const label = ROI_LABELS[id] || result.label || id;
            const mark = result.corrected ? '✅' : (result.conf > 0.5 ? '' : '⚠️');
            addLog(`${mark}${label}：${result.text}`, result.conf > 0.5 ? 'info' : 'warning');
        });
        setVisionStatus(`OCR 完成: ${Object.keys(r.results).length} 个 ROI`);
    } catch (e) { addLog('OCR 预览异常: ' + e.message, 'error'); setVisionStatus('OCR 异常'); }
    finally { btn.disabled = false; }
}

function renderOcrResults(ocrResults) {
    // 不再使用 —— 结果已改为 addLog 输出
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
    pollMode();
});

// ========================================
// 模式轮询 (更新侧边栏模式指示器)
// ========================================
async function pollMode() {
    try {
        const r = await pywebview.api.mode_get();
        if (r.success) {
            const dot = document.querySelector('.mode-dot');
            const label = $('modeLabel');
            if (dot) dot.className = 'mode-dot mode-' + r.mode;
            if (label) label.textContent = r.label || r.mode;
        }
    } catch (e) { /* 静默 */ }
    setTimeout(pollMode, 3000);
}