// ========================================
// 洛克王国 PVP 助手 · ROI 标注系统
// 从 app.js 拆出: SVG ROI 交互式标注工坊 + ROI 模板管理
// ========================================
//
// 拆分说明:
// app.js 为经典 script, 顶层 function 声明即全局; 而本文件用 IIFE 隔离,
// 因此需要显式把函数挂到 window, 并把共享状态 (currentRoi / ROI_COLORS /
// ROI_LABELS / roiSelected / tmplName 等) 通过 window 上的 getter/setter
// 桥接到模块私有变量, 从而让 app.js / theme.js / HTML 内联 onclick 的
// 读写继续生效。
//
// 依赖: 必须在本文件之前加载 app.js ($ / showToast / showModalPrompt /
// showModalConfirm / setVisionStatus 等工具函数来自 app.js)。
(function () {
    'use strict';

    // $ 由 app.js 顶层 const 声明 (经典 script 共享全局词法环境, 此处直接引用)
    /* global $ */

    // ---------- 模块私有状态 (经 window 桥接对外) ----------
    // 初始色板/标签 (原 app.js 顶部的 ROI_COLORS / ROI_LABELS 已迁至此处)
    let _roiColors = {
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
    let _roiLabels = {
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
    let _currentRoi = null;
    let _roiSelected = null;
    let _tmplName = '';

    // 把共享状态暴露到 window (供 app.js / theme.js / HTML 内联读写)
    Object.defineProperty(window, 'currentRoi', {
        configurable: true,
        get() { return _currentRoi; },
        set(v) { _currentRoi = v; }
    });
    Object.defineProperty(window, 'ROI_COLORS', {
        configurable: true,
        get() { return _roiColors; },
        set(v) { _roiColors = v; }
    });
    Object.defineProperty(window, 'ROI_LABELS', {
        configurable: true,
        get() { return _roiLabels; },
        set(v) { _roiLabels = v; }
    });
    Object.defineProperty(window, 'roiSelected', {
        configurable: true,
        get() { return _roiSelected; },
        set(v) { _roiSelected = v; }
    });
    Object.defineProperty(window, 'tmplName', {
        configurable: true,
        get() { return _tmplName; },
        set(v) { _tmplName = v; }
    });

    // ---------- ROI 工坊 (原 app.js L850-1191) ----------
    let roiDragging = null;       // 当前拖拽状态: {type:'move'|'resize', id, handle, sx, sy, ...}
    let roiDragCreate = null;     // 拖框创建模式: ROI 名称 (非 null 时进入创建)

    // 从 roi_config.json 加载的初始 ROI
    function roiLoadConfig() {
        if (!_currentRoi) return;
        Object.keys(_currentRoi || {}).forEach(id => {
            if (!_roiColors[id]) {
                _roiColors[id] = '#6366f1';
                _roiLabels[id] = id;
            }
        });
        renderRoiManager();
        renderRoiOverlay();
    }

    async function roiAddNew() {
        const defaultId = 'roi_' + (Object.keys(_currentRoi || {}).length + 1);
        const name = await showModalPrompt({
            title: '新建 ROI 区域',
            desc: '请输入 ROI 的唯一英文标识 (ID)：',
            defaultValue: defaultId,
            placeholder: '例如: enemy_hp, skill_1'
        });
        if (!name) return;
        if (_currentRoi[name]) { showToast('ROI 已存在: ' + name, 'warning'); return; }
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
        _currentRoi[name] = { left: +left.toFixed(4), top: +top.toFixed(4), width: +width.toFixed(4), height: +height.toFixed(4) };
        _roiColors[name] = '#' + Math.floor(Math.random() * 0xffffff).toString(16).padStart(6, '0');
        _roiLabels[name] = name;
        _roiSelected = name;
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
        delete _currentRoi[id];
        if (_roiSelected === id) _roiSelected = null;
        renderRoiManager();
        renderRoiOverlay();
    }

    function roiToggleVis(id) {
        if (!_currentRoi[id]) return;
        _currentRoi[id]._hidden = !_currentRoi[id]._hidden;
        renderRoiManager();
        renderRoiOverlay();
    }

    function roiSelect(id) {
        _roiSelected = (_roiSelected === id) ? null : id;
        renderRoiManager();
        renderRoiOverlay();
    }

    function roiRename(id, newName) {
        newName = newName.trim();
        if (!newName || newName === id) return;
        if (_currentRoi[newName]) { showToast('名称已存在', 'warning'); return; }
        _currentRoi[newName] = _currentRoi[id];
        _roiColors[newName] = _roiColors[id] || '#6366f1';
        _roiLabels[newName] = _roiLabels[id] || newName;
        delete _currentRoi[id];
        delete _roiColors[id];
        delete _roiLabels[id];
        if (_roiSelected === id) _roiSelected = newName;
        renderRoiManager();
        renderRoiOverlay();
    }

    function roiColorChange(id, color) {
        _roiColors[id] = color;
        renderRoiManager();
        renderRoiOverlay();
    }

    // ---- SVG 渲染 ----
    function renderRoiOverlay() {
        const svg = $('roiSvg');
        if (!svg) return;
        svg.innerHTML = '';
        if (!$('roiToggle').checked || !_currentRoi) return;

        const img = $('shotImg');
        const iw = img.naturalWidth || 1920, ih = img.naturalHeight || 1080;
        svg.setAttribute('viewBox', `0 0 ${iw} ${ih}`);

        Object.entries(_currentRoi || {}).forEach(([id, box]) => {
            if (!box || !box.width || !box.height || box._hidden) return;
            const color = _roiColors[id] || '#6366f1';
            const label = _roiLabels[id] || id;
            const x = box.left * iw, y = box.top * ih;
            const w = box.width * iw, h = box.height * ih;
            const sel = (_roiSelected === id);

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
        const box = _currentRoi[id];
        if (!box) return;
        const img = $('shotImg');
        const iw = img.naturalWidth || 1920, ih = img.naturalHeight || 1080;

        _roiSelected = id;
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
        const box = _currentRoi[roiDragging.id];
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
            _roiSelected = null;
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
        _currentRoi[name] = { left: +left.toFixed(4), top: +top.toFixed(4), width: +width.toFixed(4), height: +height.toFixed(4) };
        _roiColors[name] = '#' + Math.floor(Math.random() * 0xffffff).toString(16).padStart(6, '0');
        _roiLabels[name] = name;
        _roiSelected = name;
        renderRoiManager();
        renderRoiOverlay();
        showToast('已创建 ROI: ' + name, 'success');
    }

    async function roiColorPrompt(id) {
        const cur = _roiColors[id] || '#6366f1';
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
        const ids = Object.keys(_currentRoi || {}).filter(id => _currentRoi[id] && _currentRoi[id].width);
        $('rmCount').textContent = ids.length;
        list.innerHTML = ids.map(id => {
            const box = _currentRoi[id];
            const color = _roiColors[id] || '#6366f1';
            const label = _roiLabels[id] || id;
            const hidden = box._hidden;
            const active = (_roiSelected === id);
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

    // ---------- ROI 模板管理 (原 app.js L1196-1352) ----------
    let tmplRois = [];
    let tmplBaseRes = [1920, 1080];
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
            _currentRoi = {};
            _tmplName = r.template.name;
            tmplBaseRes = r.template.base_resolution || [1920, 1080];
            tmplRois = r.template.rois || [];
            tmplRois.forEach(roi => {
                _currentRoi[roi.id] = { left: roi.rx, top: roi.ry, width: roi.rw, height: roi.rh };
                if (roi.color) _roiColors[roi.id] = roi.color;
                if (roi.label) _roiLabels[roi.id] = roi.label;
            });
            _roiSelected = null;
            tmplTags = [...new Set(tmplRois.map(r => r.tag || ''))].filter(Boolean);
            tmplTagFilter = {};
            tmplTags.forEach(t => tmplTagFilter[t] = true);
            renderTagFilters();
            renderRoiManager();
            renderRoiOverlay();
            $('tmplNameInput').value = _tmplName;
            setVisionStatus(`已加载模板: ${_tmplName} (${tmplRois.length} ROI)`);
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
        let name = $('tmplNameInput').value.trim() || _tmplName;
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
        Object.keys(_currentRoi || {}).forEach(id => {
            const box = _currentRoi[id];
            if (!box || !box.width || !box.height) return;
            rois.push({
                id, label: _roiLabels[id] || id, color: _roiColors[id] || '#6366f1',
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
                _tmplName = name; tmplBaseRes = baseRes; tmplRois = rois;
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
        if (!_tmplName) { showToast('请先加载或保存模板', 'warning'); return; }
        try {
            const r = await pywebview.api.roi_template_export(_tmplName);
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
        _currentRoi = {};
        tmplRois = []; _tmplName = name; tmplTags = [];
        tmplTagFilter = {}; _roiSelected = null; exitRoiCreate();
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

    // 说明: 原 app.js 在 ROI 块尾部覆写 showShot 以在截图后渲染 ROI 叠加层。
    // 由于 shotNaturalW/shotNaturalH 是 app.js 的模块级 let, 跨文件无法赋值,
    // 故已把该逻辑并入 app.js 的基础 showShot onload 中 (调用 renderRoiOverlay)。
    // 此处仅提供延迟渲染入口, 供 app.js 调用。
    function roiAfterShotRender() {
        setTimeout(() => { renderRoiManager(); renderRoiOverlay(); }, 100);
    }

    // ---------- 暴露到 window (供 app.js / theme.js / HTML 内联调用) ----------
    Object.assign(window, {
        roiLoadConfig,
        roiAddNew,
        roiAddNewAt,
        roiDelete,
        roiToggleVis,
        roiSelect,
        roiRename,
        roiColorChange,
        renderRoiOverlay,
        renderRoiManager,
        roiColorPrompt,
        exitRoiCreate,
        roiAfterShotRender,
        tmplRefreshList,
        tmplLoad,
        renderTagFilters,
        tmplSaveDialog,
        tmplExport,
        tmplImport,
        tmplNewBlank,
        tmplDelete,
    });
})();
