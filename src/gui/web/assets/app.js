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
// 全局自定义模态弹窗系统 (Promise-based Modal)
// ========================================

let modalResolver = null;

function showModalPrompt({ title = '输入', desc = '', defaultValue = '', placeholder = '', confirmText = '确定', cancelText = '取消' } = {}) {
    return new Promise((resolve) => {
        modalResolver = resolve;
        $('customModalTitle').textContent = title;
        $('customModalDesc').textContent = desc;
        const inputWrap = $('customModalInputWrap');
        const input = $('customModalInput');
        inputWrap.style.display = 'block';
        input.value = defaultValue;
        input.placeholder = placeholder;

        const confirmBtn = $('customModalConfirmBtn');
        confirmBtn.textContent = confirmText;
        confirmBtn.className = 'btn btn-primary';
        $('customModalCancelBtn').textContent = cancelText;

        $('customModalOverlay').classList.add('show');
        setTimeout(() => { input.focus(); input.select(); }, 50);

        input.onkeydown = (e) => {
            if (e.key === 'Enter') confirmCustomModal();
            if (e.key === 'Escape') cancelCustomModal();
        };
    });
}

function showModalConfirm({ title = '确认操作', desc = '', confirmText = '确定', cancelText = '取消', danger = false } = {}) {
    return new Promise((resolve) => {
        modalResolver = resolve;
        $('customModalTitle').textContent = title;
        $('customModalDesc').textContent = desc;
        $('customModalInputWrap').style.display = 'none';

        const confirmBtn = $('customModalConfirmBtn');
        confirmBtn.textContent = confirmText;
        confirmBtn.className = danger ? 'btn btn-danger' : 'btn btn-primary';
        $('customModalCancelBtn').textContent = cancelText;

        $('customModalOverlay').classList.add('show');
        setTimeout(() => confirmBtn.focus(), 50);
    });
}

function confirmCustomModal() {
    $('customModalOverlay').classList.remove('show');
    if (modalResolver) {
        const inputWrap = $('customModalInputWrap');
        if (inputWrap.style.display !== 'none') {
            modalResolver($('customModalInput').value.trim());
        } else {
            modalResolver(true);
        }
        modalResolver = null;
    }
}

function cancelCustomModal() {
    $('customModalOverlay').classList.remove('show');
    if (modalResolver) {
        const inputWrap = $('customModalInputWrap');
        if (inputWrap.style.display !== 'none') {
            modalResolver(null);
        } else {
            modalResolver(false);
        }
        modalResolver = null;
    }
}

function closeCustomModal(e) {
    if (e.target === $('customModalOverlay')) {
        cancelCustomModal();
    }
}

window.showModalPrompt = showModalPrompt;
window.showModalConfirm = showModalConfirm;
window.confirmCustomModal = confirmCustomModal;
window.cancelCustomModal = cancelCustomModal;
window.closeCustomModal = closeCustomModal;

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
    const open = d.classList.contains('open');
    document.body.classList.toggle('log-open', open);
    // 头部按钮与任务栏按钮文案互换(展开时头部提供收起)
    const headBtn = d.querySelector('.log-head .log-clear:last-child');
    if (headBtn) headBtn.textContent = open ? '收起 »' : '展开 «';
    if (open) {
        $('logContent').scrollTop = $('logContent').scrollHeight;
    }
}

// 日志侧栏默认展开(可随时收起, 状态由 body.log-open 驱动)
document.addEventListener('DOMContentLoaded', () => {
    if ($('logDrawer') && !$('logDrawer').classList.contains('open')) {
        toggleLogDrawer();
    }
});

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
let engineSaveTimer = null;

function collectEngineSettings() {
    return {
        catch_hp: Number($('engineCatchHp').value),
        skills: $('engineSkills').value,
        skill_mode: $('engineSkillMode') ? $('engineSkillMode').value : 'cycle',
        open_ball_key: $('engineOpenKey').value,
        ball_slot_key: $('engineBallKey').value,
        patrol_enabled: $('patrolEnabled').checked,
        patrol_move_key: $('patrolMoveKey').value,
        patrol_turn_mode: $('patrolTurnMode').value,
        dry_run: $('engineDry').checked,
    };
}

function pushEngineSettings() {
    clearTimeout(engineSaveTimer);
    engineSaveTimer = setTimeout(async () => {
        try {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.engine_save_settings) {
                const params = collectEngineSettings();
                await pywebview.api.engine_save_settings(params);
            }
        } catch (e) { /* ignore */ }
    }, 300);
}

async function initEngineSettings() {
    try {
        const r = await pywebview.api.engine_get_settings();
        if (r && r.success && r.settings) {
            const s = r.settings;
            if (s.catch_hp !== undefined && $('engineCatchHp')) {
                $('engineCatchHp').value = s.catch_hp;
                paintCatchHpSlider();
            }
            if (s.skills !== undefined && $('engineSkills')) $('engineSkills').value = s.skills;
            if (s.open_ball_key !== undefined && $('engineOpenKey')) $('engineOpenKey').value = s.open_ball_key;
            if (s.ball_slot_key !== undefined && $('engineBallKey')) $('engineBallKey').value = s.ball_slot_key;
            if (s.patrol_enabled !== undefined && $('patrolEnabled')) $('patrolEnabled').checked = Boolean(s.patrol_enabled);
            if (s.patrol_move_key !== undefined && $('patrolMoveKey')) $('patrolMoveKey').value = s.patrol_move_key;
            if (s.patrol_turn_mode !== undefined && $('patrolTurnMode')) $('patrolTurnMode').value = s.patrol_turn_mode;
        }
    } catch (e) { /* 后端未就绪 */ }
}

function paintCatchHpSlider() {
    const el = $('engineCatchHp');
    if (!el) return;
    const pct = ((el.value - el.min) / (el.max - el.min)) * 100;
    el.style.setProperty('--fill', pct + '%');
    const valEl = $('engineCatchHpVal');
    if (valEl) valEl.textContent = el.value + '%';
}

async function engineToggle() {
    try {
        if (engineOn) {
            await pywebview.api.engine_stop();
            showToast('引擎已停止', 'warning');
        } else {
            const params = collectEngineSettings();
            const dry = $('engineDry').checked;
            const r = await pywebview.api.engine_start(dry, params);
            if (!r.success) {
                addLog('引擎启动失败: ' + (r.message || ''), 'error');
            } else {
                notifyAutoStopped(r);
                showToast(dry ? '引擎已启动(模拟模式)' : '引擎已启动', 'success');
            }
        }
        refreshState();
    } catch (e) { addLog('引擎操作异常: ' + e.message, 'error'); }
}

// 模式互斥提示: 后端启动新模式时自动停止了其它组
function notifyAutoStopped(r) {
    if (r && Array.isArray(r.auto_stopped) && r.auto_stopped.length) {
        showToast('模式互斥: 已自动停止 ' + r.auto_stopped.join('、'), 'warning', 6000);
        addLog('模式互斥: 已自动停止 ' + r.auto_stopped.join('、'), 'warning');
    }
}

// ========================================
// 运行模式 (开发者版 / 用户版)
// 用户版隐藏: 视觉调试台、配置文件编辑器、数据采集、诊断工具、演示数据
// ========================================
function isUserMode() {
    return document.body.classList.contains('mode-user');
}

async function applyAppMode() {
    try {
        const r = await pywebview.api.get_app_mode();
        if (r && r.success && r.dev === false) {
            document.body.classList.add('mode-user');
            // 若当前停留在被隐藏的开发者页面,跳回丢球助手
            if (document.querySelector('#page-vision.active')) switchPage('throw');
        }
    } catch (e) { /* 后端未就绪,默认按开发者版显示 */ }
}

// ========================================
// 账户登录区(侧边栏) · 卡密激活
// ========================================

let authState = { authorized: false, dev_mode: false };

function randomPetAvatar() {
    try {
        const vals = Object.values(window.PET_ASSET_MAP || {});
        if (vals.length) return 'assets/img/pets/' + vals[Math.floor(Math.random() * vals.length)];
    } catch (e) { /* fallthrough */ }
    return 'assets/img/balls/100740_国王球.png';
}

function fmtExpire(ms) {
    if (!ms) return '';
    const d = new Date(ms);
    const left = Math.max(0, Math.floor((ms - Date.now()) / 86400000));
    return `${d.getMonth() + 1}/${d.getDate()} · 剩${left}天`;
}

// 付费功能锁判据(后端守卫是硬闸, 这里只是 UI 引导)
window.isAuthed = function () {
    return !!(authState.authorized || authState.dev_mode);
};

function applyAuthLock() {
    // 未登录: 付费页(daily/pvp)内容盖锁幕引导激活; 登录后移除
    document.querySelectorAll('#page-daily, #page-pvp').forEach(page => {
        const need = !window.isAuthed();
        let veil = page.querySelector('.auth-veil');
        if (need && !veil) {
            veil = document.createElement('div');
            veil.className = 'auth-veil';
            veil.innerHTML = '<div class="av-box">'
                + '<div class="av-icon">🔒</div>'
                + '<div class="av-title">该功能需要激活</div>'
                + '<div class="av-desc">点击左侧「未登录 · 点击激活」输入卡密<br>丢球助手/挂机引擎免费使用, 无需激活</div>'
                + '<button class="btn btn-primary" onclick="authClick()">立即激活</button></div>';
            page.appendChild(veil);
        } else if (!need && veil) {
            veil.remove();
        }
    });
}

function renderAuth(st) {
    authState = st || authState;
    const box = $('authAvatarBox'), img = $('authAvatar'), sub = $('authState');
    if (!box || !sub) return;
    if (authState.authorized) {
        box.className = 'auth-avatar authed';
        box.title = (authState.nickname || '') + (authState.dev_mode ? ' · 开发者模式' : '') + ' — 点击退出';
        if (!img.dataset.pet) {
            img.src = randomPetAvatar();       // 登录/刷新时随机换一只精灵头像
            img.dataset.pet = '1';
        }
        img.style.visibility = 'visible';
        sub.innerHTML = authState.dev_mode
            ? '<span class="auth-name">开发者模式</span> · <span class="auth-exp">已授权</span>'
            : `<span class="auth-name">${(authState.nickname || '训练家')}</span><br>`
              + `<span class="auth-exp">到期 ${fmtExpire(authState.expires_at)}</span>`;
    } else {
        box.className = 'auth-avatar unauthed';
        img.dataset.pet = '';
        box.title = '点击激活';
        sub.innerHTML = '<span class="auth-exp">未登录 · 点击激活</span>';
    }
    applyAuthLock();
}

// 头像点击: 未登录 → 激活弹窗; 已登录 → 确认退出
async function authClick() {
    if (authState.authorized) {
        if (authState.dev_mode) { showToast('开发者模式无需退出', 'info'); return; }
        const ok = await showModalConfirm({
            title: '退出登录', desc: '退出后将无法使用自动化功能, 需重新激活卡密。',
            danger: true, confirmText: '退出'
        });
        if (ok) { try { await pywebview.api.auth_logout(); } catch (e) {} }
        return;
    }
    const code = await showModalPrompt({
        title: '激活卡密',
        desc: '请输入卡密(格式 LK-XXXX-XXXX-XXXX), 激活后绑定本机:',
        placeholder: 'LK-XXXX-XXXX-XXXX', confirmText: '激活'
    });
    if (!code) return;
    showToast('激活中…', 'info');
    try {
        const r = await pywebview.api.auth_activate(code);
        showToast(r && r.ok ? '激活成功, 欢迎训练家!' : (r.message || '激活失败'),
                  r && r.ok ? 'success' : 'error');
    } catch (e) { showToast('激活异常: ' + e, 'error'); }
}

// 后端推送登录态(激活/退出/启动校验后)
window.onAuthUpdate = function (st) { renderAuth(st); };

// 启动拉一次登录态
(async function initAuth() {
    const wait = setInterval(async () => {
        if (!(window.pywebview && pywebview.api && pywebview.api.auth_status)) return;
        clearInterval(wait);
        try { renderAuth(await pywebview.api.auth_status()); } catch (e) {}
    }, 200);
})();

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
    if ($('engShiny')) $('engShiny').textContent = s.shiny_count ?? 0;
    if ($('engBallsUsed')) $('engBallsUsed').textContent = s.balls_used_total ?? 0;
}

// ========================================
// 页面导航
// ========================================

// 合并页映射: 旧页面名 → [侧边栏包装页, 页内子tab]
// 自动挂机 = 丢球助手 + 挂机引擎; PVP对战 = 实时对战 + 赛季战报
const MERGED_PAGE_MAP = {
    auto:    ['auto', 'throw'],
    throw:   ['auto', 'throw'],
    engine:  ['auto', 'engine'],
    pvp:     ['pvp', 'battle'],
    battle:  ['pvp', 'battle'],
    history: ['pvp', 'history'],
    ai:      ['ai', null],
    aipvp:   ['aipvp', 'overview'],
    aivision: ['aipvp', 'vision'],
    aibuddy:  ['aipvp', 'buddy'],
    mcp:      ['aipvp', 'mcp'],
};

function switchPage(name) {
    // 进入日常任务页时自动重载清单(配置改了不用手动刷新)
    if (name === 'daily' && typeof dailyReload === 'function') {
        setTimeout(dailyReload, 30);
    }
    const merged = MERGED_PAGE_MAP[name];
    if (merged) {
        activateNavPage(merged[0]);
        // ai 和 aipvp 是独立侧栏页(无子 tab 或有子 tab 的 section)
        if (merged[1] !== null) {
            activatePageTab(merged[0], merged[1]);
        }
        // 懒加载初始化
        if (merged[0] === 'aipvp') {
            if ((merged[1] === 'vision' || merged[1] === null) && typeof initAiVisionSettings === 'function') {
                setTimeout(() => { initAiVisionPresetDropdown(); initAiVisionSettings(); }, 100);
            }
            if ((merged[1] === 'buddy' || merged[1] === null) && typeof initAiBuddySettings === 'function') {
                setTimeout(initAiBuddySettings, 100);
            }
        }
        // 切到赛季战报子页时刷新数据
        if (merged[0] === 'pvp' && merged[1] === 'history' && typeof loadMatchHistory === 'function') {
            setTimeout(loadMatchHistory, 50);
        }
        return;
    }

    activateNavPage(name);

    // 切换到视觉调试台时刷新模板列表
    if (name === 'vision' && typeof tmplRefreshList === 'function') {
        setTimeout(tmplRefreshList, 200);
    }
    // AI 设置页: 初始化全局预设
    if (name === 'ai' && typeof initAiGlobalSettings === 'function') {
        setTimeout(initAiGlobalSettings, 50);
    }
}

// 高亮侧边栏入口并显示对应 .page 区块
function activateNavPage(name) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const page = $(`page-${name}`);
    const nav = document.querySelector(`.nav-item[data-page="${name}"]`);
    if (page) page.classList.add('active');
    if (nav) nav.classList.add('active');
}

// 在合并页内切换子 tab(丢球助手/挂机引擎、实时对战/赛季战报)
function activatePageTab(wrapper, tab) {
    document.querySelectorAll(`#page-${wrapper} .page-tab-btn`).forEach(b =>
        b.classList.toggle('active', b.dataset.tab === tab));
    document.querySelectorAll(`#page-${wrapper} .page-tab-pane`).forEach(d =>
        d.classList.toggle('active', d.dataset.tab === tab));
}

// ========================================
// 咕噜球库存卡片
// ========================================

function renderBallInventory(bi) {
    const card = $('ballInventoryCard');
    if (!card) return;
    if (!bi) { card.style.display = 'none'; return; }
    card.style.display = '';

    // 诊断状态行: 监视是否启用 / 采样次数
    const state = $('ballInvState');
    if (state) {
        if (!bi.enabled) {
            state.textContent = ' · ⚠ 监视未启用(缺 咕噜球1 ROI 或球模板)';
        } else {
            const real = bi.real_throw_count > 0 ? ` · 实际丢球 ${bi.real_throw_count} 颗` : '';
            const corner = (bi.corner && bi.corner.present && bi.corner.ball_name)
                ? ` · 右下角:${bi.corner.ball_name}` : '';
            state.textContent = ` · 已采样 ${bi.samples || 0} 次 · 模式:${bi.mode || 'log'}${real}${corner}`
                + ((bi.samples || 0) === 0 ? ' · 启动丢球后自动识别' : '');
        }
    }

    const blank = { present: false, ball_name: null, count: null, score: 0 };
    const slots = Array.isArray(bi.slots) && bi.slots.length === 6 ? bi.slots : [1, 2, 3, 4, 5, 6].map(i => ({ slot: i, ...blank }));
    const everSampled = (bi.samples || 0) > 0 || bi.updated_at;

    $('ballInvGrid').innerHTML = slots.map(s => {
        if (!s.present) {
            const label = everSampled ? '空' : '未识别';
            return `<div class="bi-cell off"><span class="bi-slot">${s.slot}号</span><span class="bi-name">${label}</span><span class="bi-count">—</span></div>`;
        }
        const name = s.ball_name || '未知球';
        const count = s.count != null ? s.count : '?';
        return `<div class="bi-cell on" title="${name}${s.count != null ? ' × ' + s.count : ''} (匹配度 ${s.score})">`
            + `<span class="bi-slot">${s.slot}号</span>`
            + `<span class="bi-name">${name}</span>`
            + `<span class="bi-count">${count}</span></div>`;
    }).join('');

    const t = $('ballInvTime');
    if (t) t.textContent = bi.updated_at ? '更新于 ' + bi.updated_at : '';
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
    if ($('chkExitOnBattle')) {
        cfg.exit_on_battle = $('chkExitOnBattle').checked;
    }
    // 自动停止条件(0 = 不限制)
    if ($('stop_after_count')) cfg.stop_after_count = Math.max(0, Number($('stop_after_count').value) || 0);
    if ($('stop_after_minutes')) cfg.stop_after_minutes = Math.max(0, Number($('stop_after_minutes').value) || 0);
    return cfg;
}

async function toggleExitOnBattle(checked) {
    try {
        const r = await pywebview.api.update_config({ exit_on_battle: checked });
        if (r.success) {
            showToast(checked ? '已开启遭遇战斗自动退出丢球' : '已关闭遭遇战斗自动退出丢球', 'info');
        }
    } catch (e) {
        showToast('设置失败: ' + e.message, 'error');
    }
}
window.toggleExitOnBattle = toggleExitOnBattle;

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
        if (r.running) notifyAutoStopped(r);
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
        if (s.config.exit_on_battle !== undefined && $('chkExitOnBattle')) {
            if (document.activeElement !== $('chkExitOnBattle')) {
                $('chkExitOnBattle').checked = Boolean(s.config.exit_on_battle);
            }
        }
        // 自动停止条件回填(不干扰正在输入的框)
        [['stop_after_count', 'stop_after_count'], ['stop_after_minutes', 'stop_after_minutes']].forEach(([key, id]) => {
            const el = $(id);
            if (el && s.config[key] !== undefined && document.activeElement !== el) {
                if (Number(el.value) !== Number(s.config[key])) el.value = s.config[key];
            }
        });
    }

    // 咕噜球库存卡片(识别结果或上次持久化数据)
    renderBallInventory(s.ball_inventory);

    // 本轮计时 + 配额剩余 + 异色记录
    renderRunMonitor(s.throw_run);

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

// 打包版降级: 无独立悬浮窗时走主窗口内浮动覆盖层
let _floatOn = false;
function toggleFloatOverlay() {
    _floatOn = !_floatOn;
    const el = document.getElementById('floatOverlay');
    if (el) el.style.display = _floatOn ? '' : 'none';
    const btn = typeof $ === 'function' && $('btnWidget');
    if (btn) {
        btn.classList.toggle('pinned', _floatOn);
        btn.textContent = _floatOn ? '📱 已开' : '📱 悬浮窗';
    }
    // 同步 widgetVisible
    if (typeof widgetVisible !== 'undefined') widgetVisible = _floatOn;
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

async function roiAddNew() {
    const defaultId = 'roi_' + (Object.keys(currentRoi || {}).length + 1);
    const name = await showModalPrompt({
        title: '新建 ROI 区域',
        desc: '请输入 ROI 的唯一英文标识 (ID)：',
        defaultValue: defaultId,
        placeholder: '例如: enemy_hp, skill_1'
    });
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

async function roiDelete(id) {
    const ok = await showModalConfirm({
        title: '删除 ROI 区域',
        desc: `确定从当前模板中删除 ROI「${id}」？`,
        danger: true,
        confirmText: '删除'
    });
    if (!ok) return;
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

async function roiColorPrompt(id) {
    const cur = ROI_COLORS[id] || '#6366f1';
    const color = await showModalPrompt({
        title: '修改 ROI 标注颜色',
        desc: '请输入 16 进制颜色代码 (#hex)：',
        defaultValue: cur,
        placeholder: '#6366f1'
    });
    if (color) roiColorChange(id, color);
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
            <span class="rm-swatch" style="background:${color}" onclick="event.stopPropagation();roiColorPrompt('${id}')" title="点击修改颜色"></span>
            <input class="rm-name" value="${label}" onfocus="this.select()" title="输入后按回车确认改名, 按 Esc 取消"
                onchange="roiRename('${id}',this.value)" onclick="event.stopPropagation()"
                onkeydown="if(event.key==='Enter'){this.blur()}else if(event.key==='Escape'){this.value=this.defaultValue;this.blur()}">
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
        // 不放空白占位选项(用户反馈: 空选项严重影响判断);
        // 列表为空时只给一条禁用提示, 不可选中
        sel.innerHTML = r.templates.length
            ? r.templates.map(t => `<option value="${t.name}">${t.name} (${t.roi_count}ROI)</option>`).join('')
            : '<option value="" disabled>暂无模板</option>';
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
    let name = $('tmplNameInput').value.trim() || tmplName;
    if (!name) {
        name = await showModalPrompt({
            title: '保存 ROI 模板',
            desc: '请输入保存的模板名称：',
            defaultValue: '新模板',
            placeholder: '例如: PVP标准模板'
        });
    }
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
    if (!rois.length) {
        // 允许 0 ROI 保存(与 ROI 工坊一致): 先建模板文件占位, ROI 后续再框
        const ok = await showModalConfirm({
            title: '保存空模板',
            desc: '当前模板没有任何 ROI, 仍要保存吗？可以先建模板占位, 之后继续框选。',
            confirmText: '保存'
        });
        if (!ok) return;
    }
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

async function tmplNewBlank() {
    const defaultName = 'PVP模板_' + new Date().toISOString().slice(5, 10).replace(/-/g, '');
    const name = await showModalPrompt({
        title: '新建空白模板',
        desc: '请输入新模板名称：',
        defaultValue: defaultName,
        placeholder: '例如: 自定义模板'
    });
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
    const ok = await showModalConfirm({
        title: '删除模板',
        desc: `确定永久删除模板文件「${name}」？此操作不可恢复。`,
        danger: true,
        confirmText: '删除模板'
    });
    if (!ok) return;
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
    const front = $('capFront') ? $('capFront').checked : true;
    setVisionStatus(front ? '游戏置前中, 1 秒后截图…' : '截图中…');
    try {
        const r = await pywebview.api.vision_capture(front, 'main');
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
    const front = $('capFront') ? $('capFront').checked : true;
    setVisionStatus(front ? '游戏置前中, 1 秒后截图 + 识别…' : '截图 + 识别中…');
    try {
        const r = await pywebview.api.vision_analyze(front, 'main');
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
        const front = $('capFront') ? $('capFront').checked : true;
        const r = await pywebview.api.vision_save_shot(front);
        if (r.success) setVisionStatus(`已保存 ${r.path}`);
    } catch (e) { addLog('保存截图异常: ' + e.message, 'error'); }
}

// 实时预览画质切换(fast=960 / hd=1440 / full=原尺寸)
async function liveQualityChange() {
    try { await pywebview.api.vision_live_quality($('liveQuality').value); }
    catch (e) { addLog('画质切换异常: ' + e.message, 'error'); }
}

// 打开 ROI 标注工坊独立大窗
async function openRoiStudio() {
    try {
        const r = await pywebview.api.roi_studio_open();
        if (!r.success) showToast(r.message || '打开失败', 'error');
    } catch (e) { showToast('打开工坊异常: ' + e.message, 'error'); }
}

// 工坊/工作台保存 ROI 模板后, 由后端推送同步 currentRoi
window.onRoiStudioSaved = function (payload) {
    if (!payload || !payload.roi) return;
    currentRoi = payload.roi;
    Object.keys(currentRoi).forEach(id => {
        if (!ROI_COLORS[id]) { ROI_COLORS[id] = '#6366f1'; ROI_LABELS[id] = id; }
    });
    renderRoiManager();
    renderRoiOverlay();
    addLog(`ROI 已同步${payload.name ? ' (模板: ' + payload.name + ')' : ''}`, 'info');
};

// ========================================
// 工具箱
// ========================================

let currentToolCategory = 'all';

function filterTools(category) {
    currentToolCategory = category;
    document.querySelectorAll('.tool-tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.filter === category);
    });
    renderTools(toolsCache);
}

function renderTools(tools) {
    toolsCache = tools || [];
    const grid = $('toolGrid');
    if (!grid) return;

    const filtered = currentToolCategory === 'all'
        ? toolsCache
        : toolsCache.filter(t => t.category === currentToolCategory);

    if (!filtered.length) {
        grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--dim); padding: 40px;">暂无该分类的小工具</div>';
        return;
    }

    grid.innerHTML = filtered.map(t => {
        const catClass = t.category ? `tag-${t.category}` : '';
        const icon = t.gui ? '🖼' : '⌨';
        return `
        <div class="tool-card ${t.running ? 'running' : ''}" id="tool-${t.id}">
            <div class="tool-head">
                <div class="tool-icon">${icon}</div>
                <div>
                    <div class="tool-name">
                        ${t.name}
                        <span class="tool-tag ${catClass}">${t.tag || (t.gui ? 'GUI' : 'CLI')}</span>
                    </div>
                </div>
            </div>
            <div class="tool-desc">${t.desc}</div>
            <div class="tool-foot">
                <button class="tool-btn" onclick="toolToggle('${t.id}')">${t.running ? '■ 停止' : '▶ 启动'}</button>
                <span class="tool-pid" id="toolpid-${t.id}"></span>
            </div>
        </div>`;
    }).join('');
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

let configFilesCache = [];
let currentConfigMeta = null;

function markConfigActive(name) {
    document.querySelectorAll('.config-item').forEach(el => el.classList.remove('active'));
    const el = document.querySelector(`.config-item[data-name="${name}"]`);
    if (el) el.classList.add('active');
}

function renderConfigList(files) {
    configFilesCache = files || [];
    const listEl = $('configList');
    if (!listEl) return;
    listEl.innerHTML = configFilesCache.map(f => `
        <div class="config-item ${f.name === currentFile ? 'active' : ''}" data-name="${f.name}" onclick="openConfig('${f.name}')">
            <div class="ci-title">
                <span>${f.icon || '📄'} ${f.title || f.name}</span>
                ${f.gui_page ? `<span class="ci-page-badge">${f.page_hint}</span>` : ''}
            </div>
            <div class="ci-name">
                <span>${f.name}</span>
                <span class="ci-badge">${f.type.toUpperCase()}</span>
            </div>
            <div class="ci-desc">${f.desc}</div>
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

    const meta = configFilesCache.find(f => f.name === name);
    currentConfigMeta = meta;

    if (meta) {
        $('cfgGuideTitle').textContent = `${meta.icon || '📄'} ${meta.title || meta.name} 指南说明`;
        $('cfgDesc').textContent = meta.desc || '';

        const jumpBtn = $('cfgJumpBtn');
        if (jumpBtn) {
            if (meta.gui_page) {
                jumpBtn.style.display = '';
                jumpBtn.textContent = `🔗 前往「${meta.page_hint || '对应'}」页面调整`;
            } else {
                jumpBtn.style.display = 'none';
            }
        }

        const fieldsSection = $('cfgFieldsSection');
        const fieldsGrid = $('cfgFieldsGrid');
        if (fieldsSection && fieldsGrid) {
            if (meta.fields && meta.fields.length > 0) {
                fieldsSection.style.display = '';
                fieldsGrid.innerHTML = meta.fields.map(fld => `
                    <div class="ce-field-item">
                        <span class="ce-field-key">${fld.key || fld.name}</span>
                        <span class="ce-field-desc">${fld.desc}</span>
                    </div>
                `).join('');
            } else {
                fieldsSection.style.display = 'none';
            }
        }

        const btnFmt = $('btnCfgFormat');
        if (btnFmt) {
            btnFmt.style.display = meta.type === 'json' ? '' : 'none';
        }
    }

    try {
        const r = await pywebview.api.config_read(name);
        $('cfgText').value = r.success ? (r.content || '') : `读取失败: ${r.message}`;
    } catch (e) { $('cfgText').value = '读取异常: ' + e.message; }
}

function jumpToConfigGuiPage() {
    if (currentConfigMeta && currentConfigMeta.gui_page) {
        switchPage(currentConfigMeta.gui_page);
    }
}

function setCfgMsg(text, ok) {
    const el = $('cfgMsg');
    if (!el) return;
    el.textContent = text;
    el.className = 'ce-msg ' + (ok ? 'ok' : 'err');
}

async function configSave() {
    if (!currentFile) return;
    try {
        const r = await pywebview.api.config_save(currentFile, $('cfgText').value);
        if (r.success) {
            setCfgMsg(`✓ 已保存 (${new Date().toLocaleTimeString()})`, true);
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

async function configResetDefault() {
    if (!currentFile) return;
    const ok = await showModalConfirm(`确认将「${currentFile}」重置为推荐的默认参数吗？\n当前修改将会被覆盖。`);
    if (!ok) return;
    try {
        const r = await pywebview.api.config_reset_default(currentFile);
        if (r.success) {
            $('cfgText').value = r.content || '';
            setCfgMsg('✓ 已成功恢复推荐默认配置', true);
            showToast('已恢复默认配置', 'success');
        } else {
            setCfgMsg('✗ 重置失败: ' + r.message, false);
        }
    } catch (e) { setCfgMsg('✗ 重置异常: ' + e.message, false); }
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
// AI 全局设置 (密钥/模型, 各AI子功能共用)
// ========================================

// 全局预设表(复用 AI_VISION_PRESETS 的地址映射, 加一个 vision_model 字段)
const AI_GLOBAL_PRESETS = [
    { id: 'doubao',   label: '豆包桥(本地 127.0.0.1:7868)', base: 'http://127.0.0.1:7868/v1', key: 'DoubaoAPI', model: 'deepseek-chat', vision: 'doubao/vision-express' },
    { id: 'openai',   label: 'OpenAI',        base: 'https://api.openai.com/v1',                          key: '', model: 'gpt-4o', vision: 'gpt-4o' },
    { id: 'zhipu',    label: '智谱 GLM',      base: 'https://open.bigmodel.cn/api/paas/v4',               key: '', model: 'glm-4-plus', vision: 'glm-4v-plus' },
    { id: 'moonshot', label: 'Kimi(月之暗面)', base: 'https://api.moonshot.cn/v1',                        key: '', model: 'moonshot-v1-8k', vision: 'moonshot-v1-8k-vision-preview' },
    { id: 'qwen',     label: '通义千问',      base: 'https://dashscope.aliyuncs.com/compatible-mode/v1',  key: '', model: 'qwen-plus', vision: 'qwen-vl-max' },
    { id: 'custom',   label: '自定义…',       base: '', key: '', model: '', vision: '' },
];

// AI 视觉识别的服务商预设表(专用于 aiVisionPreset 下拉)
const AI_VISION_PRESETS = AI_GLOBAL_PRESETS.map(p => ({
    id: p.id, label: p.label, base: p.base, key: p.key, vision: p.vision
}));

function initAiGlobalSettings() {
    const sel = $('aiGlobalPreset');
    if (!sel || sel.options.length) return;   // 已初始化
    AI_GLOBAL_PRESETS.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id; opt.textContent = p.label;
        sel.appendChild(opt);
    });
    sel.value = 'doubao';
    aiGlobalPresetChange();
}

function aiGlobalPresetChange() {
    const sel = $('aiGlobalPreset');
    const p = AI_GLOBAL_PRESETS.find(x => x.id === sel.value);
    if (!p || p.id === 'custom') return;
    if ($('aiGlobalBase')) $('aiGlobalBase').value = p.base;
    if ($('aiGlobalModel')) $('aiGlobalModel').value = p.model;
    if ($('aiGlobalVisionModel')) $('aiGlobalVisionModel').value = p.vision || '';
    if (p.key && $('aiGlobalKey')) $('aiGlobalKey').value = p.key;
}

function aiGlobalOnManualEdit() {
    const sel = $('aiGlobalPreset');
    if (!sel || sel.value === 'custom') return;
    const p = AI_GLOBAL_PRESETS.find(x => x.id === sel.value);
    if (p && $('aiGlobalBase') && $('aiGlobalBase').value.trim() !== p.base) {
        sel.value = 'custom';
    }
}

async function aiGlobalSave() {
    const st = $('aiGlobalStatus');
    // 保存到 settings.yaml 的 ai.* 段
    const params = {
        ai_base_url: ($('aiGlobalBase').value || '').trim(),
        ai_api_key: ($('aiGlobalKey').value || '').trim(),
        ai_model: ($('aiGlobalModel').value || '').trim(),
        ai_vision_model: ($('aiGlobalVisionModel').value || '').trim(),
    };
    try {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.engine_save_settings) {
            await pywebview.api.engine_save_settings(params);
            if (st) st.textContent = '已保存 ✓';
            setTimeout(() => { if (st) st.textContent = ''; }, 2500);
        }
    } catch (e) {
        if (st) st.textContent = '保存失败: ' + e;
    }
}

// 从全局 AI 设置读取 API 字段(用于 aiVision/aiBuddy 保存时合并)
async function _loadGlobalAiParams() {
    try {
        if (!window.pywebview || !window.pywebview.api) return {};
        const r = await window.pywebview.api.engine_get_settings();
        if (r && r.success && r.settings) {
            const s = r.settings;
            return {
                base_url: s.ai_base_url || '',
                api_key: s.ai_api_key || '',
                model: s.ai_model || '',
                vision_model: s.ai_vision_model || '',
            };
        }
    } catch (e) { /* ignore */ }
    return {};
}

// ========================================
// AI 视觉识别设置 (状态栏识图)
// ========================================

let aiVisionLoaded = false;

// AI 视觉服务商预设下拉填充+变更
function initAiVisionPresetDropdown() {
    const sel = $('aiVisionPreset');
    if (!sel || sel.options.length) return;
    AI_VISION_PRESETS.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id; opt.textContent = p.label;
        sel.appendChild(opt);
    });
    sel.value = 'doubao';
    aiVisionPresetChange();
}
function aiVisionPresetChange() {
    const sel = $('aiVisionPreset');
    if (!sel) return;
    const p = AI_VISION_PRESETS.find(x => x.id === sel.value);
    if (!p || p.id === 'custom') return;
    if ($('aiVisionBase')) $('aiVisionBase').value = p.base;
    if ($('aiVisionModel')) $('aiVisionModel').value = p.vision || '';
    if (p.key && $('aiVisionKey')) $('aiVisionKey').value = p.key;
}
function aiVisionOnManualEdit() {
    const sel = $('aiVisionPreset');
    if (!sel || sel.value === 'custom') return;
    if ($('aiVisionBase') && $('aiVisionPreset')) {
        const p = AI_VISION_PRESETS.find(x => x.id === sel.value);
        if (p && $('aiVisionBase').value.trim() !== p.base) {
            sel.value = 'custom';
        }
    }
}

async function initAiVisionSettings() {
    if (aiVisionLoaded) return;
    try {
        const r = await pywebview.api.ai_vision_get_settings();
        if (!(r && r.success && r.settings)) return;   // 后端未就绪/失败, 下次进页重试
        aiVisionLoaded = true;
        const s = r.settings;
        if ($('aiVisionEnabled')) $('aiVisionEnabled').checked = Boolean(s.enabled);
        if ($('aiVisionInterval')) $('aiVisionInterval').value = s.interval_s;
        if ($('aiVisionPrompt')) $('aiVisionPrompt').value = s.prompt || '';
        // ROI 模板下拉: 先拉模板列表, 再选中配置里的模板
        const sel = $('aiVisionTemplate');
        if (sel) {
            sel.innerHTML = '';
            try {
                const tl = await pywebview.api.roi_template_list();
                (tl && tl.templates ? tl.templates : []).forEach(t => {
                    const name = typeof t === 'string' ? t : (t.name || '');
                    if (!name) return;
                    const opt = document.createElement('option');
                    opt.value = name; opt.textContent = name;
                    sel.appendChild(opt);
                });
            } catch (e) { /* ignore */ }
            if (s.template && ![...sel.options].some(o => o.value === s.template)) {
                const opt = document.createElement('option');
                opt.value = s.template; opt.textContent = s.template + ' (未找到)';
                sel.appendChild(opt);
            }
            if (s.template) sel.value = s.template;
        }
    } catch (e) { /* 后端未就绪 */ }
}

function collectAiVisionSettings() {
    const modelOverride = ($('aiVisionModelOverride') ? $('aiVisionModelOverride').value.trim() : '');
    return {
        enabled: $('aiVisionEnabled') ? $('aiVisionEnabled').checked : false,
        interval_s: $('aiVisionInterval') ? Number($('aiVisionInterval').value) || 10 : 10,
        prompt: $('aiVisionPrompt') ? $('aiVisionPrompt').value : '',
        template: $('aiVisionTemplate') ? $('aiVisionTemplate').value : 'pvp状态',
        model: modelOverride || undefined,  // 只传覆盖值
    };
}

async function aiVisionSave() {
    const st = $('aiVisionStatus');
    try {
        // 合并全局 AI 设置
        const global = await _loadGlobalAiParams();
        const params = collectAiVisionSettings();
        if (!params.base_url && global.base_url) params.base_url = global.base_url;
        if (!params.api_key && global.api_key) params.api_key = global.api_key;
        if (!params.model && (global.vision_model || global.model)) params.model = global.vision_model || global.model;
        const r = await pywebview.api.ai_vision_save_settings(params);
        if (st) { st.textContent = r && r.success ? '已保存 ✓' : ('保存失败: ' + (r.message || '')); }
        setTimeout(() => { if (st) st.textContent = ''; }, 2500);
    } catch (e) {
        if (st) st.textContent = '保存失败: ' + e;
    }
}

async function aiVisionTest() {
    const btn = $('btnAiVisionTest'), st = $('aiVisionStatus');
    const card = $('aiVisionResultCard');
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    const oldText = btn.textContent;
    btn.textContent = '⏳ 识别中…';
    if (st) st.textContent = '正在截图并发送给 AI…';
    try {
        await aiVisionSave();   // 先存当前填的配置, 保证测试与运行一致
        const r = await pywebview.api.ai_vision_test();
        if (r && r.success) {
            if (st) st.textContent = '识别完成';
            if (card) {
                card.style.display = '';
                const crops = $('aiVisionCrops');
                crops.innerHTML = '';
                (r.crops || []).forEach(c => {
                    const wrap = document.createElement('div');
                    wrap.style.cssText = 'text-align:center';
                    const img = document.createElement('img');
                    img.src = c.image;
                    img.style.cssText = 'max-width:220px;max-height:56px;border:1px solid var(--line);border-radius:6px;display:block';
                    const cap = document.createElement('div');
                    cap.style.cssText = 'font-size:10.5px;color:var(--dim);margin-top:2px';
                    cap.textContent = c.id;
                    wrap.appendChild(img); wrap.appendChild(cap);
                    crops.appendChild(wrap);
                });
                $('aiVisionMeta').textContent = r.elapsed ? ('· 耗时 ' + r.elapsed + 's') : '';
                $('aiVisionText').textContent = r.text || '';
            }
        } else {
            if (st) st.textContent = '失败: ' + ((r && r.message) || '未知错误');
        }
    } catch (e) {
        if (st) st.textContent = '失败: ' + e;
    } finally {
        btn.disabled = false;
        btn.textContent = oldText;
    }
}

// ========================================
// AI 陪玩伙伴设置 (对局弹幕伙伴)
// ========================================

let aiBuddyLoaded = false;

// 内置人设的弹幕风格示例(用于前端预览, 不翻译英文)
const AI_BUDDY_PERSONA_SAMPLES = {
    salty:   { label: '毒舌主播', sample: '斩杀时 → "收了收了！这波不亏"；失误时 → "这波啊, 这波是送温暖"' },
    tsundere: { label: '傲娇伙伴', sample: '斩杀时 → "哼、也、也就一般般厉害啦"；挨打时 → "才不是担心你呢, 只是提醒血量…"' },
    gentle:  { label: '温柔鼓励', sample: '斩杀时 → "太棒了！"；劣势时 → "不怪你, 对面速度线确实顶, 找机会换回来"' },
};

function aiBuddyPersonaPreview() {
    const sel = $('aiBuddyPersona');
    const pid = sel ? sel.value : 'tsundere';
    const cw = $('aiBuddyCustomPrompt');
    const customWrap = $('aiBuddyPersonaCustomWrap');
    if (customWrap) customWrap.style.display = pid === '__custom__' ? '' : 'none';
    const preview = $('aiBuddyPreview');
    if (!preview) return;
    if (pid === '__custom__') {
        preview.textContent = cw && cw.value.trim()
            ? '自定义: ' + cw.value.slice(0, 60) + (cw.value.length > 60 ? '…' : '')
            : '请输入自定义人设提示词...';
        return;
    }
    const sample = AI_BUDDY_PERSONA_SAMPLES[pid];
    preview.textContent = sample ? sample.sample : '';
}

async function initAiBuddySettings() {
    if (aiBuddyLoaded) return;
    try {
        const r = await pywebview.api.ai_companion_get_settings();
        if (!(r && r.success && r.settings)) return;
        aiBuddyLoaded = true;
        const s = r.settings;
        if ($('aiBuddyEnabled')) $('aiBuddyEnabled').checked = Boolean(s.enabled);
        if ($('aiBuddyInterval')) $('aiBuddyInterval').value = s.interval_min || 20;
        if ($('aiBuddyBase')) $('aiBuddyBase').value = s.base_url || '';
        if ($('aiBuddyModel')) $('aiBuddyModel').value = s.model || '';
        if ($('aiBuddyKey')) $('aiBuddyKey').value = s.api_key || '';
        const personaSel = $('aiBuddyPersona');
        if (personaSel) {
            const pid = s.persona || 'tsundere';
            const inbuilt = ['salty', 'tsundere', 'gentle'];
            personaSel.value = inbuilt.includes(pid) ? pid : '__custom__';
            if (!inbuilt.includes(pid) && $('aiBuddyCustomPrompt')) {
                $('aiBuddyCustomPrompt').value = s.custom_persona || '';
            }
        }
        if ($('aiBuddyCustomPrompt')) {
            if (!s.custom_persona && personaSel && personaSel.value === '__custom__') {
                // 只读了内置人设但下拉在自定义 → 清空
            } else {
                $('aiBuddyCustomPrompt').value = s.custom_persona || '';
            }
        }
        aiBuddyPersonaPreview();
    } catch (e) { /* 后端未就绪 */ }
}

function collectAiBuddySettings() {
    const personaSel = $('aiBuddyPersona');
    const pid = personaSel ? personaSel.value : 'tsundere';
    return {
        enabled: $('aiBuddyEnabled') ? $('aiBuddyEnabled').checked : false,
        interval_min: $('aiBuddyInterval') ? Number($('aiBuddyInterval').value) || 20 : 20,
        persona: pid === '__custom__' ? 'tsundere' : pid,
        custom_persona: pid === '__custom__' ? ($('aiBuddyCustomPrompt').value || '') : '',
    };
}

async function aiBuddySave() {
    const st = $('aiBuddyStatus');
    try {
        // 合并全局 AI 设置
        const global = await _loadGlobalAiParams();
        let params = collectAiBuddySettings();
        if (global.base_url) params.base_url = global.base_url;
        if (global.api_key) params.api_key = global.api_key;
        if (global.model) params.model = global.model;
        const r = await pywebview.api.ai_companion_save_settings(params);
        if (st) { st.textContent = r && r.success ? '已保存 ✓' : ('保存失败: ' + (r.message || '')); }
        setTimeout(() => { if (st) st.textContent = ''; }, 2500);
    } catch (e) {
        if (st) st.textContent = '保存失败: ' + e;
    }
}

// ========================================
// 初始化
// ========================================

window.addEventListener('pywebviewready', async () => {
    addLog('后端已连接', 'success');
    await applyAppMode();
    initEngineSettings();
    initAiVisionSettings();
    refreshState();
    refreshTools();
    if (!isUserMode()) {
        refreshConfigList().then(() => {
            // 默认打开第一个配置
            const first = document.querySelector('.config-item');
            if (first) openConfig(first.dataset.name);
        });
    }
    setInterval(refreshState, 1000);
    setInterval(refreshTools, 2000);
});

document.addEventListener('DOMContentLoaded', () => {
    CONFIG_KEYS.forEach(k => paintSlider($(k)));

    const catchHp = $('engineCatchHp');
    if (catchHp) {
        catchHp.addEventListener('input', () => { paintCatchHpSlider(); pushEngineSettings(); });
        paintCatchHpSlider();
    }

    ['engineSkills', 'engineOpenKey', 'engineBallKey', 'patrolEnabled', 'patrolMoveKey', 'patrolTurnMode', 'engineDry'].forEach(id => {
        const el = $(id);
        if (el) {
            el.addEventListener('change', pushEngineSettings);
            if (el.type === 'text') {
                el.addEventListener('input', pushEngineSettings);
            }
        }
    });

    // 自动停止条件: 修改即持久化
    ['stop_after_count', 'stop_after_minutes'].forEach(id => {
        const el = $(id);
        if (el) el.addEventListener('change', () => {
            if (Number(el.value) < 0 || isNaN(Number(el.value))) el.value = 0;
            pushConfig();
        });
    });

    addLog('控制台加载完成,等待后端连接…', 'info');
    pollMode();
    updateResourceStats();
});

// 退出窗口前保存用户配置
window.addEventListener('beforeunload', () => {
    try {
        if (window.pywebview && window.pywebview.api) {
            if (typeof collectConfig === 'function' && window.pywebview.api.update_config) {
                pywebview.api.update_config(collectConfig());
            }
            if (typeof collectEngineSettings === 'function' && window.pywebview.api.engine_save_settings) {
                pywebview.api.engine_save_settings(collectEngineSettings());
            }
        }
    } catch (e) { /* ignore */ }
});

// ========================================
// 官方数据与资源同步
// ========================================
async function doResourceSync() {
    const btn = $('btnResourceSync');
    const tag = $('rscStatusTag');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="rsc-btn-icon">⏳</span> 正在从官方同步数据...';
    }
    if (tag) {
        tag.textContent = '同步中…';
        tag.style.background = 'rgba(245, 158, 11, 0.2)';
        tag.style.borderColor = 'rgba(245, 158, 11, 0.4)';
        tag.style.color = '#fbbf24';
    }
    showToast('🚀 正在连接官方 API 同步最新图鉴与技能素材...', 'info');

    try {
        const r = await pywebview.api.resource_sync();
        if (r.success) {
            // 后台异步模式: 立即返回"已启动", 完成结果走日志抽屉
            showToast(r.message, 'success');
            addLog(r.message, 'success');
            if (tag) {
                tag.textContent = '后台同步中…';
                tag.style.background = 'rgba(245, 158, 11, 0.2)';
                tag.style.borderColor = 'rgba(245, 158, 11, 0.4)';
                tag.style.color = '#fbbf24';
            }
            if (r.stats) {
                if ($('rscStatPets')) $('rscStatPets').textContent = r.stats.pets || '375+';
                if ($('rscStatSkills')) $('rscStatSkills').textContent = r.stats.skills || '569+';
                if ($('rscStatIcons')) $('rscStatIcons').textContent = r.stats.icons || '18';
            }
        } else {
            showToast('同步失败: ' + r.message, 'error');
            addLog('官方资源同步失败: ' + r.message, 'error');
            if (tag) {
                tag.textContent = '同步异常';
                tag.style.background = 'rgba(239, 68, 68, 0.2)';
                tag.style.borderColor = 'rgba(239, 68, 68, 0.4)';
                tag.style.color = '#f87171';
            }
        }
    } catch (e) {
        showToast('资源同步异常: ' + e, 'error');
        addLog('资源同步异常: ' + e, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="rsc-btn-icon">⚡</span> 一键自动更新资源';
        }
    }
}

async function updateResourceStats() {
    try {
        if (!window.pywebview || !pywebview.api || !pywebview.api.resource_get_stats) return;
        const r = await pywebview.api.resource_get_stats();
        if (r.success && r.stats) {
            if ($('rscStatPets')) $('rscStatPets').textContent = r.stats.pets || '375+';
            if ($('rscStatSkills')) $('rscStatSkills').textContent = r.stats.skills || '569+';
            if ($('rscStatIcons')) $('rscStatIcons').textContent = r.stats.icons || '18';
        }
    } catch (e) {}
}

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
// ========================================
// 本轮计时 / 配额剩余 / 异色记录
// ========================================

function _fmtDuration(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    const mm = String(m).padStart(2, '0'), ss = String(s).padStart(2, '0');
    return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function renderRunMonitor(tr) {
    const timer = $('runTimer'), thrown = $('runThrown'), quota = $('runQuota');
    if (!timer) return;
    tr = tr || {};
    timer.textContent = _fmtDuration(tr.elapsed || 0);
    thrown.textContent = `已丢 ${tr.thrown || 0} 球`;

    let quotaText = '—';
    if ((tr.quota_count > 0 || tr.quota_minutes > 0) && tr.running) {
        const parts = [];
        if (tr.quota_count > 0) parts.push(`剩 ${Math.max(0, tr.quota_count - (tr.thrown || 0))} 球`);
        if (tr.quota_minutes > 0) parts.push(`剩 ${_fmtDuration(tr.quota_minutes * 60 - (tr.elapsed || 0))}`);
        quotaText = parts.join(' / ');
    } else if (tr.running) {
        quotaText = '不限';
    } else {
        quotaText = '未运行';
    }
    quota.textContent = quotaText;
    renderShiny(tr.thrown || 0);
}

function _loadShiny() {
    try { return parseInt(localStorage.getItem('lkw_shiny') || '0', 10) || 0; }
    catch (e) { return 0; }
}

function shinyAdjust(delta) {
    const v = Math.max(0, _loadShiny() + delta);
    try { localStorage.setItem('lkw_shiny', String(v)); } catch (e) {}
    renderShiny(null);
}

function renderShiny(thrown) {
    const el = $('shinyCount'), rate = $('shinyRate');
    if (!el) return;
    if (thrown === null || thrown === undefined) {
        el.textContent = _loadShiny();
        if (rate) rate.textContent = '—';
        return;
    }
    const n = _loadShiny();
    el.textContent = n;
    if (rate) rate.textContent = (n > 0 && thrown > 0) ? `约 ${Math.round(thrown / n)} 球/只` : '—';
}


// ========================================
// 背包盘点(新页面): 打开背包并盘点 / 直接盘点
// ========================================
async function _bagRun(fn, btnId) {
    const btn = $(btnId);
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 进行中…'; }
    try {
        const r = await fn();
        if (!r.success) {
            showToast('操作失败: ' + (r.message || ''), 'error');
            $('bagStatus').textContent = '操作失败: ' + (r.message || '');
            return;
        }
        renderBagResult(r);
        showToast(`盘点完成: ${Object.keys(r.totals || {}).length} 种球`, 'success');
    } catch (e) {
        showToast('盘点异常: ' + e, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = btnId === 'btnBagOpenScan' ? '📦 打开背包并盘点' : '🔍 直接盘点(背包已开)'; }
    }
}

function bagOpenScan() { _bagRun(() => pywebview.api.bag_open_and_scan(), 'btnBagOpenScan'); }
function bagScanDirect() { _bagRun(() => pywebview.api.bag_scan(), 'btnBagScanDirect'); }

function renderBagResult(r) {
    const status = $('bagStatus'), grid = $('bagGrid');
    if (!grid) return;
    if (status) {
        status.textContent = `盘点于 ${r.updated_at || '?'} · 较上次快照`
            + (r.debug_shot ? ` · 现场截图: ${r.debug_shot} (data/screenshots/)` : '');
    }
    const totals = Object.entries(r.totals || {}).sort((a, b) => (b[1].count || 0) - (a[1].count || 0));
    const consumed = r.consumed || {};
    if (!totals.length) {
        grid.innerHTML = '<div class="bag-empty">未识别到咕噜球(背包界面是否正确打开?)</div>';
        return;
    }
    grid.innerHTML = totals.map(([bid, e]) => {
        const used = consumed[bid] ? `<span class="bag-used">较上次 -${consumed[bid].used}</span>` : '';
        const cnt = e.count != null ? e.count : '?';
        return `<div class="bag-cell">
            <img class="bag-img" src="assets/img/balls/${bid}.png" onerror="this.style.visibility='hidden'">
            <div class="bag-name">${e.name}</div>
            <div class="bag-count">×${cnt}</div>
            ${used}
        </div>`;
    }).join('');
}
