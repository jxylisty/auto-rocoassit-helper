"""AppBridge Mix-in —— 工具箱(外部工具进程管理)"""

import subprocess
import sys
import threading
from pathlib import Path
from src.gui.bridge_common import PROJECT_ROOT, SCREENSHOT_DIR, DEV_MODE, TOOLS


class ToolsMixin:

    # ========================================
    # 3. 工具箱 API
    # ========================================

    def tools_list(self) -> dict:
        items = []
        for t in TOOLS:
            # 用户版只保留辅助工具(连点器),标注/诊断类工具仅开发者模式可见
            if not DEV_MODE and t.get("category", "helper") != "helper":
                continue
            proc = self._tool_procs.get(t["id"])
            running = bool(proc and proc["proc"].poll() is None)
            if not running and proc:
                self._tool_procs.pop(t["id"], None)
            items.append({
                "id": t["id"],
                "name": t["name"],
                "desc": t["desc"],
                "gui": t["gui"],
                "category": t.get("category", "helper"),
                "tag": t.get("tag", "工具"),
                "running": running,
            })
        return {"success": True, "tools": items}

    def tool_start(self, tool_id: str) -> dict:
        tool = next((t for t in TOOLS if t["id"] == tool_id), None)
        if not tool:
            return {"success": False, "message": f"未知工具: {tool_id}"}
        if not DEV_MODE and tool.get("category", "helper") != "helper":
            return {"success": False, "message": f"{tool['name']} 仅开发者模式可用"}
        proc_info = self._tool_procs.get(tool_id)
        if proc_info and proc_info["proc"].poll() is None:
            return {"success": False, "message": f"{tool['name']} 已在运行"}

        # 按策略准备参数
        args: list[str] = []
        if tool["arg"] == "shot":
            shot = self.vision_save_shot()
            if not shot.get("success"):
                return {"success": False,
                        "message": f"自动截图失败,无法启动: {shot.get('message')}"}
            args.append(str(self._last_shot_path))
        elif tool["arg"] == "last":
            path = self._resolve_last_screenshot()
            if not path:
                # 尝试自动截一张
                shot = self.vision_save_shot()
                if shot.get("success"):
                    path = self._last_shot_path
            if not path or not path.exists():
                return {"success": False,
                        "message": "没有可用截图,请先在视觉调试台截图或保持游戏前台运行"}
            args.append(str(path))
            self._enqueue_log(f"{tool['name']} 使用截图: {path.name}", "info")

        script = PROJECT_ROOT / tool["script"]
        if not script.exists():
            return {"success": False, "message": f"脚本不存在: {script}"}

        cmd = [sys.executable, str(script)] + args
        try:
            if tool["gui"]:
                proc = subprocess.Popen(
                    cmd, cwd=str(PROJECT_ROOT),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                proc = subprocess.Popen(
                    cmd, cwd=str(PROJECT_ROOT),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                threading.Thread(target=self._pump_tool_output,
                                 args=(proc, tool["name"]), daemon=True).start()
        except Exception as e:
            self._enqueue_log(f"启动 {tool['name']} 失败: {e}", "error")
            return {"success": False, "message": str(e)}

        self._tool_procs[tool_id] = {"proc": proc, "name": tool["name"]}
        self._enqueue_log(f"已启动 {tool['name']} (PID {proc.pid})", "success")
        return {"success": True, "pid": proc.pid}

    def tool_stop(self, tool_id: str) -> dict:
        tool = next((t for t in TOOLS if t["id"] == tool_id), None)
        name = tool["name"] if tool else tool_id
        if tool_id not in self._tool_procs:
            return {"success": False, "message": f"{name} 未在运行"}
        self._kill_tool(tool_id)
        self._enqueue_log(f"已停止 {name}", "warning")
        return {"success": True}

    def _kill_tool(self, tool_id: str):
        info = self._tool_procs.pop(tool_id, None)
        if not info:
            return
        proc = info["proc"]
        if proc.poll() is None:
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                proc.terminate()

    def _pump_tool_output(self, proc: subprocess.Popen, name: str):
        """把 CLI 工具的 stdout 回流到日志"""
        try:
            for raw in iter(proc.stdout.readline, b""):
                if not raw:
                    break
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("gbk", errors="replace")
                text = text.rstrip()
                if text:
                    self._enqueue_log(f"[{name}] {text}", "info")
        except Exception:
            pass
        finally:
            code = proc.poll()
            self._enqueue_log(f"[{name}] 进程结束 (code {code})", "info")

    def _resolve_last_screenshot(self) -> Path | None:
        if self._last_shot_path and self._last_shot_path.exists():
            return self._last_shot_path
        if SCREENSHOT_DIR.exists():
            pngs = sorted(SCREENSHOT_DIR.glob("*.png"))
            if pngs:
                return pngs[-1]
        return None
