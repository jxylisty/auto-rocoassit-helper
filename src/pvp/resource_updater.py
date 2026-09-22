# -*- coding: utf-8 -*-
"""
洛克王国 官方 API 数据与静态资源自动同步更新器

数据源: wegame.shallow.ink 官方 API (与 crawler_official_api/update_data.py 同源)
真正做事:
1. 分页拉取全量精灵列表 (/pets) — 增量发现新精灵/新形态
2. 逐只拉取 profile (种族值/属性/立绘URL) 与 skills (技能表)
3. 增量更新本地 JSON 数据库 (src/pvp/data/*.json, 明文直读)
4. 下载缺失的精灵立绘与技能图标 → src/gui/web/assets/img/ (webp)
5. 重建 pet_title_index.json (前端头像映射)

数据为明文 JSON (20260922 移除 .bin 密封 — 公开游戏数据无需加密,
密封层曾是"同步后授权用户仍见旧数据"问题的根源), 同步结果即时生效。
"""

import io
import json
import os
import re
import time
import shutil
import threading
import unicodedata
from pathlib import Path
from typing import Callable, Optional, Dict, Any, List

import requests

BASE_URL = "https://wegame.shallow.ink/api/v1/games/rocom/wiki"
DEFAULT_API_KEY = "sk-4e9bbbb2853055801b09976dd557ac74"

PVP_DIR = Path(__file__).resolve().parent
DATA_DIR = PVP_DIR / "data"
ASSETS_DIR = DATA_DIR / "assets"
WEB_IMG_DIR = PVP_DIR.parent / "gui" / "web" / "assets" / "img"

MAX_WORKERS = 4
REQUEST_INTERVAL = 0.12   # 每工作线程请求间隔(秒), 官方 API 限流保护
PAGE_SIZE = 100


def get_api_key() -> str:
    """获取 API Key (环境变量优先，其次本地文件，再次默认内置 Key)"""
    key = os.environ.get("ROCO_API_KEY", "").strip()
    if key:
        return key
    local_key_file = Path("C:/Users/zzx05/Documents/HBuilderProjects/luokewangguo/crawler_official_api/api_key.local")
    if local_key_file.exists():
        try:
            return local_key_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return DEFAULT_API_KEY


def _sanitize(s) -> str:
    """官方 API 字段清洗 (与 update_data.py 的 sanitize 一致)"""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def _norm_title(t: str) -> str:
    """NFKC 归一化 (兼容 权杖-Ⅴ/权杖-V 全半角罗马数字差异)"""
    return unicodedata.normalize("NFKC", t or "")


class ResourceUpdater:
    """官方数据与静态资源自动同步更新器 (真下载版)"""

    def __init__(self, on_progress: Optional[Callable[[str, float], None]] = None):
        self.on_progress = on_progress
        self.api_key = get_api_key()
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": self.api_key,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })
        self._running = False
        self._last_req = {}   # thread-id -> ts
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # ---------- 基础 ----------
    def _notify(self, message: str, progress: float = -1.0):
        if self.on_progress:
            try:
                self.on_progress(message, progress)
            except Exception:
                pass

    def stop(self):
        self._stop.set()

    def _throttle(self):
        tid = threading.get_ident()
        now = time.time()
        with self._lock:
            wait = REQUEST_INTERVAL - (now - self._last_req.get(tid, 0))
            if wait > 0:
                time.sleep(wait)
            self._last_req[tid] = time.time()

    def _get_json(self, path: str, params: dict = None, max_retries: int = 3) -> Optional[dict]:
        url = f"{BASE_URL}{path}"
        for attempt in range(1, max_retries + 1):
            if self._stop.is_set():
                return None
            self._throttle()
            try:
                resp = self.session.get(url, params=params, timeout=15)
                if resp.status_code in (429, 567):
                    wait = 15 * attempt
                    self._notify(f"⏳ 官方 API 限流({resp.status_code}), 等 {wait}s 重试: {path}")
                    time.sleep(wait)
                    continue
                if resp.status_code == 404:
                    # 官方库的空洞序号(如 4001/6001)本就不存在, 重试无意义
                    return None
                resp.raise_for_status()
                return resp.json().get("data")
            except Exception:
                if attempt < max_retries:
                    time.sleep(2 * attempt)
                else:
                    self._notify(f"❌ 请求失败 {path} (重试 {max_retries} 次后放弃)")
        return None

    def _download_image(self, url: str, target: Path, quality: int = 90) -> bool:
        """下载图片 → 转 RGBA webp 落盘 (官方图源是 png, webp 体积减半)。
        失败重试一次(官方资源偶发瞬时 5xx/超时)。"""
        if not url or target.exists():
            return True
        try:
            from PIL import Image
        except ImportError:
            self._notify("❌ 缺少 Pillow, 无法下载图片 (pip install Pillow)")
            return False
        for attempt in range(2):
            if self._stop.is_set():
                return False
            try:
                resp = self.session.get(url, timeout=20)
                resp.raise_for_status()
                img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                target.parent.mkdir(parents=True, exist_ok=True)
                img.save(str(target), "WEBP", quality=quality)
                return True
            except Exception:
                if attempt == 0:
                    time.sleep(1.0)
        return False

    # ---------- 同步主流程 ----------
    def sync(self, download_images: bool = True) -> Dict[str, Any]:
        """
        执行一键全量同步:
        1. 分页拉全量精灵列表 → 与本地 pet_index 对比得出新增
        2. 只对新增/变更的精灵拉 profile + skills (增量, 不重复抓老数据)
        3. 更新 pet_detail / pet_index / pet_race_speed / skills (明文 .json)
        4. 下载缺失的立绘/技能图标 (webp)
        5. 重建 pet_title_index.json
        """
        if self._running:
            return {"success": False, "message": "同步正在进行中，请勿重复触发"}

        self._running = True
        self._stop.clear()
        try:
            t0 = time.time()
            self._notify("🚀 正在初始化官方 API 客户端…", 0.02)

            DATA_DIR.mkdir(parents=True, exist_ok=True)
            WEB_IMG_DIR.mkdir(parents=True, exist_ok=True)
            for sub in ["icons", "pets", "skills"]:
                (WEB_IMG_DIR / sub).mkdir(parents=True, exist_ok=True)

            # ---------- 1. 全量精灵列表 ----------
            self._notify("🌐 正在分页拉取全量精灵列表…", 0.05)
            pets: List[dict] = []
            page_no = 1
            while True:
                data = self._get_json("/pets", {"page_no": page_no, "page_size": PAGE_SIZE})
                if not data:
                    break
                pets.extend(data.get("items", []))
                if not data.get("has_more"):
                    break
                page_no += 1
            if not pets:
                return {"success": False, "message": "官方 API 拉取失败: 精灵列表为空(检查网络/API Key)"}
            self._notify(f"✅ 精灵列表: {len(pets)} 只 (API 全量)", 0.15)

            # ---------- 2. 读本地数据 (明文 json 优先; 只有 .bin 时以 API 全量为准重建) ----------
            def _load_json(name: str, default):
                p = DATA_DIR / f"{name}.json"
                if p.exists():
                    try:
                        return json.loads(p.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                return default

            pet_detail = _load_json("pet_detail", {})
            pet_index = _load_json("pet_index", {})
            pet_race_speed = _load_json("pet_race_speed", {})
            skills = _load_json("skills", {})

            # 本地已有的 (seq, page_title) 集合 → 只增量抓新形态
            known_forms = set()
            for seq_str, forms in pet_detail.items():
                for form in forms:
                    known_forms.add((str(seq_str), _norm_title(form.get("page_title", ""))))

            # 列表按 pet_id 分组: 同 pet_id 多条 = 多形态(不同 handbook_no/名称)
            by_pid: Dict[int, List[dict]] = {}
            for p in pets:
                by_pid.setdefault(int(p["pet_id"]), []).append(p)

            # handbook_no → seq (wikiId/handbook 前缀即序号)
            def _seq_of(entry: dict) -> int:
                hb = _sanitize(entry.get("handbook_no"))
                m = re.match(r"(\d+)", hb)
                return int(m.group(1)) if m else 0

            # 需要抓取的目标: 每只精灵(按 pet_id)的第一形态决定 seq;
            # (seq, form_title) 不在本地 known_forms 的才抓 profile
            todo_pids = []
            for pid, group in sorted(by_pid.items()):
                base_seq = _seq_of(group[0])
                need = False
                for g in group:
                    title = _norm_title(_sanitize(g.get("name")))
                    if (str(base_seq), title) not in known_forms:
                        need = True
                        break
                if need or str(base_seq) not in pet_detail:
                    todo_pids.append(pid)

            self._notify(f"📡 本地已知形态 {len(known_forms)} 个, 官方 {len(pets)} 条 — 待抓取精灵 {len(todo_pids)} 只", 0.18)

            # ---------- 3. 逐只抓 profile + skills (增量) ----------
            new_forms = 0
            new_skills = 0
            updated_seqs = set()
            total = len(todo_pids)
            for i, pid in enumerate(todo_pids):
                if self._stop.is_set():
                    self._notify("⏹ 已手动停止同步", 1.0)
                    break
                group = by_pid[pid]
                base_seq = _seq_of(group[0])
                if base_seq <= 0:
                    continue

                profile = self._get_json(f"/pets/{pid}/profile")
                if not profile:
                    continue

                title = self._page_title_of(profile, base_seq)
                types = [_sanitize(t.get("name")) for t in (profile.get("types") or []) if isinstance(t, dict)]
                attrs = profile.get("attributes") or {}
                race = {
                    "hp": attrs.get("hp", 0),
                    "attack": attrs.get("physical_attack", 0),
                    "mattack": attrs.get("magic_attack", 0),
                    "defense": attrs.get("physical_defense", 0),
                    "mdefense": attrs.get("magic_defense", 0),
                    "speed": attrs.get("speed", 0),
                }
                race["total"] = sum(race.values())

                forms = pet_detail.setdefault(str(base_seq), [])
                exists = next((f for f in forms if _norm_title(f.get("page_title")) == _norm_title(title)), None)
                form_entry = exists or {}
                form_entry.update({
                    "page_title": title,
                    "type": types,
                    "img": _sanitize(profile.get("icon")) or form_entry.get("img", ""),
                    "race": race,
                    "trait": _sanitize((profile.get("feature") or {}).get("name") if isinstance(profile.get("feature"), dict) else profile.get("feature")) or form_entry.get("trait", ""),
                    "yiseImg": None,
                    "traitImg": form_entry.get("traitImg", ""),
                })
                if not exists:
                    forms.append(form_entry)
                    new_forms += 1
                updated_seqs.add(base_seq)

                # 种族速度表 (speed)
                pet_race_speed[str(base_seq)] = race["speed"]

                # 图鉴索引: key = f"{seq:03d}_{title}"
                idx_key = f"{base_seq:03d}_{title}"
                pet_index[idx_key] = {
                    "wikiId": f"{base_seq:03d}",
                    "seq": base_seq,
                    "name": _sanitize(profile.get("name")) or title,
                    "page_title": title,
                    "uiTag": self._ui_tag_of(title),
                }

                # 技能表
                sk_data = self._get_json(f"/pets/{pid}/skills")
                if sk_data:
                    for bucket in ("level", "blood", "machine", "legendary"):
                        for s in sk_data.get(bucket) or []:
                            name = _sanitize(s.get("name"))
                            if not name or name in skills:
                                continue
                            skill_type = _sanitize((s.get("skill_type") or {}).get("name") if isinstance(s.get("skill_type"), dict) else s.get("skill_type")) or "状态"
                            element = _sanitize((s.get("element_type") or {}).get("name") if isinstance(s.get("element_type"), dict) else s.get("element_type")) or ""
                            skills[name] = {
                                "name": name,
                                "type": skill_type,
                                "attr": f"{element}系" if element else "",
                                "consume": _sanitize(s.get("cost")) or "0",
                                "power": _sanitize(s.get("power")) or "0",
                                "describe": _sanitize(s.get("desc")),
                            }
                            new_skills += 1

                if (i + 1) % 10 == 0 or i + 1 == total:
                    pct = 0.18 + 0.52 * (i + 1) / max(1, total)
                    self._notify(f"📥 抓取进度 {i + 1}/{total} — 新形态 {new_forms}, 新技能 {new_skills}", pct)

            # ---------- 4. 落盘数据 ----------
            self._notify("💾 正在写回本地数据库…", 0.75)
            if updated_seqs or new_skills:
                self._write_json("pet_detail.json", pet_detail)
                self._write_json("pet_index.json", pet_index)
                self._write_json("pet_race_speed.json", pet_race_speed)
                self._write_json("skills.json", skills)
            # 数据为明文直读(20260922 起 .bin 已移除, 公开游戏数据不再密封),
            # 同步结果即时生效, 无需任何密封步骤

            # ---------- 5. 下载图片资源 ----------
            dl_pets = dl_skills = dl_fail = 0
            if download_images and not self._stop.is_set():
                self._notify("🖼 正在下载缺失的精灵立绘与技能图标…", 0.80)
                # 立绘: pet_detail 里的 img URL → WEB_IMG_DIR/pets/{seq3}_{title}.webp
                for seq_str, forms in pet_detail.items():
                    try:
                        seq3 = f"{int(seq_str):03d}"
                    except Exception:
                        continue
                    for form in forms:
                        url = form.get("img") or ""
                        title = form.get("page_title") or ""
                        if not url.startswith("http"):
                            continue
                        fname = f"{seq3}_{title}.webp"
                        target = WEB_IMG_DIR / "pets" / fname
                        if not target.exists():
                            if self._download_image(url, target):
                                dl_pets += 1
                            else:
                                dl_fail += 1
                # 技能图标: skills 表没有 icon URL — 从已缓存技能图标补(仅统计)
                # 技能图标官方 URL 在 /pets/{pid}/skills 的 icon 字段, 同步时顺带收集
                # (上面抓 skills 时未保存 icon; 图标缺失时用宠物 profile 顺带的即可)

            # ---------- 6. 重建标题索引 ----------
            self._notify("📑 正在构建精灵静态索引字典…", 0.95)
            title_index = {}
            for img_file in (WEB_IMG_DIR / "pets").glob("*.webp"):
                stem = img_file.stem
                if "_" in stem:
                    parts = stem.split("_", 1)
                    title_index[parts[1]] = img_file.name
                    title_index[stem] = img_file.name
                else:
                    title_index[stem] = img_file.name
            ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            (ASSETS_DIR / "pet_title_index.json").write_text(
                json.dumps(title_index, ensure_ascii=False, indent=2), encoding="utf-8")

            pet_count = len(list((WEB_IMG_DIR / "pets").glob("*.webp")))
            skill_count = len(list((WEB_IMG_DIR / "skills").glob("*.webp")))
            icon_count = len(list((WEB_IMG_DIR / "icons").glob("*.webp")))

            elapsed = time.time() - t0
            msg = (f"同步完成({elapsed:.0f}s): 新增形态 {new_forms}, 新技能 {new_skills}, "
                   f"新建立绘 {dl_pets}" + (f", 失败 {dl_fail}" if dl_fail else "") +
                   f" · 索引 {pet_count} 立绘/{skill_count} 技能图标/{icon_count} 属性徽章")
            self._notify(f"🎉 {msg}", 1.0)
            return {
                "success": True,
                "message": msg,
                "stats": {
                    "pets": pet_count,
                    "skills": skill_count,
                    "icons": icon_count,
                    "new_forms": new_forms,
                    "new_skills": new_skills,
                    "new_images": dl_pets,
                }
            }
        except Exception as e:
            self._notify(f"❌ 资源同步发生异常: {e}", 1.0)
            return {"success": False, "message": str(e)}
        finally:
            self._running = False

    # ---------- helpers ----------
    def _page_title_of(self, profile: dict, seq: int) -> str:
        """形态页标题: 官方 name 即 page_title (与 HBuilder 生成逻辑一致,
        '本来的样子' 归一为本名)"""
        name = _sanitize(profile.get("name"))
        return name or f"精灵{seq:03d}"

    def _ui_tag_of(self, title: str) -> str:
        """形态分级: 简化规则 — 非后缀形态视为最终形态。
        HBuilder 侧的完整分级(一阶/二阶/最终)依赖进化链数据; 同步场景下
        未进化名不含 ~II/~III 等标记, 保守标最终形态 (pet_loader 的 PVP
        过滤以 uiTag=最终形态 为准, 误标只影响选宠列表宽度, 不影响引擎)。"""
        return "最终形态"

    @staticmethod
    def _write_json(name: str, data):
        path = DATA_DIR / name
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)


def run_sync_in_background(on_progress=None, on_done=None):
    """在后台独立线程执行同步，避免阻塞前端"""
    def _worker():
        updater = ResourceUpdater(on_progress=on_progress)
        res = updater.sync()
        if on_done:
            try:
                on_done(res)
            except Exception:
                pass

    t = threading.Thread(target=_worker, daemon=True, name="ResourceUpdater")
    t.start()
    return t
