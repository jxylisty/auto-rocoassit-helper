/**
 * 洛克王国 PVP 助手 - Web 前后端解耦透明适配器 (Web Adapter)
 * 
 * 作用:
 * 1. 当在独立浏览器 (Edge / Chrome / Tauri) 中运行时，模拟注入 window.pywebview.api 对象。
 * 2. 通过 Proxy 将所有 pywebview.api.xxx(...args) 调用自动转发到后端的 HTTP RPC (/api/rpc/xxx)。
 * 3. 建立 WebSocket 长连接 (/ws)，接收后端实时推送的日志 (addLog)、PVP 战况快照和控制指令。
 * 4. 零侵入: 若在原生 pywebview 环境中运行，本脚本自动静默旁路，不干扰任何原有逻辑。
 */
(function () {
    // 1. 如果已存在原生 pywebview，静默退出
    if (window.pywebview && window.pywebview.api) {
        return;
    }

    const API_BASE = window.location.origin.startsWith('http') 
        ? window.location.origin 
        : 'http://127.0.0.1:17365';

    console.info(`[WebAdapter] 激活前后端解耦模式 (服务端: ${API_BASE})`);

    // 弹窗窗口单例管理 (浏览器模式下模拟桌面悬浮窗)
    const subWindows = {};

    function isTauriEnv() {
        return typeof window !== 'undefined' && (!!window.__TAURI__ || !!window.__TAURI_INTERNALS__);
    }

    async function tauriInvoke(cmd, args = {}) {
        if (window.__TAURI__ && window.__TAURI__.core && typeof window.__TAURI__.core.invoke === 'function') {
            return window.__TAURI__.core.invoke(cmd, args);
        }
        if (window.__TAURI__ && typeof window.__TAURI__.invoke === 'function') {
            return window.__TAURI__.invoke(cmd, args);
        }
        if (window.__TAURI_INTERNALS__ && typeof window.__TAURI_INTERNALS__.invoke === 'function') {
            return window.__TAURI_INTERNALS__.invoke(cmd, args);
        }
        throw new Error("Tauri API not found");
    }

    function toggleSubWindow(key, url, width, height) {
        try {
            if (subWindows[key] && !subWindows[key].closed) {
                subWindows[key].close();
                subWindows[key] = null;
                return { success: true, action: "closed" };
            }
            const left = Math.max(20, window.screen.availWidth - width - 30);
            const top = Math.max(40, Math.floor((window.screen.availHeight - height) / 2));
            const features = `width=${width},height=${height},left=${left},top=${top},menubar=no,toolbar=no,location=no,status=no,resizable=yes`;
            const win = window.open(url, key, features);
            if (win) {
                subWindows[key] = win;
                win.focus();
                return { success: true, action: "opened" };
            }
            console.warn(`[WebAdapter] 弹窗被浏览器拦截，请在浏览器地址栏允许弹出窗口: ${url}`);
            return { success: false, message: "弹窗被拦截，请允许弹出窗口" };
        } catch (e) {
            console.error(`[WebAdapter] 打开弹窗失败:`, e);
            return { success: false, message: String(e) };
        }
    }

    // 2. 构造透明 Proxy 拦截所有 pywebview.api 方法调用
    const apiProxy = new Proxy({}, {
        get(target, propKey) {
            if (propKey in target) {
                return target[propKey];
            }
            // 客户端窗口行为拦截 (Tauri 模式调用原生置顶窗口，浏览器模式模拟多窗口)
            if (propKey === "widget_toggle") {
                return async function () {
                    if (isTauriEnv()) {
                        try {
                            const visible = await tauriInvoke('toggle_subwindow', { label: 'float' });
                            return { success: true, visible };
                        } catch (err) {
                            console.warn('[WebAdapter] Tauri 原生悬浮窗调用失败，回退到浏览器窗口:', err);
                        }
                    }
                    toggleSubWindow("FloatConsoleWindow", `${API_BASE}/float`, 380, 520);
                    return { success: true };
                };
            }
            if (propKey === "pvp_float_toggle") {
                return async function () {
                    if (isTauriEnv()) {
                        try {
                            const visible = await tauriInvoke('toggle_subwindow', { label: 'pvp_float' });
                            return { success: true, visible };
                        } catch (err) {
                            console.warn('[WebAdapter] Tauri 原生 PVP 悬浮窗调用失败，回退到浏览器窗口:', err);
                        }
                    }
                    toggleSubWindow("PvpFloatWindow", `${API_BASE}/pvp_float`, 420, 620);
                    return { success: true };
                };
            }
            if (propKey === "ai_widget_toggle") {
                return async function () {
                    if (isTauriEnv()) {
                        try {
                            const visible = await tauriInvoke('toggle_subwindow', { label: 'float' });
                            return { success: true, visible };
                        } catch (err) {
                            console.warn('[WebAdapter] Tauri 原生悬浮窗调用失败，回退到浏览器窗口:', err);
                        }
                    }
                    toggleSubWindow("AiFloatWindow", `${API_BASE}/float`, 360, 500);
                    return { success: true };
                };
            }
            if (propKey === "window_close" || propKey === "close_window") {
                return async function () {
                    if (isTauriEnv()) {
                        try {
                            await tauriInvoke('close_app');
                            return { success: true };
                        } catch (err) {
                            console.warn('[WebAdapter] Tauri close_app 失败:', err);
                        }
                    }
                    window.close();
                    return { success: true };
                };
            }
            if (propKey === "minimize_window" || propKey === "window_minimize") {
                return async function () {
                    if (isTauriEnv()) {
                        try {
                            await tauriInvoke('minimize_window', { label: 'main' });
                            return { success: true };
                        } catch (err) {
                            console.warn('[WebAdapter] Tauri minimize_window 失败:', err);
                        }
                    }
                    return { success: true };
                };
            }

            // 返回一个异步函数
            return async function (...args) {
                try {
                    const response = await fetch(`${API_BASE}/api/rpc/${String(propKey)}`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Accept': 'application/json'
                        },
                        body: JSON.stringify({ args: args })
                    });

                    if (!response.ok) {
                        const errText = await response.text();
                        console.error(`[WebAdapter] RPC 调用失败: ${String(propKey)}`, response.status, errText);
                        return { success: false, message: `HTTP ${response.status}: ${errText}` };
                    }

                    const result = await response.json();
                    return result;
                } catch (err) {
                    console.error(`[WebAdapter] RPC 网络异常: ${String(propKey)}`, err);
                    return { success: false, message: String(err) };
                }
            };
        }
    });

    window.pywebview = {
        api: apiProxy
    };

    // 3. 派发 pywebviewready 事件，通知业务 JS 就绪
    function notifyReady() {
        try {
            window.dispatchEvent(new CustomEvent('pywebviewready'));
        } catch (e) {
            const evt = document.createEvent('Event');
            evt.initEvent('pywebviewready', true, true);
            window.dispatchEvent(evt);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', notifyReady);
    } else {
        setTimeout(notifyReady, 0);
    }

    // 4. WebSocket 实时双向流: 替代原 evaluate_js 推送日志与战况
    let ws = null;
    let wsReconnectTimer = null;

    function connectWs() {
        const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsHost = (window.location.protocol.startsWith('http') && window.location.host)
            ? window.location.host
            : '127.0.0.1:17365';
        const wsUrl = `${wsProto}//${wsHost}/ws`;

        try {
            ws = new WebSocket(wsUrl);
        } catch (e) {
            scheduleReconnect();
            return;
        }

        ws.onopen = function () {
            console.info('[WebAdapter] WebSocket 实时通道已建立');
            if (wsReconnectTimer) {
                clearTimeout(wsReconnectTimer);
                wsReconnectTimer = null;
            }
        };

        ws.onmessage = function (event) {
            try {
                const data = JSON.parse(event.data);
                handleServerPush(data);
            } catch (e) {
                console.warn('[WebAdapter] 解析推送消息失败:', event.data, e);
            }
        };

        ws.onclose = function () {
            scheduleReconnect();
        };

        ws.onerror = function () {
            try { ws.close(); } catch (_) {}
        };
    }

    function scheduleReconnect() {
        if (!wsReconnectTimer) {
            wsReconnectTimer = setTimeout(connectWs, 2000);
        }
    }

    function handleServerPush(msg) {
        if (!msg || !msg.type) return;

        switch (msg.type) {
            case 'log':
                if (typeof window.addLog === 'function') {
                    window.addLog(msg.message, msg.level || 'info');
                }
                break;
            case 'eval':
                if (msg.js) {
                    try {
                        // 兼容后端原 evaluate_js 行为
                        (new Function(msg.js))();
                    } catch (e) {
                        console.error('[WebAdapter] 执行推送 JS 出错:', msg.js, e);
                    }
                }
                break;
            case 'state':
                if (typeof window.applyState === 'function') {
                    window.applyState(msg.state);
                }
                break;
            case 'pvp_update':
                if (typeof window.applyPvpUpdate === 'function') {
                    window.applyPvpUpdate(msg.data);
                }
                break;
            default:
                // 自定义事件广播
                window.dispatchEvent(new CustomEvent('server_' + msg.type, { detail: msg.data }));
                break;
        }
    }

    // 启动 WebSocket 连接
    connectWs();
})();
