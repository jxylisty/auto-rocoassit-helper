"""AppBridge Mix-in —— 账户登录 / 卡密验证 / 在线更新"""

import json
import threading
from src.gui.updater import AutoUpdater, check_update, apply_update, updater_status
import time
from src.gui.bridge_common import DEV_MODE


class AuthUpdateMixin:


    # ---------- 账户登录/卡密验证 ----------
    def _auth_gate(self) -> dict | None:
        """付费功能统一鉴权守卫。返回 None=放行; dict=拒绝响应。
        开发者版放行; 用户版需已激活且未过期 + 核心数据密钥就绪。
        (UI 锁幕只是引导, 这里是硬闸)"""
        if DEV_MODE:
            return None
        try:
            from src.gui import auth
            st = auth.status()
            if not st.get("authorized"):
                return {"ok": False, "auth_required": True,
                        "message": "该功能需要激活卡密后使用(侧边栏点击激活)"}
            from src.pvp import seadata
            if seadata.has_sealed_data() and not seadata.is_ready():
                return {"ok": False, "auth_required": True,
                        "message": "核心数据未就绪, 请联网启动一次完成授权校验"}
            return None
        except Exception:
            return {"ok": False, "auth_required": True, "message": "登录态检查失败"}

    def auth_status(self) -> dict:
        from src.gui import auth
        st = auth.status()
        st["dev_mode"] = DEV_MODE
        if DEV_MODE:
            st["authorized"] = True      # 开发者版放行, 不锁任何功能
            st["nickname"] = st.get("nickname") or "开发者"
        return st

    def auth_activate(self, code) -> dict:
        if DEV_MODE:
            return {"ok": True, "message": "开发者模式无需激活", "dev": True}
        from src.gui import auth
        res = auth.activate(str(code or ""))
        if res.get("ok"):
            self._push_auth_state()
            self._enqueue_log(f"激活成功: {res.get('nickname')}", "success")
        else:
            self._enqueue_log(f"激活失败: {res.get('message')}", "error")
        return res

    def auth_logout(self) -> dict:
        from src.gui import auth
        auth.deactivate()
        self._push_auth_state()
        self._enqueue_log("已退出登录", "info")
        return {"ok": True}

    def auth_verify_remote(self) -> dict:
        """启动静默校验(后台线程调), 结果推送前端"""
        if DEV_MODE:
            return self.auth_status()
        from src.gui import auth
        res = auth.verify_remote()
        self._push_auth_state()
        if res.get("authorized"):
            days = res.get("expires_at")
            if days:
                left = max(0, (int(days) - int(time.time() * 1000)) // 86400000)
                if left <= 3:
                    self._enqueue_log(f"卡密剩余 {left} 天, 请及时续期", "warning")
        elif res.get("reason") == "revoked":
            self._enqueue_log("卡密已被吊销, 已退出登录", "error")
            self._on_auth_denied("revoked")
        elif res.get("reason") == "expired":
            self._on_auth_denied("expired")
        return res

    def _push_auth_state(self):
        """登录态推送到前端(侧边栏登录区刷新)"""
        if self._window is None:
            return
        try:
            st = self.auth_status()
            self._window.evaluate_js(
                "window.onAuthUpdate && window.onAuthUpdate("
                + json.dumps(st, ensure_ascii=False) + ")")
        except Exception:
            pass

    def start_auth_verify(self):
        """启动静默校验 + 运行中心跳(每 15 分钟一次, 吊销/过期实时生效)"""
        def _job():
            time.sleep(2.5)
            while True:
                try:
                    self.auth_verify_remote()
                except Exception:
                    pass
                self._stop_event.wait(900)  # 15 分钟
        threading.Thread(target=_job, daemon=True, name="AuthVerify").start()

    def _on_auth_denied(self, reason: str):
        """云端复验失败 (吊销/过期): 停掉全部任务并提示"""
        try:
            self.engine.stop(f"授权{ {'revoked': '已吊销', 'expired': '已过期'}.get(reason, '失效') }")
        except Exception:
            pass
        try:
            self.daily_stop()
        except Exception:
            pass
        try:
            self._pvp_running = False
        except Exception:
            pass
        self._enqueue_log("授权已失效，相关功能已停止。请重新激活或续费。", "warning")

    def start_state_push(self):
        t = threading.Thread(target=self._state_push_loop, daemon=True)
        t.start()

    # ========================================
    # 自动更新 (GitHub main 分支通道)
    # ========================================
    def _notify_update_available(self, info: dict):
        """后台检查发现新版本: 记录状态, 前端轮询 get_state 时顺带带上"""
        try:
            self._update_hint = {
                "has_update": True,
                "remote_commit": info.get("remote_commit", ""),
                "new_count": info.get("new_count", 0),
                "new_commits": (info.get("new_commits") or [])[:8],
            }
        except Exception:
            pass

    _update_hint = None

    def update_check(self) -> dict:
        """立即检查更新(前端点击触发)"""
        return check_update()

    def update_apply(self) -> dict:
        """执行更新: 自动停止所有键鼠任务 -> 保护 data/ -> git pull -> 可回滚"""
        return apply_update(stop_tasks_fn=self.stop_all)

    def update_status(self) -> dict:
        return updater_status()
