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

    // 2. 构造透明 Proxy 拦截所有 pywebview.api 方法调用
    const apiProxy = new Proxy({}, {
        get(target, propKey) {
            if (propKey in target) {
                return target[propKey];
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
        const wsHost = window.location.host || '127.0.0.1:17365';
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
