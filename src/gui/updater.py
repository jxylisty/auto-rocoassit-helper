# -*- coding: utf-8 -*-
"""自动更新器 (V4.4)

通道: GitHub 仓库 main 分支 (jxylisty/auto-rocoassit-helper)
策略:
  - 后台静默检查(启动 30s 后首次, 之后每 30 分钟): git fetch + 比对, 不影响运行
  - 用户点击"更新"才执行: 停任务 -> 保留 data/ -> git stash --include-untracked(排除 data) -> pull -> 恢复 -> stash drop
  - data/ 目录(配置/ROI/模板/词库/截图)永不覆盖
  - 失败自动回滚 git reset --hard 到更新前 commit
  - 仅源码运行模式可用(打包 exe 不提供)
"""
import json
import subprocess
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPDATE_STATE_FILE = Path(__file__).resolve().parent / "update_state.json"

# 更新时必须保护的用户数据(相对路径前缀)
PROTECTED_PREFIXES = ("data/", "data", ".git/")


class UpdateError(Exception):
    pass


def _run_git(args: list, timeout: int = 60) -> tuple:
    """在项目根执行 git 命令, 返回 (returncode, stdout+stderr)"""
    try:
        r = subprocess.run(
            ["git"] + args,
            cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return -1, "未找到 git, 请安装 Git for Windows"
    except subprocess.TimeoutExpired:
        return -2, "git 命令超时: " + " ".join(args)
    except Exception as e:
        return -3, str(e)


def _current_commit() -> str:
    rc, out = _run_git(["rev-parse", "HEAD"], 15)
    return out.strip() if rc == 0 else ""


def _remote_url() -> str:
    rc, out = _run_git(["remote", "get-url", "origin"], 15)
    return out.strip() if rc == 0 and out.strip() else ""


def _load_state() -> dict:
    try:
        return json.loads(UPDATE_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(**kwargs):
    try:
        st = _load_state()
        st.update(kwargs)
        UPDATE_STATE_FILE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def check_update() -> dict:
    """静默检查远程是否有新版本。绝不修改工作区。"""
    try:
        if not _remote_url():
            return {"success": False, "message": "未配置远程仓库, 自动更新不可用"}

        rc, out = _run_git(["fetch", "origin", "main", "--quiet"], 90)
        if rc != 0:
            return {"success": False, "message": "无法连接 GitHub(检查网络): " + out.strip()[:150]}

        rc, local = _run_git(["rev-parse", "HEAD"], 15)
        rc2, remote = _run_git(["rev-parse", "origin/main"], 15)
        if rc != 0 or rc2 != 0:
            return {"success": False, "message": "版本读取失败"}

        local, remote = local.strip(), remote.strip()
        has_update = (local != remote)

        info = {"success": True, "has_update": has_update,
                "local_commit": local[:8], "remote_commit": remote[:8]}
        if has_update:
            rc3, log = _run_git(["log", "--oneline", local + ".." + remote], 20)
            commits = [l.strip() for l in (log or "").splitlines() if l.strip()]
            info["new_commits"] = commits
            info["new_count"] = len(commits)
            _save_state(last_check=time.time(), remote_commit=remote)
        else:
            _save_state(last_check=time.time())
        return info
    except Exception as e:
        return {"success": False, "message": "检查异常: " + str(e)}


def _stash_protected() -> tuple:
    """把本地改动(除 data/ 外)暂存起来, 返回 (成功?, 说明)。
    用 pathspec 排除 data/: git stash push --include-untracked -- <paths>
    data/ 内的 settings.yaml 等运行配置不进 stash, 工作区原样保留。"""
    # 收集改动项
    rc, out = _run_git(["status", "--porcelain"], 30)
    if rc != 0:
        return False, "git status 失败: " + out[:120]

    tracked, untracked = [], []
    for line in (out or "").splitlines():
        if not line.strip():
            continue
        status, path = line[:2].strip(), line[3:].strip()
        if path.startswith(PROTECTED_PREFIXES):
            continue                      # data/ 与 .git 不动
        if status == "??":
            untracked.append(path)
        else:
            tracked.append(path)

    if not tracked and not untracked:
        return True, "clean"              # 工作区本来就干净(对非 data 而言)

    rc2, out2 = _run_git(["stash", "push", "--include-untracked", "-m", "auto-updater"] + tracked + untracked, 120)
    if rc2 != 0:
        return False, "stash 失败: " + out2[:150]
    return True, "stashed"


def _stash_restore() -> tuple:
    rc, out = _run_git(["stash", "list"], 15)
    if rc == 0 and out.strip().startswith("stash@{0}"):
        first = out.splitlines()[0]
        if "auto-updater" in first:
            rc3, out3 = _run_git(["stash", "pop"], 120)
            if rc3 != 0:
                # pop 冲突: 保留 stash 让用户手动处理, 不吞数据
                return False, "本地改动恢复有冲突, 已保留在 stash, 未丢失: " + out3[:120]
            _run_git(["stash", "drop"], 15)
            return True, "restored"
    return True, "nothing"


def apply_update(stop_tasks_fn=None) -> dict:
    """执行更新(仅用户主动点击时调用):
    停任务 -> stash(保护 data/) -> pull -> 恢复本地改动 -> 失败回滚"""
    before = _current_commit()
    if not before:
        return {"success": False, "message": "无法读取当前版本"}

    if stop_tasks_fn:
        try:
            stop_tasks_fn()
        except Exception:
            pass

    ok, msg = _stash_protected()
    if not ok:
        return {"success": False, "message": msg, "rolled_back": False}

    rc, out = _run_git(["pull", "origin", "main", "--ff-only", "--quiet"], 300)
    if rc != 0:
        # 回滚到更新前状态
        _run_git(["reset", "--hard", before], 60)
        _stash_restore()
        return {"success": False, "message": "拉取失败已回滚: " + out.strip()[:200], "rolled_back": True}

    after = _current_commit()
    if after == before:
        _stash_restore()
        return {"success": True, "updated": False, "message": "已是最新版本"}

    rok, rmsg = _stash_restore()
    _save_state(last_update=time.time(), updated_commit=after)

    result = {"success": True, "updated": True,
              "from_commit": before[:8], "to_commit": after[:8],
              "need_restart": True}
    if not rok:
        result["warning"] = rmsg
    return result


def updater_status() -> dict:
    st = _load_state()
    st["success"] = True
    st["available"] = bool(_remote_url())
    st["current_commit"] = _current_commit()[:8]
    return st


class AutoUpdater:
    """后台静默检查线程: 结果写状态文件并通过回调通知 bridge 弹提示"""

    def __init__(self, on_update_available=None, first_delay: float = 30.0, interval: float = 1800.0):
        self._on_update_available = on_update_available
        self._first_delay = first_delay
        self._interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._last_seen_remote = None

    def start(self):
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="auto-updater")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        self._stop.wait(self._first_delay)
        while not self._stop.is_set():
            try:
                r = check_update()
                if (r.get("success") and r.get("has_update")
                        and r.get("remote_commit") != self._last_seen_remote):
                    self._last_seen_remote = r.get("remote_commit")
                    if self._on_update_available:
                        try:
                            self._on_update_available(r)
                        except Exception:
                            pass
            except Exception:
                pass
            self._stop.wait(self._interval)
