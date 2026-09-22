'use strict';
/* ============================================
   ROI 标注工坊 — 独立大窗编辑器
   与主窗内嵌版同一套交互: 归一化坐标(0-1) + SVG 覆盖层
   保存: roi_template_save(模板) + config_save(运行时 roi_config.json)
   ============================================ */

const $ = (id) => document.getElementById(id);

let roi = {};          // {id: {left, top, width, height, _hidden?}}
let roiMeta = {};      // {id: {color, label}}
let roiSel = null;     // 当前选中 id
let dragging = null;   // {type:'move'|'resize'|'create', ...}
let dragCreate = null; // 拖框创建模式中的 ROI 名
let tmplName = '';
let baseRes = [1920, 1080];
let scale = 1.0, natW = 0, natH = 0;

function toast(msg, kind = 'info') {
    const t = $('toast');
    t.textContent = msg;
    t.className = 'studio-toast show ' + kind;
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => { t.className = 'studio-toast'; }, 2600);
}

function setStatus(text) { $('studioStatus').textContent = text; }

function randomColor() {
    return '#' + Math.floor(Math.random() * 0xffffff).toString(16).padStart(6, '0');
}

// ============================================
// 初始化
// ============================================

function addTmplOption(t) {
    const sel = $('tmplSelect');
    // 首个真实模板进来时替换掉 disabled 占位项(占位项不可选, 不影响判断)
    const placeholder = sel.querySelector('option:disabled');
    if (placeholder) placeholder.remove();
    if ([...sel.options].some(o => o.value === t.name)) return;
    const opt = document.createElement('option');
    opt.value = t.name;
    opt.textContent = `${t.name} (${t.roi_count ?? '?'}ROI)`;
    sel.appendChild(opt);
}

async function init() {
    try {
        const r = await pywebview.api.roi_studio_state();
        if (r && r.success) {
            roi = r.roi || {};
            (r.templates || []).forEach(addTmplOption);
            if (r.image) {
                showShot(r.image, r.width, r.height, '最近一帧');
            } else {
                setStatus('无最近截图 — 点「重新截图」');
            }
        } else {
            setStatus('初始化失败');
        }
    } catch (e) {
        setStatus('初始化失败: ' + e.message);
    }
    renderManager();
    renderOverlay();
}

function waitForApi() {
    if (window.pywebview && pywebview.api) init();
    else setTimeout(waitForApi, 120);
}
window.addEventListener('DOMContentLoaded', waitForApi);

// ============================================
// 截图与画布
// ============================================

async function studioCapture() {
    const front = $('capFront').checked;
    const btn = $('btnCap');
    btn.disabled = true;
    setStatus(front ? '游戏置前中, 1 秒后截图…' : '截图中…');
    try {
        const r = await pywebview.api.vision_capture(front, 'studio');
        if (r.success) {
            showShot(r.image, r.width, r.height, r.title);
        } else {
            setStatus('截图失败');
            toast('截图失败: ' + (r.message || ''), 'error');
        }
    } catch (e) {
        setStatus('截图异常');
        toast('截图异常: ' + e.message, 'error');
    } finally { btn.disabled = false; }
}

function showShot(image, w, h, title) {
    $('shotEmpty').style.display = 'none';
    $('shotView').style.display = 'inline-block';
    const img = $('shotImg');
    img.onload = () => {
        natW = img.naturalWidth;
        natH = img.naturalHeight;
        baseRes = [natW, natH];
        fitView();
        renderManager();
    };
    img.src = image;
    setStatus(`${title || '游戏窗口'} · ${w}×${h}`);
}

function applyScale() {
    if (!natW || !natH) return;
    const view = $('shotView'), img = $('shotImg'), svg = $('roiSvg');
    const dw = Math.round(natW * scale), dh = Math.round(natH * scale);
    view.style.width = dw + 'px';
    view.style.height = dh + 'px';
    img.style.width = dw + 'px';
    img.style.height = dh + 'px';
    img.style.maxWidth = 'none';
    img.style.maxHeight = 'none';
    if (svg) {
        svg.style.width = dw + 'px';
        svg.style.height = dh + 'px';
        svg.setAttribute('preserveAspectRatio', 'none');
    }
    $('zoomVal').textContent = Math.round(scale * 100) + '%';
    renderOverlay();
}

function fitView() {
    const panel = $('studioCanvas');
    if (!panel || !natW || !natH) return;
    const availW = Math.max(panel.clientWidth - 28, 200);
    const availH = Math.max(panel.clientHeight - 28, 200);
    scale = Math.max(0.1, Math.min(availW / natW, availH / natH, 1.0));
    applyScale();
}

function studioZoom(delta, absolute) {
    if (absolute) { scale = delta || 1.0; if (delta === 0) { fitView(); return; } }
    else scale = Math.max(0.1, Math.min(4.0, scale + delta));
    applyScale();
}

window.addEventListener('resize', () => { if ($('shotImg').src) fitView(); });

// ============================================
// ROI 数据操作
// ============================================

function studioRoiAdd() {
    const name = ($('newRoiId').value || '').trim();
    if (!name) { toast('请先输入 ROI ID（如 enemy_hp）', 'warning'); return; }
    if (roi[name]) { toast('ROI 已存在: ' + name, 'warning'); return; }
    if (!natW) { toast('请先截图再创建 ROI', 'warning'); return; }
    dragCreate = name;
    $('roiSvg').classList.add('selecting');
    $('shotView').style.cursor = 'crosshair';
    setStatus(`拖框创建「${name}」: 在截图上按住鼠标拖拽`);
}

function exitRoiCreate() {
    dragCreate = null;
    const svg = $('roiSvg');
    if (svg) svg.classList.remove('selecting');
    $('shotView').style.cursor = 'default';
}

function roiSelect(id) {
    roiSel = (roiSel === id) ? null : id;
    renderManager();
    renderOverlay();
}

function roiRename(id, newName) {
    newName = (newName || '').trim();
    if (!newName || newName === id) return;
    if (roi[newName]) { toast('名称已存在', 'warning'); return; }
    roi[newName] = roi[id];
    roiMeta[newName] = roiMeta[id] || { color: randomColor(), label: newName };
    delete roi[id];
    delete roiMeta[id];
    if (roiSel === id) roiSel = newName;
    renderManager();
    renderOverlay();
    scheduleAutoSave();
}

function roiToggleVis(id) {
    if (!roi[id]) return;
    roi[id]._hidden = !roi[id]._hidden;
    renderManager();
    renderOverlay();
    scheduleAutoSave();
}

function roiDelete(id) {
    delete roi[id];
    delete roiMeta[id];
    if (roiSel === id) roiSel = null;
    renderManager();
    renderOverlay();
    toast('已删除 ROI: ' + id);
    scheduleAutoSave();
}

// ============================================
// SVG 覆盖层渲染
// ============================================

function renderOverlay() {
    const svg = $('roiSvg');
    if (!svg) return;
    svg.innerHTML = '';
    if (!$('roiToggle').checked || !natW) return;

    svg.setAttribute('viewBox', `0 0 ${natW} ${natH}`);

    Object.entries(roi).forEach(([id, box]) => {
        if (!box || !box.width || !box.height || box._hidden) return;
        const color = (roiMeta[id] && roiMeta[id].color) || '#6366f1';
        const label = (roiMeta[id] && roiMeta[id].label) || id;
        const x = box.left * natW, y = box.top * natH;
        const w = box.width * natW, h = box.height * natH;
        const sel = (roiSel === id);

        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        if (sel) g.classList.add('selected');
        g.setAttribute('data-id', id);

        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.classList.add('roi-rect');
        rect.setAttribute('x', x); rect.setAttribute('y', y);
        rect.setAttribute('width', w); rect.setAttribute('height', h);
        rect.setAttribute('stroke', color);
        rect.style.cursor = 'move';
        g.appendChild(rect);

        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.classList.add('roi-label');
        text.setAttribute('x', x + 2); text.setAttribute('y', y - 4);
        text.setAttribute('fill', color);
        text.textContent = label;
        g.appendChild(text);

        if (sel) {
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
            handles.forEach(hd => {
                const hr = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                hr.classList.add('roi-handle', hd.cls);
                hr.setAttribute('x', hd.x); hr.setAttribute('y', hd.y);
                hr.setAttribute('stroke', color);
                hr.setAttribute('data-handle', hd.cls);
                g.appendChild(hr);
            });
        }

        g.addEventListener('pointerdown', (e) => roiOnPointerDown(e, id));
        svg.appendChild(g);
    });
}

// ============================================
// 拖拽交互(创建/移动/缩放)
// ============================================

function roiImgPos(e) {
    const svg = $('roiSvg');
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const p = pt.matrixTransform(ctm.inverse());
    // 限制在图内
    return { x: Math.max(0, Math.min(natW, p.x)), y: Math.max(0, Math.min(natH, p.y)) };
}

function roiOnPointerDown(e, id) {
    e.preventDefault(); e.stopPropagation();
    if (dragCreate) {
        exitRoiCreate();
        setStatus('创建已取消');
    }
    const p = roiImgPos(e);
    const handle = e.target.getAttribute('data-handle');
    const box = roi[id];
    if (!box) return;

    roiSel = id;
    renderManager();
    renderOverlay();

    if (handle) {
        dragging = { type: 'resize', id, handle, sx: p.x, sy: p.y,
            ox: box.left * natW, oy: box.top * natH, ow: box.width * natW, oh: box.height * natH };
    } else {
        dragging = { type: 'move', id, sx: p.x, sy: p.y,
            ox: box.left * natW, oy: box.top * natH };
    }
    document.addEventListener('pointermove', roiOnPointerMove);
    document.addEventListener('pointerup', roiOnPointerUp);
}

function roiOnPointerMove(e) {
    if (!dragging || dragging.type === 'create') return;
    const p = roiImgPos(e);
    const dx = p.x - dragging.sx, dy = p.y - dragging.sy;
    const box = roi[dragging.id];
    if (!box) return;

    if (dragging.type === 'move') {
        let nx = dragging.ox + dx, ny = dragging.oy + dy;
        box.left = Math.max(0, Math.min(1, nx / natW));
        box.top = Math.max(0, Math.min(1, ny / natH));
    } else {
        let ox = dragging.ox, oy = dragging.oy, ow = dragging.ow, oh = dragging.oh;
        const hd = dragging.handle;
        if (hd.includes('n')) { oy += dy; oh -= dy; }
        if (hd.includes('s')) { oh += dy; }
        if (hd.includes('w')) { ox += dx; ow -= dx; }
        if (hd.includes('e')) { ow += dx; }
        if (ow < 5) ow = 5;
        if (oh < 5) oh = 5;
        box.left = Math.max(0, ox / natW);
        box.top = Math.max(0, oy / natH);
        box.width = Math.min(1 - box.left, ow / natW);
        box.height = Math.min(1 - box.top, oh / natH);
    }
    renderOverlay();
}

function roiOnPointerUp() {
    document.removeEventListener('pointermove', roiOnPointerMove);
    document.removeEventListener('pointerup', roiOnPointerUp);
    dragging = null;
    scheduleAutoSave();
}

// 画布空白区域: 拖框创建 / 取消选中
document.addEventListener('DOMContentLoaded', () => {
    const svg = $('roiSvg');
    if (!svg) return;
    svg.addEventListener('pointerdown', function (e) {
        if (e.target !== this) return;  // 只处理空白区域
        if (dragCreate) {
            const p = roiImgPos(e);
            dragging = { type: 'create', name: dragCreate, sx: p.x, sy: p.y };
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
            roiSel = null;
            renderManager();
            renderOverlay();
        }
    });
});

function roiOnCreateMove(e) {
    const ghost = document.getElementById('roiCreateGhost');
    if (!ghost || !dragging) return;
    const p = roiImgPos(e);
    const x = Math.min(dragging.sx, p.x), y = Math.min(dragging.sy, p.y);
    const w = Math.abs(p.x - dragging.sx), h = Math.abs(p.y - dragging.sy);
    ghost.setAttribute('x', x); ghost.setAttribute('y', y);
    ghost.setAttribute('width', w); ghost.setAttribute('height', h);
}

function roiOnCreateUp(e) {
    document.removeEventListener('pointermove', roiOnCreateMove);
    document.removeEventListener('pointerup', roiOnCreateUp);
    const ghost = document.getElementById('roiCreateGhost');
    if (ghost) ghost.remove();
    if (!dragging) return;
    const p = roiImgPos(e);
    const name = dragging.name;
    const sx = dragging.sx, sy = dragging.sy;
    dragging = null;
    exitRoiCreate();
    const left = Math.min(sx, p.x) / natW, top = Math.min(sy, p.y) / natH;
    const width = Math.abs(p.x - sx) / natW, height = Math.abs(p.y - sy) / natH;
    if (width < 0.005 || height < 0.005) { toast('框太小, 请重新拖拽', 'warning'); return; }
    roi[name] = { left: +left.toFixed(4), top: +top.toFixed(4), width: +width.toFixed(4), height: +height.toFixed(4) };
    roiMeta[name] = { color: randomColor(), label: name };
    roiSel = name;
    $('newRoiId').value = '';
    renderManager();
    renderOverlay();
    toast('已创建 ROI: ' + name, 'success');
    scheduleAutoSave();
}

// ============================================
// ROI 管理列表
// ============================================

function renderManager() {
    const list = $('rmList');
    if (!list) return;
    const ids = Object.keys(roi).filter(id => roi[id] && roi[id].width);
    $('rmCount').textContent = ids.length;
    list.innerHTML = ids.map(id => {
        const box = roi[id];
        const meta = roiMeta[id] || { color: '#6366f1', label: id };
        const color = meta.color;
        const label = meta.label;
        const active = (roiSel === id);
        return `<div class="rm-item${active ? ' active' : ''}" onclick="roiSelect('${id}')">
            <input type="color" class="rm-color" value="${color}" title="修改颜色"
                onclick="event.stopPropagation()" onchange="roiMeta['${id}'].color=this.value;renderOverlay();scheduleAutoSave()">
            <input class="rm-name" value="${label}" onfocus="this.select()" title="输入后按回车确认改名, 按 Esc 取消"
                onchange="roiRename('${id}',this.value)" onclick="event.stopPropagation()"
                onkeydown="if(event.key==='Enter'){this.blur()}else if(event.key==='Escape'){this.value=this.defaultValue;this.blur()}">
            <span class="rm-vis" onclick="event.stopPropagation();roiToggleVis('${id}')" title="显隐">${box._hidden ? '🚫' : '👁'}</span>
            <span class="rm-del" onclick="event.stopPropagation();roiDelete('${id}')" title="删除">✕</span>
        </div>`;
    }).join('');
}

// ============================================
// 模板加载 / 保存
// ============================================

async function studioTmplLoad() {
    const name = $('tmplSelect').value;
    if (!name) {
        // 占位项(disabled)没有真实 value: 不清空画布, 避免误触发
        return;
    }
    try {
        const r = await pywebview.api.roi_template_load(name);
        if (!r.success) { toast(r.message || '加载失败', 'error'); return; }
        const t = r.template || {};
        roi = {}; roiMeta = {};
        (t.rois || []).forEach(x => {
            roi[x.id] = { left: x.rx || 0, top: x.ry || 0, width: x.rw || 0, height: x.rh || 0 };
            roiMeta[x.id] = { color: x.color || '#6366f1', label: x.label || x.id };
        });
        tmplName = name;
        $('tmplName').value = name;
        roiSel = null;
        renderManager();
        renderOverlay();
        toast('已加载模板: ' + name, 'success');
    } catch (e) { toast('加载异常: ' + e.message, 'error'); }
}

let savingNow = false;  // 防自动保存与手动保存并发写同一文件

async function studioSave(silent) {
    if (savingNow) {
        if (silent) return;  // 自动保存撞上保存进行中: 跳过(在写的同款内容)
        await new Promise(r => setTimeout(r, 350));
        if (savingNow) return;
    }
    savingNow = true;
    try {
        await doStudioSave(silent);
    } finally {
        savingNow = false;
    }
}

async function doStudioSave(silent) {
    // 空模板也允许保存(先建模板再慢慢框); silent=true 时为自动保存, 不弹 toast
    const ids = Object.keys(roi).filter(id => roi[id] && roi[id].width && roi[id].height);
    let name = ($('tmplName').value || '').trim() || tmplName;
    if (!name) {
        const d = new Date();
        const pad = (x) => String(x).padStart(2, '0');
        name = `自动模板_${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}`;
        $('tmplName').value = name;
    }
    const rois = ids.map(id => ({
        id,
        label: (roiMeta[id] && roiMeta[id].label) || id,
        color: (roiMeta[id] && roiMeta[id].color) || '#6366f1',
        tag: id.includes('enemy') ? 'enemy_team' : (id.includes('battle') ? 'battle_hud' : 'player_team'),
        rx: roi[id].left, ry: roi[id].top, rw: roi[id].width, rh: roi[id].height,
    }));
    const btn = $('btnSave');
    if (!silent) btn.disabled = true;
    try {
        // 原子保存: 模板落盘 + 运行时 roi_config 同步 + 主窗同步, 后端一次完成
        const r = await pywebview.api.roi_studio_save(name, baseRes, rois);
        if (!r.success) { toast('保存失败: ' + (r.message || ''), 'error'); return; }
        tmplName = name;
        addTmplOption({ name, roi_count: ids.length });
        $('tmplSelect').value = name;
        const synced = !!r.synced;
        const summary = `${name} · ${ids.length} ROI${synced ? '' : ' · ⚠运行时同步失败'}`;
        if (silent) {
            setStatus('已自动保存 ' + summary);
            if (!synced) toast('自动保存成功, 但运行时同步失败, 详见日志', 'error');
        } else {
            setStatus('已保存 ' + summary);
            toast('已保存模板「' + name + '」' + (synced ? ',运行时配置已同步' : ',⚠ 运行时同步失败,详见日志'), synced ? 'success' : 'error');
        }
    } catch (e) {
        toast('保存异常: ' + e.message, 'error');
    } finally { if (!silent) btn.disabled = false; }
}

// ---- 自动保存: 任何 ROI 变更(创建/拖动/缩放/改名/删除/显隐/换色)后 0.9s 落盘 ----
let autoSaveTimer = null;
function scheduleAutoSave() {
    if (!natW) return;  // 画面未加载时没有可保存的基准分辨率
    clearTimeout(autoSaveTimer);
    autoSaveTimer = setTimeout(() => { studioSave(true).catch(() => {}); }, 900);
}
