/* theme.js · 绘本皮肤素材注入 V4 (2026-09-15)
   只做展示增强：给库存格子与模式卡徽章注入官方素材图，缺图自动回落。
   不参与任何业务逻辑，可整体移除而不影响功能。 */
(function () {
  var BALL_MAP = {
    '普通咕噜球': '100741', '高级咕噜球': '100003', '国王球': '100740', '瞌睡球': '100261',
    '美妙球': '100262', '好战球': '100263', '光合球': '100271', '网兜球': '100272',
    '暗星球': '100273', '调温球': '100274', '绝缘球': '100275', '水珠球': '100281',
    '冰凌球': '100282', '淘沙球': '100283', '变幻球': '100284', '捕光球': '100285',
    '棱镜球': '100286', '可可果球': '100287', '织梦棱镜球': '100288', '狂欢棱镜球': '100289',
    '奇趣球': '100290', '铅绘棱镜球': '100291', '童话球': '100982', '柔软咕噜球': '280001'
  };
  var MODE_ICON = {
    cardNormal: 'assets/img/balls/100741_普通咕噜球.png',
    cardBomber: 'assets/img/balls/100003_高级咕噜球.png',
    cardSkill:  'assets/img/icons/electric.webp'
  };

  function makeImg(src, cls) {
    var img = document.createElement('img');
    img.className = cls; img.src = src; img.alt = '';
    img.onerror = function () { if (img.parentNode) img.parentNode.removeChild(img); };
    return img;
  }

  function enhanceCells() {
    var cells = document.querySelectorAll('.bi-cell');
    for (var i = 0; i < cells.length; i++) {
      var cell = cells[i];
      if (cell.querySelector('img')) continue;
      var nameEl = cell.querySelector('.bi-name');
      if (!nameEl) continue;
      var name = (nameEl.textContent || '').trim();
      var id = BALL_MAP[name];
      if (!id) continue;
      cell.insertBefore(makeImg('assets/img/balls/' + id + '_' + name + '.png', 'bi-img'), cell.firstChild);
    }
  }

  function enhanceModeIcons() {
    Object.keys(MODE_ICON).forEach(function (cid) {
      var card = document.getElementById(cid);
      if (!card) return;
      var icon = card.querySelector('.mode-icon');
      if (!icon || icon.querySelector('img')) return;
      var img = makeImg(MODE_ICON[cid], 'mode-medal-img');
      img.onload = function () {
        var svg = icon.querySelector('svg');
        if (svg) svg.style.display = 'none';
      };
      icon.insertBefore(img, icon.firstChild);
    });
  }

  function runAll() { try { enhanceModeIcons(); enhanceCells(); } catch (e) {} }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runAll);
  } else { runAll(); }

  if (typeof MutationObserver !== 'undefined') {
    var pending = null;
    var mo = new MutationObserver(function () {
      if (pending) return;
      pending = setTimeout(function () { pending = null; enhanceCells(); }, 120);
    });
    var watch = function () {
      ['ballInvGrid', 'bagGrid'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) mo.observe(el, { childList: true });
      });
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', watch);
    } else { watch(); }
  }
})();

/* ================= 自绘标题栏控制器 V4.3 =================
   拖拽移动: 使用 pywebview 内置 pywebview-drag-region 协议(绝对坐标,
   无读改竞争, 抖动根除); 自研增量移动已移除。
   缩放手柄: 绝对尺寸协议 —— 手势起点只读一次尺寸, 之后每次发送绝对目标。 */
(function () {
  function api() { return (window.pywebview && pywebview.api) ? pywebview.api : null; }

  /* --- 关闭(走后端 destroy -> closed 事件持久化) --- */
  window.windowClose = function () {
    var a = api();
    if (a && a.window_close) { a.window_close(); return; }
    window.close();
  };

  /* --- 最小化: 直调 pywebview.api, 不依赖 app.js --- */
  window.minimize_window = function () {
    var a = api();
    if (a && a.minimize_window) { a.minimize_window(); return; }
  };

  /* --- 右下角缩放手柄(绝对协议) --- */
  var rz = null;
  var grip = document.getElementById('winResizeGrip');
  if (grip) {
    grip.addEventListener('mousedown', function (e) {
      if (e.button !== 0) return;
      var a = api();
      if (!a || !a.window_get_size) return;
      e.preventDefault(); e.stopPropagation();
      a.window_get_size().then(function (r) {
        if (!r || !r.success) return;
        rz = { x: e.screenX, y: e.screenY, w: r.width, h: r.height, lw: r.width, lh: r.height };
      }).catch(function () {});
    });
  }
  window.addEventListener('mousemove', function (e) {
    if (!rz) return;
    var nw = Math.max(1080, Math.min(3840, rz.w + (e.screenX - rz.x)));
    var nh = Math.max(720, Math.min(2160, rz.h + (e.screenY - rz.y)));
    if (Math.abs(nw - rz.lw) < 2 && Math.abs(nh - rz.lh) < 2) return;  // 2px 死区
    rz.lw = nw; rz.lh = nh;
    var a = api();
    if (a && a.window_resize_to) a.window_resize_to(nw, nh);
  }, true);
  window.addEventListener('mouseup', function () { rz = null; });
  window.addEventListener('blur', function () { rz = null; });

  /* --- 置顶按钮状态与侧栏 btnPin 双向同步(不改 app.js) --- */
  function syncPin() {
    var src = document.getElementById('btnPin');
    var dst = document.getElementById('tbBtnTop');
    if (!src || !dst) return;
    var on = src.classList.contains('pinned');
    dst.classList.toggle('pinned', on);
    dst.title = on ? '取消置顶' : '窗口置顶';
    /* app.js 会覆写按钮文字带回 emoji，这里统一净化为纯文字 */
    var want = on ? '已置顶' : '置顶';
    if ((src.textContent || '').indexOf(want) === -1 || /[\u2190-\u27BF\u2B00-\u2BFF\uD83C-\uD83E]/.test(src.textContent)) {
      src.textContent = want;
    }
  }
  function watchPin() {
    var src = document.getElementById('btnPin');
    if (!src || typeof MutationObserver === 'undefined') return;
    new MutationObserver(syncPin).observe(src, { attributes: true, childList: true, subtree: true });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { syncPin(); watchPin(); });
  } else { syncPin(); watchPin(); }
})();

/* ================= ROI 显示名编辑 + 自动持久化 V4.2 =================
   语义修正：管理器里的输入框改为「显示名」，ROI 的 id(识别键) 保持稳定，
   后端按固定 id 取框的逻辑不受改名影响。显示名自动落盘：
   - 模板模式 → roi_template_save(label 已有字段)
   - live 模式 → config_save('roi_config.json')，框内新增 label/color 字段
     (后端加载已容错，附加字段不影响识别)
   不修改 app.js；在 app.js 执行完成后包一层覆写。 */
(function () {
  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
    if (typeof window.renderRoiManager !== 'function' || typeof window.roiRename !== 'function') return;
    if (window.__roiRenamePatched) return;
    window.__roiRenamePatched = true;

    var origRender = window.renderRoiManager;

    /* 从框数据同步显示名/颜色到前端缓存(下次启动时恢复上次改名) */
    function syncFromBoxes() {
      try {
        if (typeof currentRoi === 'undefined' || !currentRoi) return;
        Object.keys(currentRoi).forEach(function (id) {
          var box = currentRoi[id];
          if (!box || typeof box !== 'object') return;
          if (box.label && (typeof ROI_LABELS[id] === 'undefined' || ROI_LABELS[id] === id)) {
            ROI_LABELS[id] = box.label;
          }
          if (box.color && (typeof ROI_COLORS[id] === 'undefined' || ROI_COLORS[id] === '#6366f1')) {
            ROI_COLORS[id] = box.color;
          }
        });
      } catch (e) { /* 静默 */ }
    }

    window.renderRoiManager = function () {
      try { syncFromBoxes(); } catch (e) {}
      var r = origRender.apply(this, arguments);
      try { decorateRows(); } catch (e) {}
      return r;
    };

    /* 给管理器行加 ID 提示(悬停可见), 输入框旁不再混淆 id 与显示名 */
    function decorateRows() {
      var list = document.getElementById('rmList');
      if (!list) return;
      var items = list.querySelectorAll('.rm-item');
      for (var i = 0; i < items.length; i++) {
        var input = items[i].querySelector('.rm-name');
        if (!input) continue;
        var input2 = input;
        input2.title = '显示名(可自由修改并自动保存)';
        input2.setAttribute('data-id-hint', '1');
      }
      try {
        if (typeof currentRoi !== 'undefined' && currentRoi) {
          items.forEach && null;
          for (var j = 0; j < items.length; j++) {
            var inp = items[j].querySelector('.rm-name');
            if (!inp) continue;
            var onchange = inp.getAttribute('onchange') || '';
            var m = onchange.match(/roiRename\('([^']+)'/);
            if (m) items[j].title = 'ID: ' + m[1] + ' · 识别键不可改,显示名可改';
          }
        }
      } catch (e) { /* 静默 */ }
    }

    /* 清理框数据中的临时键, 返回可直接序列化的副本 */
    function cleanBoxes() {
      var out = {};
      if (typeof currentRoi === 'undefined' || !currentRoi) return out;
      Object.keys(currentRoi).forEach(function (id) {
        var box = currentRoi[id];
        if (!box || typeof box !== 'object') return;
        var c = {};
        Object.keys(box).forEach(function (k) {
          if (k.charAt(0) === '_') return;      // _hidden 等临时态不落盘
          c[k] = box[k];
        });
        if (typeof ROI_LABELS[id] !== 'undefined') c.label = ROI_LABELS[id];
        if (typeof ROI_COLORS[id] !== 'undefined') c.color = ROI_COLORS[id];
        out[id] = c;
      });
      return out;
    }

    var lastSaved = '';
    function snapshot() {
      try { return JSON.stringify(cleanBoxes()); } catch (e) { return ''; }
    }

    /* 自动持久化: 模板 → 模板文件; live → roi_config.json */
    async function persist() {
      var snap = snapshot();
      if (!snap || snap === lastSaved) return;
      lastSaved = snap;
      var a = (window.pywebview && pywebview.api) ? pywebview.api : null;
      if (!a) return;
      try {
        if (typeof tmplName !== 'undefined' && tmplName) {
          /* 模板模式: 按模板存储格式保存 */
          var rois = [];
          var boxes = JSON.parse(snap);
          Object.keys(boxes).forEach(function (id) {
            var b = boxes[id];
            if (!b.width || !b.height) return;
            rois.push({
              id: id, label: b.label || id, color: b.color || '#6366f1',
              tag: id.indexOf('enemy') >= 0 ? 'enemy_team' : (id.indexOf('battle') >= 0 ? 'battle_hud' : 'player_team'),
              rx: b.left, ry: b.top, rw: b.width, rh: b.height
            });
          });
          if (!rois.length) return;
          var img = document.getElementById('shotImg');
          var baseRes = (img && img.naturalWidth) ? [img.naturalWidth, img.naturalHeight] : [1920, 1080];
          var r = await a.roi_template_save(tmplName, baseRes, rois);
          if (r && r.success) showToast('显示名已保存到模板: ' + tmplName, 'success');
          else if (r && r.message) showToast('保存失败: ' + r.message, 'error');
        } else {
          /* live 模式: 写 roi_config.json(后端热重载识别管线) */
          var r2 = await a.config_save('roi_config.json', snap);
          if (r2 && r2.success) showToast('显示名已保存到 roi_config.json', 'success');
          else if (r2 && r2.message && /开发者|DEV/.test(r2.message)) {
            showToast('非开发者模式, 显示名仅本次会话生效', 'warning');
          } else if (r2 && r2.message) {
            showToast('保存失败: ' + r2.message, 'error');
          }
        }
      } catch (e) {
        showToast('显示名保存异常: ' + e, 'error');
      }
    }

    /* 覆写改名: 只改显示名(ROI_LABELS), id/识别键保持不变 → 保存 */
    window.roiRename = function (id, newName) {
      newName = (newName || '').trim();
      if (!id || !newName) return;
      if (typeof currentRoi === 'undefined' || !currentRoi[id]) return;
      if (ROI_LABELS[id] === newName) return;
      ROI_LABELS[id] = newName;          // 仅显示名; id 不动 → 识别语义安全
      renderRoiManager();
      renderRoiOverlay();
      persist();
    };
  });
})();

/* ================= ROI 改名键盘保证 V4.3 =================
   回车 = 提交并自动保存; Esc = 撤销本次输入。
   委托监听挂在 #rmList 上, 列表重渲染不丢失。 */
(function () {
  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }
  ready(function () {
    var list = document.getElementById('rmList');
    if (!list || list.__roiKeyBound) return;
    list.__roiKeyBound = true;
    list.addEventListener('keydown', function (e) {
      var input = e.target;
      if (!input.classList || !input.classList.contains('rm-name')) return;
      if (e.key === 'Enter') {
        e.preventDefault();
        input.blur();          // 触发 onchange -> roiRename -> 自动保存
      } else if (e.key === 'Escape') {
        e.preventDefault();
        var m = (input.getAttribute('onchange') || '').match(/roiRename\('([^']+)'/);
        if (m) {
          var id = m[1];
          try { input.value = (typeof ROI_LABELS !== 'undefined' && ROI_LABELS[id]) ? ROI_LABELS[id] : id; } catch (err) {}
        }
        input.blur();
      }
    });
  });
})();

/* ================= 自动更新入口 V4.4 =================
   后台检查由 Python 侧完成(结果随 get_state.update_hint 推送);
   这里负责: 顶栏"有可用更新"按钮 + 点击后检查/应用更新的流程与反馈。 */
(function () {
  function api() { return (window.pywebview && pywebview.api) ? pywebview.api : null; }
  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  var btn = null;
  function ensureBtn() {
    if (btn) return btn;
    var bar = document.querySelector('.titlebar .tb-drag');
    if (!bar) return null;
    btn = document.createElement('button');
    btn.id = 'updBtn';
    btn.className = 'upd-btn';
    btn.style.display = 'none';
    btn.addEventListener('click', onBtnClick);
    bar.appendChild(btn);
    return btn;
  }

  function setBtn(visible, text, busy) {
    var b = ensureBtn();
    if (!b) return;
    b.style.display = visible ? '' : 'none';
    b.textContent = text;
    b.classList.toggle('busy', !!busy);
  }

  function onBtnClick() {
    var a = api();
    if (!a || !a.update_apply) return;
    setBtn(true, '正在更新…', true);
    a.update_apply().then(function (r) {
      if (!r || !r.success) {
        setBtn(true, '更新失败', false);
        if (typeof showToast === 'function') showToast(r && r.message ? r.message : '更新失败', 'error');
        return;
      }
      if (!r.updated) {
        setBtn(false, '', false);
        if (typeof showToast === 'function') showToast('已是最新版本', 'success');
        return;
      }
      setBtn(true, '已更新 · 请重启应用', false);
      if (typeof showToast === 'function') {
        showToast('已更新到 ' + (r.to_commit || '') + '，关闭应用重新打开即生效', 'success');
      }
      if (r.warning && typeof showToast === 'function') showToast(r.warning, 'warning');
    }).catch(function (e) {
      setBtn(true, '更新异常', false);
      if (typeof showToast === 'function') showToast('更新异常: ' + e, 'error');
    });
  }

  /* 轮询 get_state 时附带 update_hint(每 60s 检查一次按钮状态) */
  function pollHint() {
    var a = api();
    if (a && a.update_status) {
      a.update_status().then(function (st) {
        if (!st || !st.success) return;
        var last = (typeof window.__lastUpdState === 'undefined') ? null : window.__lastUpdState;
        if (st.updated_commit && st.updated_commit !== last) {
          window.__lastUpdState = st.updated_commit;
        }
      }).catch(function () {});
    }
    if (a && a.update_check) {
      a.update_check().then(function (r) {
        if (r && r.success && r.has_update) {
          setBtn(true, '有可用更新 · ' + (r.new_count || 0) + ' 个新提交', false);
        }
      }).catch(function () {});
    }
  }

  ready(function () {
    ensureBtn();
    setTimeout(pollHint, 25000);      // 启动 25s 后首次(错开 Python 侧 30s 检查)
    setInterval(pollHint, 600000);    // 之后每 10 分钟
  });
})();
