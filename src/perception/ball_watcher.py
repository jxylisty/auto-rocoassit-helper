"""
战斗前咕噜球库存监视线程 (6 槽全识别 + 数量 OCR + 本地持久化)

设计原则(绝不拖慢丢球):
- 丢球循环 mouse_down(开始蓄力)后只 set 一个 Event,识别完全在独立守护线程里做
- 每次蓄力采样一帧: 等约 120ms 让"头像→球槽"UI 切换完成,抓帧+匹配+OCR 全在后台
- 丢球循环的 mouse_up 时机由蓄力时长决定,永远不等待本线程

识别内容:
- 6 个槽位(咕噜球1-6): 是否有球 + 球类型(多尺度模板匹配) + 库存数量(数字区域 OCR)
- 1 号位恒为当前使用的球: 连续无球 -> 自动停止丢球; 命中贵重球 -> 警告/停止
- 2-6 号位是背包信息展示,不参与停止判定

持久化: data/config/ball_inventory.json — 每次识别结果落盘,重启后 UI 仍显示上次库存

运行模式(ball_watch.json 的 "mode"):
- "log"  : 只记日志不干预丢球(默认,用于先验证识别准确率)
- "stop" : 空球/贵重球时实际停止丢球模式
"""
import json
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ROI_TEMPLATE_DIR = PROJECT_ROOT / "data" / "config" / "roi_templates"
REF_ICON_DIR = PROJECT_ROOT / "data" / "vision" / "ball_icons"
INGAME_TEMPLATE_DIR = PROJECT_ROOT / "data" / "vision" / "ball_templates"
CONFIG_PATH = PROJECT_ROOT / "data" / "config" / "ball_watch.json"
INVENTORY_PATH = PROJECT_ROOT / "data" / "config" / "ball_inventory.json"
BALLS_DATA = PROJECT_ROOT / "src" / "pvp" / "data" / "balls_data.json"

SAMPLE_DELAY = 0.2        # 蓄力开始后等待"头像→球槽"UI 切换的时长(秒); 太短会把精灵头像误识别成球
EMPTY_STOP_STREAK = 3     # 1号位连续多少个蓄力样本无球才判定"球已丢完"
EMPTY_SLOT_DISPLAY_STREAK = 2   # 显示层去抖: 连续多少次识别失败才把槽位显示为空(单次失败保留上次结果)
PRESENT_DISPLAY_STREAK = 2      # 显示层对称去抖: 从"空"变"有球"需连续命中该次数, 防头像/过渡帧误报
PROTECTED_WARN_COOLDOWN = 10.0  # 贵重球警告节流(秒)
COUNT_ROI_SPLIT = 0.55    # 槽位 ROI 下部(此比例以下)为数字区域
INGAME_DIGIT_CUT = 0.68   # 游戏内模板保留顶部比例(底部混着数量数字,会干扰匹配)
EDGE_TIE_EPSILON = 0.08    # 边缘决胜: 同色系对分数差小于此值才启用
CONFUSABLE_PAIRS = {        # 同色系/同构型难分对(球型): 用图案复杂度(边缘能量)决胜
    "100262": {"100290"},   # 美妙球 ↔ 奇趣球 (官方图标同为暖色系)
}
HIST_FULL_MIN = 0.30     # 颜色门第二通道: 全像素直方图相关系数下限(含暗色系)
HIST_MIN_CORREL = 0.25    # 颜色门: 区域与模板的色相直方图相关系数低于此值判为不同球
COLOR_SAT_MIN = 90        # 颜色门: 双方平均饱和度都低于此值时跳过颜色检查(灰白球无法按色相判断)
HIST_BINS = 30            # 色相直方图分箱(0-180)


def _edge_sig(gray) -> float:
    """边缘能量签名: 拉普拉斯绝对值均值/255。花纹球(奇趣球有星形图案) > 光滑球(美妙球)"""
    import cv2
    import numpy as np
    if gray is None or gray.size == 0:
        return 0.0
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    return float(np.abs(lap).mean() / 255.0)


def _hue_hist(bgr) -> tuple:
    """球体颜色签名 → (鲜艳直方图或None, 平均饱和度, 全像素直方图或None)。
    鲜艳掩膜(饱和>90且明度>80)防深色描边淹没主色; 全像素直方图保留暗红等低明度色,
    供颜色门第二通道使用(如奇趣球的暗红: 明度34饱和度15, 人眼可见但鲜艳掩膜会丢掉)"""
    import cv2
    import numpy as np
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat = hsv[..., 1].astype(np.float32)
    val = hsv[..., 2].astype(np.float32)
    hue = hsv[..., 0].astype(np.uint8)
    m = (sat > 90) & (val > 80)
    vivid = None
    if int(m.sum()) > 20:
        hist = cv2.calcHist([hue[m]], [0], None, [HIST_BINS], [0, 180])
        cv2.normalize(hist, hist)
        vivid = hist
    full = None
    if hue.size > 100:
        hist = cv2.calcHist([hue], [0], None, [HIST_BINS], [0, 180])
        cv2.normalize(hist, hist)
        full = hist
    sat_mean = float(sat[m].mean()) if int(m.sum()) > 20 else 0.0
    return vivid, sat_mean, full


def _default_config() -> dict:
    return {
        "mode": "log",              # log = 只记日志; stop = 实际停止丢球
        "present_threshold": 0.6,   # 模板匹配分数 >= 此值判定有球
        "protected_ids": [],        # 贵重球 id 列表, 留空则自动使用 quality>=5 的球
        "ocr_interval": 12,         # 数量 OCR 间隔(秒), 独立线程按此节奏识别保存的帧
        "prefer": "official",       # 模板优先级: official = 官方高清图标; ingame = 游戏内截图
        "active_balls": [],         # 实际存在的球 id 白名单(如 ["100002","100003","100255"]), 留空 = 全部 27 种
    }


class BallTemplateMatcher:
    """无线程的纯球型识别器(挂机引擎/数据统计复用 BallSlotWatcher 的匹配逻辑)"""

    def __init__(self, active_balls=None, prefer: str = "official"):
        self.refs = BallSlotWatcher._load_ref_templates(active_balls, prefer)
        self.present_threshold = 0.6

    def match(self, crop_gray, crop_bgr=None) -> tuple:
        """裁剪图 → (score, ball_id, ball_name)"""
        return self._match(crop_gray, crop_bgr)

    def match_frame_rect(self, frame, rect: tuple) -> dict:
        """整帧 + 相对矩形 → {present, score, ball_id, ball_name}"""
        import cv2
        h, w = frame.shape[:2]
        rx, ry, rw, rh = rect
        bgr = frame[int(ry * h):int((ry + rh) * h), int(rx * w):int((rx + rw) * w)]
        if bgr.size == 0:
            return {"present": False, "score": 0.0, "ball_id": None, "ball_name": None}
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        score, ball_id, ball_name = self._match(gray, bgr)
        present = score >= self.present_threshold
        return {"present": present, "score": round(score, 3),
                "ball_id": ball_id if present else None,
                "ball_name": ball_name if present else None}

    # 内部: 与 BallSlotWatcher._match_slot 同逻辑
    def _match(self, crop_gray, crop_bgr=None) -> tuple:
        import cv2
        ch, cw = crop_gray.shape
        if crop_bgr is None:
            crop_bgr = cv2.cvtColor(crop_gray, cv2.COLOR_GRAY2BGR)
        best = (0.0, None, None)
        best_loc = None        # best 对应的匹配位置
        fallback = (0.0, None, None)
        ref_best = {}          # ball_id -> (最高分, 模板, 匹配位置)
        ref_tpls = {bid: tpl for bid, _, tpl, _ in self.refs}
        for ball_id, name, tpl, ref_hsv in self.refs:
            for scale in (0.45, 0.55, 0.65, 0.75, 0.85, 0.95):
                tw = max(8, int(cw * scale))
                th = max(8, int(tpl.shape[0] * tw / tpl.shape[1]))
                if th > ch or tw > cw:
                    continue
                t = cv2.resize(tpl, (tw, th), interpolation=cv2.INTER_AREA)
                try:
                    res = cv2.matchTemplate(crop_gray, t, cv2.TM_CCOEFF_NORMED)
                except Exception:
                    continue
                if res.size == 0:
                    continue
                _, score, _, loc = cv2.minMaxLoc(res)
                if score > fallback[0]:
                    fallback = (float(score), ball_id, name)
                if score > ref_best.get(ball_id, (0.0, None, None))[0]:
                    ref_best[ball_id] = (float(score), t, loc)
                if score <= best[0]:
                    continue
                if ref_hsv is not None and ref_hsv[0] is not None:
                    mx, my = loc
                    region = crop_bgr[my:my + th, mx:mx + tw]
                    reg_vivid, reg_sat, reg_full = _hue_hist(region) if region.size else (None, 0.0, None)
                    if (reg_vivid is not None and ref_hsv[1] >= COLOR_SAT_MIN
                            and reg_sat >= COLOR_SAT_MIN
                            and cv2.compareHist(ref_hsv[0], reg_vivid, cv2.HISTCMP_CORREL) < HIST_MIN_CORREL):
                        continue
                    # 第二通道: 全像素直方图(含暗红等低明度色), 相关系数要求更高
                    if (reg_full is not None and ref_hsv[2] is not None
                            and cv2.compareHist(ref_hsv[2], reg_full, cv2.HISTCMP_CORREL) < HIST_FULL_MIN):
                        continue
                best = (float(score), ball_id, name)
                best_loc = loc
        # 边缘决胜: 同色系难分对分数接近时, 用图案复杂度(边缘能量)选更匹配的
        if best[0] > 0 and best[0] < 0.98 and best_loc is not None:
            pair = (CONFUSABLE_PAIRS.get(best[1])
                    or {k for k, v in CONFUSABLE_PAIRS.items() if best[1] in v})
            if pair:
                rival = next((pid for pid in pair
                              if pid in ref_best and abs(ref_best[pid][0] - best[0]) < EDGE_TIE_EPSILON), None)
                if rival:
                    b_score, b_tpl, b_loc = ref_best[best[1]]
                    mx, my = b_loc
                    th_, tw_ = b_tpl.shape
                    region = crop_bgr[my:my + th_, mx:mx + tw_]
                    e_reg = _edge_sig(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)) if region.size else None
                    e_best = _edge_sig(ref_tpls.get(best[1]))
                    e_rival = _edge_sig(ref_tpls.get(rival))
                    if (e_reg is not None
                            and abs(e_reg - e_rival) < abs(e_reg - e_best) - 0.004):
                        rival_name = next(n for bid, n, _, _ in self.refs if bid == rival)
                        return (ref_best[rival][0], rival, rival_name)
        return best if best[0] > 0 else fallback


class BallSlotWatcher:
    """咕噜球库存监视器(独立线程,蓄力事件驱动采样)"""

    def __init__(self, frame_provider=None, on_log=None):
        self.on_log = on_log or (lambda msg, level="info": print(f"[{level}] {msg}"))
        self.frame_provider = frame_provider
        cfg = self._load_config()
        self.mode = cfg["mode"]
        self.present_threshold = float(cfg["present_threshold"])
        self.protected_ids = set(cfg["protected_ids"]) or self._default_protected_ids()
        self.ocr_interval = float(cfg.get("ocr_interval", 12))   # 数量 OCR 间隔(秒)

        self.slot_rects = self._load_slot_rects()   # {槽位号: (rx,ry,rw,rh) 相对坐标}
        self.slot1_rect = self.slot_rects.get(1)
        active = set(cfg.get("active_balls") or [])
        self._matcher = BallTemplateMatcher(active or None, cfg.get("prefer", "official"))
        self.refs = self._matcher.refs
        self.enabled = bool(self.slot1_rect and self.refs)
        if not self.enabled:
            self.on_log("咕噜球监视未启用: 缺少 咕噜球1 ROI 或球图标模板", "info")

        self._thread = None
        self._charge_event = threading.Event()
        self._running = False
        self._stop_requested = False
        self._last_warn_at = 0.0
        self._count_readers = {}   # 槽位号 -> OcrNumberReader (懒加载)
        self._last_inventory_json = ""
        self._last_cap_warn = 0.0  # 截图失败警告节流

        # "先拍照后冲印": 采样线程只存帧, OCR 独立线程按间隔识别保存的帧
        self._latest_frame = None
        self._ocr_thread = None
        self._ocr_wake = threading.Event()
        self.real_throw_count = 0  # 由 1 号位数量下降差值累计的真实丢球数

        # 右下角常驻球通道(球型识别 + <999 数量监控; ROI 未框时自动禁用)
        self.corner_rect = self._load_corner_rect()
        self.corner = {"enabled": self.corner_rect is not None, "present": False,
                       "ball_id": None, "ball_name": None, "count": None, "score": 0.0}
        saved_corner = self._load_corner_state()
        if saved_corner and self.corner_rect is not None:
            saved_corner["enabled"] = True
            self.corner = saved_corner   # 重启回显上次右下角识别结果

        # 库存(持久化, 启动时读回上次识别结果供 UI 显示)
        self.inventory = self._load_inventory()
        self.updated_at = self._load_inventory_updated_at()
        self._slot_miss = [0] * 6   # 各槽位连续识别失败次数(显示层去抖)
        self._slot_hit = [0] * 6    # 各槽位连续识别命中次数(防头像误报: 空→有球需连续命中)

        # 运行统计(供 UI/日志)
        self.samples = 0
        self.empty_streak = 0
        self.last_ball_id = None
        self.last_ball_name = None
        self.last_score = 0.0
        self.last_sample_at = 0.0

    # ---------- 配置与资源加载 ----------

    @staticmethod
    def _load_config() -> dict:
        cfg = _default_config()
        try:
            if CONFIG_PATH.exists():
                cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
        return cfg

    @staticmethod
    def _default_protected_ids() -> set:
        """默认贵重球: balls_data 里 quality>=5 且 is_ball 的(国王球等)"""
        protected = set()
        try:
            balls = json.loads(BALLS_DATA.read_text(encoding="utf-8"))
            protected = {str(b["id"]) for b in balls if b.get("is_ball") and b.get("quality", 0) >= 5}
        except Exception:
            pass
        return protected

    @staticmethod
    def _load_slot_rects() -> dict:
        """从 ROI 模板文件里找 咕噜球1-6 的相对坐标"""
        rects = {}
        try:
            for f in ROI_TEMPLATE_DIR.glob("*.json"):
                data = json.loads(f.read_text(encoding="utf-8"))
                rois = data.get("rois", []) if isinstance(data, dict) else []
                for r in rois:
                    rid = str(r.get("id", "")).strip()
                    if rid.startswith("咕噜球"):
                        suffix = rid.replace("咕噜球", "")
                        if suffix.isdigit() and 1 <= int(suffix) <= 6 and int(suffix) not in rects:
                            rects[int(suffix)] = (r["rx"], r["ry"], r["rw"], r["rh"])
                if 1 in rects:
                    break
        except Exception:
            pass
        return rects

    @staticmethod
    def _load_postbattle_rects() -> dict:
        """战斗内丢球界面的球槽 ROI(id: 进入战斗后咕噜球1-6)"""
        rects = {}
        try:
            for f in ROI_TEMPLATE_DIR.glob("*.json"):
                data = json.loads(f.read_text(encoding="utf-8"))
                rois = data.get("rois", []) if isinstance(data, dict) else []
                for r in rois:
                    rid = str(r.get("id", "")).strip()
                    if rid.startswith("进入战斗后咕噜球"):
                        suffix = rid.replace("进入战斗后咕噜球", "")
                        if suffix.isdigit() and 1 <= int(suffix) <= 6 and int(suffix) not in rects:
                            rects[int(suffix)] = (r["rx"], r["ry"], r["rw"], r["rh"])
                if 1 in rects:
                    break
        except Exception:
            pass
        return rects

    @staticmethod
    def _load_corner_rect():
        """从 ROI 模板文件里找右下角常驻球图标区域(id: ball_corner / 右下角*)"""
        try:
            for f in ROI_TEMPLATE_DIR.glob("*.json"):
                data = json.loads(f.read_text(encoding="utf-8"))
                rois = data.get("rois", []) if isinstance(data, dict) else []
                for r in rois:
                    rid = str(r.get("id", "")).strip()
                    if rid == "ball_corner" or rid.startswith("右下角"):
                        return (r["rx"], r["ry"], r["rw"], r["rh"])
        except Exception:
            pass
        return None

    @staticmethod
    def _load_ref_templates(active_balls=None, prefer: str = "official") -> list:
        """加载球图标模板。返回 [(ball_id, name, gray_tpl, hue_hist元组)]
        active_balls: 实际存在的球 id 白名单, None/空 = 不过滤(噪音球会抢匹配, 建议配置)
        prefer: official = 官方高清图标优先; ingame = 游戏内截图优先"""
        refs = []
        seen = set()
        dirs = ((REF_ICON_DIR, INGAME_TEMPLATE_DIR) if prefer != "ingame"
                else (INGAME_TEMPLATE_DIR, REF_ICON_DIR))
        for d in dirs:
            if not d.exists():
                continue
            for f in sorted(d.glob("*.png")):
                try:
                    import cv2
                    import numpy as np
                    bgr = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8), cv2.IMREAD_COLOR)
                    if bgr is None or bgr.size == 0:
                        continue
                    if d is INGAME_TEMPLATE_DIR and bgr.shape[0] > bgr.shape[1] * 1.15:
                        bgr = bgr[:int(bgr.shape[0] * INGAME_DIGIT_CUT)]  # 裁掉底部数字区(仅限带数字的旧战中槽位模板)
                    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                    if gray.size == 0:
                        continue
                    # 颜色签名: 只统计饱和度足够的像素
                    ref_hsv = _hue_hist(bgr)
                    stem = f.stem
                    ball_id = stem.split("_", 1)[0]
                    name = stem.split("_", 1)[1] if "_" in stem else stem
                    if ball_id in seen:
                        continue  # 高优先目录的同 id 模板胜出
                    if active_balls and ball_id not in active_balls:
                        continue  # 不在游戏实际球池里的模板是纯噪音
                    seen.add(ball_id)
                    refs.append((ball_id, name, gray, ref_hsv))
                except Exception:
                    continue
        return refs

    # ---------- 库存持久化 ----------

    @staticmethod
    def _load_inventory() -> list:
        try:
            if INVENTORY_PATH.exists():
                data = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
                slots = data.get("slots")
                if isinstance(slots, list) and len(slots) == 6:
                    return slots
        except Exception:
            pass
        return [{"slot": i, "present": False, "ball_id": None,
                 "ball_name": None, "count": None, "score": 0.0} for i in range(1, 7)]

    @classmethod
    def _load_inventory_updated_at(cls) -> str:
        try:
            if INVENTORY_PATH.exists():
                return json.loads(INVENTORY_PATH.read_text(encoding="utf-8")).get("updated_at", "")
        except Exception:
            pass
        return ""

    @staticmethod
    def _load_corner_state() -> dict | None:
        try:
            if INVENTORY_PATH.exists():
                c = json.loads(INVENTORY_PATH.read_text(encoding="utf-8")).get("corner")
                if isinstance(c, dict):
                    return c
        except Exception:
            pass
        return None

    def _persist_inventory(self):
        payload = json.dumps({
            "updated_at": self.updated_at,
            "slots": self.inventory,
            "corner": self.corner,
        }, ensure_ascii=False, indent=1)
        if payload == self._last_inventory_json:
            return  # 内容没变不重复写盘
        self._last_inventory_json = payload
        try:
            INVENTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            INVENTORY_PATH.write_text(payload, encoding="utf-8")
        except Exception as e:
            self.on_log(f"库存持久化失败: {e}", "warning")

    # ---------- 采样与判定 ----------

    def _grab_frame(self):
        if self.frame_provider is None:
            return None
        try:
            result = self.frame_provider()
        except Exception:
            return None
        if isinstance(result, tuple):
            return result[1] if len(result) > 1 else None
        return result

    def _count_reader(self, slot: int, rect: tuple):
        """槽位数字区域的 OCR 读取器(懒加载缓存)"""
        if slot not in self._count_readers:
            from src.ocr.base import ROI
            from src.perception.ocr_reader import OcrNumberReader
            rx, ry, rw, rh = rect
            self._count_readers[slot] = OcrNumberReader(ROI(
                name=f"ball_slot_{slot}_count",
                left=rx,
                top=ry + rh * COUNT_ROI_SPLIT,
                width=rw,
                height=rh * (1 - COUNT_ROI_SPLIT),
            ), percent=False)
        return self._count_readers[slot]

    def _match_slot(self, crop_gray, crop_bgr=None) -> tuple:
        """槽位裁剪图 -> (best_score, ball_id, ball_name) 多尺度模板匹配 + 颜色门"""
        m = getattr(self, "_matcher", None)
        if m is None:
            m = BallTemplateMatcher.__new__(BallTemplateMatcher)
            m.refs = self.refs
            m.present_threshold = getattr(self, "present_threshold", 0.6)
        return m.match(crop_gray, crop_bgr)

    def _sample_once(self):
        """抓一帧,识别全部 6 个槽位(仅轻量模板匹配 ~40ms); 截图失败返回 None。
        数量 OCR 不在这里跑——帧被保存到 _latest_frame, 由独立 OCR 线程按间隔识别,"先拍照后冲印" """
        import cv2
        frame = self._grab_frame()
        if frame is None or frame.size == 0 or not self.slot_rects:
            return None
        self._latest_frame = frame   # 存帧供 OCR 线程异步识别(抓帧返回的是独立数组,不会被覆盖)
        newly_present = False
        results = [dict(s) for s in self.inventory]  # 兜底沿用上次
        h, w = frame.shape[:2]
        for slot, rect in sorted(self.slot_rects.items()):
            rx, ry, rw, rh = rect
            bgr_crop = frame[int(ry * h):int((ry + rh) * h), int(rx * w):int((rx + rw) * w)]
            if bgr_crop.size == 0:
                continue
            crop = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2GRAY)
            score, ball_id, ball_name = self._match_slot(crop, bgr_crop)
            present = score >= self.present_threshold
            results[slot - 1] = {
                "slot": slot, "present": present, "score": round(score, 3),
                "ball_id": ball_id if present else None,
                "ball_name": ball_name if present else None,
                "count": None,
            }
            if present and not self.inventory[slot - 1].get("present"):
                newly_present = True
        if newly_present:
            self._ocr_wake.set()   # 有槽位刚出现,让 OCR 线程尽快读一次数量
        return results

    # ---------- 守护线程 ----------

    def attach(self, on_stop_request):
        """启动监视线程; on_stop_request(reason) 由 AutoThrowBall 注入"""
        if not self.enabled or self._running:
            return False
        self._on_stop_request = on_stop_request
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="BallSlotWatcher")
        self._thread.start()
        self._ocr_thread = threading.Thread(target=self._ocr_loop, daemon=True, name="BallSlotOcr")
        self._ocr_thread.start()
        mode_txt = "只记录日志" if self.mode == "log" else "自动停止丢球"
        self.on_log(
            f"🎯 咕噜球库存监视已启动(6槽, {len(self.refs)} 个球模板, 模式: {mode_txt}, "
            f"数量OCR间隔 {self.ocr_interval:.0f}s)", "success")
        return True

    def notify_charging(self):
        """丢球循环在 mouse_down 后调用(非阻塞,仅设置事件)"""
        if self._running:
            self._charge_event.set()

    def reset_run(self):
        """用户手动启动新模式时重置判定状态(清除停止闩锁与空球连击)"""
        self._stop_requested = False
        self.empty_streak = 0
        self._slot_miss = [0] * 6
        self._slot_hit = [0] * 6
        self.real_throw_count = 0

    def request_stop(self):
        self._running = False
        self._charge_event.set()
        self._ocr_wake.set()

    def _request_throw_stop(self, reason: str):
        if self._stop_requested:
            return
        self._stop_requested = True
        try:
            self._on_stop_request(reason)
        except Exception:
            pass

    def _loop(self):
        while self._running:
            if not self._charge_event.wait(timeout=1.0):
                continue
            self._charge_event.clear()
            time.sleep(SAMPLE_DELAY)  # 等"头像→球槽"UI 切换完成(后台等待,不占丢球线程)

            results = self._sample_once()
            if results is None:
                # 截图失败(游戏未启动/最小化/窗口找不到), 节流警告避免刷屏
                now = time.time()
                if now - self._last_cap_warn > 10.0:
                    self._last_cap_warn = now
                    self.on_log("📷 [咕噜球监视] 采样失败: 无法截取游戏画面(窗口未找到或最小化?)", "warning")
                continue
            self.samples += 1
            self.last_sample_at = time.time()
            self.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")

            # 显示状态去抖: 可视化是给人看的, 单次识别失败(蓄力结束/UI切换帧)不清空上次结果。
            # 连续 EMPTY_SLOT_DISPLAY_STREAK 次失败才显示为空; 数量 OCR 偶发失败保留上次读数。
            # 注意: 下方空球停止判定用的是原始 results, 与显示层互不影响。
            merged = []
            for i, s in enumerate(results):
                prev = self.inventory[i] if i < len(self.inventory) else {}
                if s["present"]:
                    self._slot_miss[i] = 0
                    self._slot_hit[i] += 1
                    if s["count"] is None and prev.get("count") is not None:
                        s["count"] = prev["count"]
                    # 空→有球需连续命中 PRESENT_DISPLAY_STREAK 次(防精灵头像/过渡帧误报)
                    if prev.get("present") or self._slot_hit[i] >= PRESENT_DISPLAY_STREAK:
                        merged.append(s)
                    else:
                        merged.append(dict(prev))
                else:
                    self._slot_hit[i] = 0
                    self._slot_miss[i] += 1
                    if prev.get("present") and self._slot_miss[i] < EMPTY_SLOT_DISPLAY_STREAK:
                        merged.append(dict(prev))
                    else:
                        merged.append(s)
            self.inventory = merged
            self._persist_inventory()

            # 1 号位判定: 空球连击 / 贵重球保护 (用原始识别流)
            slot1 = results[0] if results else None
            if slot1:
                self.last_score = slot1["score"]
                if slot1["present"]:
                    self.empty_streak = 0
                    self.last_ball_id = slot1["ball_id"]
                    self.last_ball_name = slot1["ball_name"]
                    if slot1["ball_id"] in self.protected_ids:
                        now = time.time()
                        if now - self._last_warn_at > PROTECTED_WARN_COOLDOWN:
                            self._last_warn_at = now
                            cnt = f", 剩余 {slot1['count']}" if slot1.get("count") is not None else ""
                            self.on_log(
                                f"💎 [贵重球保护] 1号位当前是 {slot1['ball_name']}{cnt}"
                                f"(匹配度 {slot1['score']:.2f})", "warning")
                            if self.mode == "stop":
                                self._request_throw_stop(
                                    f"1号位是贵重球 {slot1['ball_name']}, 防止误丢已停止")
                else:
                    self.empty_streak += 1
                    if self.empty_streak >= EMPTY_STOP_STREAK:
                        self.on_log("🫙 [咕噜球监视] 1号位连续多个蓄力样本未识别到球, 判定球已丢完", "warning")
                        if self.mode == "stop":
                            self._request_throw_stop("1号位咕噜球已用完, 已自动停止丢球")
                        self.empty_streak = 0  # 已上报,重新累计

    # ---------- 数量 OCR 线程("先拍照后冲印") ----------

    def _ocr_loop(self):
        """独立线程按间隔识别采样线程保存的帧, 完全不占采样周期"""
        while self._running:
            self._ocr_wake.wait(timeout=self.ocr_interval)
            self._ocr_wake.clear()
            if not self._running:
                break
            try:
                self._ocr_pass()
            except Exception as e:
                self.on_log(f"[咕噜球监视] 数量 OCR 异常: {e}", "warning")

    def _ocr_pass(self):
        """对最近保存的帧跑一遍 6 槽数量识别"""
        frame = self._latest_frame
        if frame is None or frame.size == 0:
            return
        changed = False
        for slot in sorted(self.slot_rects.keys()):
            if not self.inventory[slot - 1].get("present"):
                continue
            try:
                r = self._count_reader(slot, self.slot_rects[slot]).read(frame)
                if r and r.value is not None:
                    self._apply_count(slot, int(r.value))
                    changed = True
            except Exception:
                continue

        # 右下角常驻球通道: 常驻可见不受蓄力限制,球型识别更稳;
        # 数量 >999 时游戏显示 999+(OCR 读出 999), 精确消耗仍以 1 号位槽位差值为主
        if self.corner_rect is not None:
            try:
                import cv2
                h, w = frame.shape[:2]
                rx, ry, rw, rh = self.corner_rect
                bgr_crop = frame[int(ry * h):int((ry + rh) * h), int(rx * w):int((rx + rw) * w)]
                if bgr_crop.size:
                    crop = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2GRAY)
                    score, ball_id, ball_name = self._match_slot(crop, bgr_crop)
                    present = score >= self.present_threshold
                    self.corner.update({
                        "present": present, "score": round(score, 3),
                        "ball_id": ball_id if present else None,
                        "ball_name": ball_name if present else None,
                    })
                    if present:
                        try:
                            from src.ocr.base import ROI
                            from src.perception.ocr_reader import OcrNumberReader
                            reader = OcrNumberReader(ROI(
                                name="ball_corner_count", left=rx, top=ry + rh * 0.5,
                                width=rw, height=rh * 0.5), percent=False)
                            r2 = reader.read(frame)
                            if r2 and r2.value is not None:
                                self.corner["count"] = int(r2.value)
                        except Exception:
                            pass
                        if (ball_id in self.protected_ids
                                and time.time() - self._last_warn_at > PROTECTED_WARN_COOLDOWN):
                            self._last_warn_at = time.time()
                            self.on_log(f"💎 [贵重球保护] 右下角当前球是 {ball_name}(常驻识别)", "warning")
            except Exception:
                pass
        if changed or self.corner_rect is not None:
            self._persist_inventory()

    def _apply_count(self, slot: int, value: int):
        """写入槽位数量; 1 号位数量下降的差值累计为真实丢球数"""
        entry = self.inventory[slot - 1]
        old = entry.get("count")
        entry["count"] = value
        if slot == 1 and old is not None and value < old:
            self.real_throw_count += old - value
            self.on_log(
                f"🏀 [真实丢球数] 1号位 {old} → {value}, 本轮实际丢球 {self.real_throw_count} 颗", "info")

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "samples": self.samples,
            "empty_streak": self.empty_streak,
            "last_ball_id": self.last_ball_id,
            "last_ball_name": self.last_ball_name,
            "last_score": round(self.last_score, 3),
            "updated_at": self.updated_at,
            "real_throw_count": self.real_throw_count,
            "corner": self.corner,
            "slots": self.inventory,
        }
