# -*- coding: utf-8 -*-
"""
PVP 精灵识别模板库 (生产版)
==============================================================
定位: 可复用的「PVP 截图 → 精灵名」识别服务, 供对战助手等外部项目调用。

核心思路 (基于 LOO 评估结论, 见 PVP_RECOGNITION.md):
  1. OCR 主链: PVP 界面左侧有「精灵名 + 等级」, 未改名精灵 OCR 直接命中 (~100%)
  2. 图像 fallback: 改名精灵 OCR 失效 → 用 PVP 同域模板库做 ORB 图像识别
     (wiki/图鉴头像与 PVP 头像域差过大 Top1=0%, 必须用 PVP 自己的截图当模板)
  3. 增量学习: 未改名截图经 OCR 验名后自动入库为新模板, 越用越准
     (occ≥5 的精灵图像识别率 ~90%)

子命令:
  ingest    <目录|图片>   增量入库: OCR验名→裁头像→存模板 (md5去重, 可反复跑)
  recognize <目录|图片>   识别: 输出 JSON (--force-image 模拟改名只走图像链)
  status                 查看库规模/精灵覆盖
  eval                   留一法自测 (LOO, 库质量体检)

用法示例:
  python crawler_official_api/pvp_lib.py ingest   "C:/path/to/pvp素材"
  python crawler_official_api/pvp_lib.py recognize "C:/path/to/xxx.png"
  python crawler_official_api/pvp_lib.py recognize "C:/path/to/dir" --out out.json
  python crawler_official_api/pvp_lib.py status
  python crawler_official_api/pvp_lib.py eval

环境变量:
  PVP_LIB_DIR  模板库目录 (默认 crawler_official_api/output/pvp_lib)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from build_ingame_dataset import (  # noqa: E402
    imread_unicode, init_ocr, run_ocr, best_match, load_titles,
)
from eval_pvp_recognition import (  # noqa: E402
    pair_pvp_rows, crop_pvp_avatar,
    _floodfill_background, _largest_foreground_component, _center_and_scale,
    extract_orb_masked, orb_match_score_raw, imwrite_unicode, draw_debug,
)

# ============================================================
# 配置
# ============================================================
LIB_DIR = Path(os.environ.get("PVP_LIB_DIR", str(SCRIPT_DIR / "output" / "pvp_lib")))
IMG_DIR = LIB_DIR / "images"

# 图像匹配画布 (96×96 为 210 实例 LOO 网格搜索最优, 见 PVP_RECOGNITION.md)
CANVAS, FG_HEIGHT = 96, 72

# 图像链置信度启发式 (raw=ORB good匹配数+距离奖励, 满量程约 0~60)
IMG_RAW_HIGH = 20.0     # raw≥此值 且领先≥10% → high
IMG_MARGIN_HIGH = 0.10
IMG_RAW_MED = 12.0      # raw≥此值 → medium, 否则 low

# OCR 分级阈值 (同 pvp_recognize_v7, 基于 42/210 实例统计)
OCR_CONF_HIGH_MIN = 0.70   # T1(1字错) 采纳门槛
OCR_CONF_MED_MIN = 0.55    # T2(2字错) 采纳门槛

RECOG_OUT_DIR = SCRIPT_DIR / "output" / "pvp_recognize"


# ============================================================
# 工具
# ============================================================
def file_md5(fp: Path) -> str:
    h = hashlib.md5()
    with open(fp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def preproc96(img_bgr: Optional[np.ndarray]) -> Optional[Dict]:
    """PVP 头像 → 96×96 白底标准化画布 dict (含 gray / fg_mask)."""
    if img_bgr is None or img_bgr.size == 0 or img_bgr.shape[2] != 3:
        return None
    try:
        bg = _floodfill_background(img_bgr)
        fg = _largest_foreground_component(~bg)
        return _center_and_scale(fg, img_bgr, CANVAS, FG_HEIGHT)
    except Exception:
        return None


# ============================================================
# 模板库
# ============================================================
class PvpTemplateLibrary:
    """PVP 同域头像模板库: 增量入库 + ORB 特征缓存 + 匹配."""

    def __init__(self, lib_dir: Path = None):
        self.lib_dir = Path(lib_dir) if lib_dir else LIB_DIR
        self.img_dir = self.lib_dir / "images"
        self.img_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.lib_dir / "library.json"
        self.feat_path = self.lib_dir / "features.pkl"
        # library.json 结构:
        #   {"entries": [{id,seq,name,file,src,src_md5,row}],
        #    "ingested": {src_md5: {file,n_templates,ts}}}
        self.data: Dict[str, Any] = {"entries": [], "ingested": {}}
        self.entries: List[Dict] = []
        self._feat: Optional[List[Optional[np.ndarray]]] = None

    # ---------- 元数据 ----------
    def load(self):
        if self.meta_path.exists():
            self.data = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.entries = self.data.get("entries", [])
        return self

    def _save_meta(self):
        self.data["entries"] = self.entries
        self.meta_path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------- 特征缓存 ----------
    def _feat_version(self) -> str:
        ids = ";".join(f"{e['id']}:{e['file']}" for e in self.entries)
        return hashlib.md5(ids.encode("utf-8")).hexdigest()

    def features(self, force_rebuild=False) -> List[Optional[np.ndarray]]:
        """按 entries 顺序返回每条模板的 ORB 描述子 (None=提取失败)."""
        if self._feat is not None and not force_rebuild:
            return self._feat
        version = self._feat_version()
        if not force_rebuild and self.feat_path.exists():
            try:
                with open(self.feat_path, "rb") as f:
                    cache = pickle.load(f)
                if cache.get("version") == version:
                    self._feat = cache["des"]
                    return self._feat
            except Exception:
                pass
        # 重建
        des_list: List[Optional[np.ndarray]] = []
        t0 = time.time()
        for i, e in enumerate(self.entries):
            img = imread_unicode(self.img_dir / e["file"])
            pp = preproc96(img)
            if pp is None:
                des_list.append(None)
                continue
            _, des = extract_orb_masked(pp["gray"], pp["fg_mask"])
            des_list.append(des)
            if (i + 1) % 50 == 0:
                print(f"    [feat] {i + 1}/{len(self.entries)}  {time.time() - t0:.0f}s")
        with open(self.feat_path, "wb") as f:
            pickle.dump({"version": version, "des": des_list}, f)
        print(f"  [feat] 特征缓存重建: {len(des_list)} 条 ({time.time() - t0:.0f}s)")
        self._feat = des_list
        return des_list

    # ---------- 入库 (增量学习) ----------
    def ingest(self, src: Path, ocr=None) -> Dict[str, int]:
        """OCR 验名 → 裁头像 → 入库. 按源图 md5 去重, 可对同一目录反复执行."""
        src = Path(src)
        files = sorted(src.glob("*.png")) if src.is_dir() else [src]
        files = [f for f in files if f.is_file()]
        if not files:
            return {"files": 0, "new_templates": 0, "skipped_files": 0,
                    "unmatched_rows": 0}

        ocr = ocr or init_ocr()
        titles = load_titles()
        n_new = n_skip = n_unmatched = 0

        for k, fp in enumerate(files):
            md5 = file_md5(fp)
            if md5 in self.data["ingested"]:
                n_skip += 1
                continue
            img = imread_unicode(fp)
            if img is None:
                print(f"  [{k + 1}/{len(files)}] {fp.name}: 读取失败, 跳过")
                continue
            rows = pair_pvp_rows(run_ocr(ocr, fp))
            cnt = 0
            for ri, pr in enumerate(rows):
                m = best_match(pr["name_txt"], titles)
                if not m:
                    n_unmatched += 1     # 改名精灵/OCR失败 → 无验证答案, 不入库
                    continue
                title, seq, pet_id, dist = m
                crop, _box = crop_pvp_avatar(img, pr)
                if crop is None or crop.shape[0] < 16 or crop.shape[1] < 16:
                    continue
                # 文件名含源图md5 → 天然去重 (重复入库只会覆盖同名文件)
                fname = f"{seq:03d}_{title}__{md5[:8]}_r{ri}.png"
                imwrite_unicode(str(self.img_dir / fname), crop)
                self.entries.append({
                    "id": len(self.entries), "seq": int(seq), "name": str(title),
                    "file": fname, "src": fp.name, "src_md5": md5, "row": ri,
                })
                cnt += 1
            self.data["ingested"][md5] = {
                "file": fp.name, "n_templates": cnt,
                "ts": datetime.now().isoformat(timespec="seconds"),
            }
            n_new += cnt
            print(f"  [{k + 1}/{len(files)}] {fp.name}: +{cnt} 模板 "
                  f"(累计 {len(self.entries)})")

        self._save_meta()
        if n_new:
            self.features(force_rebuild=True)
        return {"files": len(files), "new_templates": n_new,
                "skipped_files": n_skip, "unmatched_rows": n_unmatched}

    # ---------- 匹配 (图像链) ----------
    def match(self, crop_bgr: np.ndarray, n_top: int = 5) -> List[Dict]:
        """头像 → TopN 识别. 96画布 ORB + per-seq max 聚合.
        返回 [{seq,name,raw,margin,confidence,rank}...], 空列表=无法匹配."""
        if not self.entries:
            return []
        des_list = self.features()
        pp = preproc96(crop_bgr)
        if pp is None:
            return []
        _, q_des = extract_orb_masked(pp["gray"], pp["fg_mask"])
        if q_des is None or len(q_des) < 2:
            return []
        seq_best: Dict[int, float] = {}
        seq_name = {e["seq"]: e["name"] for e in self.entries}
        for e, des in zip(self.entries, des_list):
            s = orb_match_score_raw(q_des, des)
            if s > seq_best.get(e["seq"], 0.0):
                seq_best[e["seq"]] = float(s)
        ranked = sorted(seq_best.items(), key=lambda x: -x[1])[:n_top]
        out = []
        for rank, (seq, raw) in enumerate(ranked):
            second = ranked[1][1] if len(ranked) > 1 else 0.0
            margin = (raw - second) / raw if raw > 1e-6 else 0.0
            if raw >= IMG_RAW_HIGH and margin >= IMG_MARGIN_HIGH:
                conf = "high"
            elif raw >= IMG_RAW_MED:
                conf = "medium"
            else:
                conf = "low"
            out.append({"seq": int(seq), "name": seq_name[seq],
                        "raw": round(raw, 2), "margin": round(margin, 3),
                        "confidence": conf, "rank": rank + 1})
        return out

    # ---------- 状态 ----------
    def status(self) -> Dict:
        occ = Counter(e["seq"] for e in self.entries)
        return {
            "n_templates": len(self.entries),
            "n_pets": len(occ),
            "n_ingested_files": len(self.data.get("ingested", {})),
            "pets_occ_ge_3": sum(1 for c in occ.values() if c >= 3),
            "pets_occ_eq_1": sum(1 for c in occ.values() if c == 1),
            "lib_dir": str(self.lib_dir),
        }

    # ---------- LOO 自测 ----------
    def loo_eval(self) -> str:
        """留一法评估: 每条模板与其余模板匹配 (排除自身id), 公平测=occ≥2."""
        des_list = self.features()
        seqs = [e["seq"] for e in self.entries]
        occ = Counter(seqs)
        n = len(self.entries)
        hits = Counter()
        n_fair = 0
        by_occ: Dict[int, Counter] = defaultdict(Counter)
        t0 = time.time()
        for i in range(n):
            if occ[seqs[i]] < 2:
                continue
            n_fair += 1
            q_des = des_list[i]
            if q_des is None:
                continue
            seq_best: Dict[int, float] = {}
            for j in range(n):
                if j == i:
                    continue
                s = orb_match_score_raw(q_des, des_list[j])
                if s > seq_best.get(seqs[j], 0.0):
                    seq_best[seqs[j]] = float(s)
            top = sorted(seq_best.items(), key=lambda x: -x[1])[:5]
            gt = seqs[i]
            t1 = bool(top and top[0][0] == gt)
            if t1:
                hits["top1"] += 1
            if gt in [s for s, _ in top[:3]]:
                hits["top3"] += 1
            if gt in [s for s, _ in top]:
                hits["top5"] += 1
            k = min(occ[gt], 5)
            if t1:
                by_occ[k]["hit"] += 1
            by_occ[k]["n"] += 1

        lines = ["=" * 60, "PVP 模板库 LOO 自测报告", "=" * 60,
                 f"模板 {n} 条, 唯一精灵 {len(occ)}, 公平测样本(occ≥2) {n_fair}",
                 f"耗时 {time.time() - t0:.0f}s", ""]
        if n_fair:
            lines.append(f"总体(公平测): Top1={hits['top1']}/{n_fair}"
                         f"={100.0 * hits['top1'] / n_fair:.1f}%  "
                         f"Top3={hits['top3']}/{n_fair}={100.0 * hits['top3'] / n_fair:.1f}%  "
                         f"Top5={hits['top5']}/{n_fair}={100.0 * hits['top5'] / n_fair:.1f}%")
        lines.append("分层 Top1 (occ=精灵在库中出现次数):")
        for k in sorted(by_occ):
            c = by_occ[k]
            pct = 100.0 * c["hit"] / c["n"] if c["n"] else 0
            lines.append(f"  occ={k}{'+' if k == 5 else ' '}: {c['hit']:>3}/{c['n']:<3} = {pct:5.1f}%")
        report = "\n".join(lines)
        (self.lib_dir / "loo_report.txt").write_text(report, encoding="utf-8")
        return report


# ============================================================
# 识别 (OCR 主链 + 图像 fallback)
# ============================================================
def recognize_image(img_path: Path, lib: PvpTemplateLibrary, ocr,
                    titles, force_image=False, save_debug=True) -> Dict:
    """单张 PVP 截图 → 结构化识别结果 (JSON 可序列化)."""
    t0 = time.time()
    img = imread_unicode(img_path)
    if img is None:
        return {"file": str(img_path), "error": "image_read_failed"}
    rows = pair_pvp_rows(run_ocr(ocr, img_path))

    pets, labels, boxes = [], [], []
    for ri, pr in enumerate(rows):
        ocr_text = pr["name_txt"]
        ocr_conf = round(float(pr["name_score"]), 3)
        crop, av_box = crop_pvp_avatar(img, pr)
        boxes.append(av_box)

        pet: Dict[str, Any] = {
            "index": ri, "ocr_text": ocr_text, "ocr_conf": ocr_conf,
            "source": "none", "seq": None, "name": None,
            "confidence": 0.0, "ocr_dist": None, "image_top5": None,
        }

        # --- 链路1: OCR + 模糊匹配 (未改名精灵) ---
        m = None if force_image else best_match(ocr_text, titles)
        if m:
            title, seq, pet_id, dist = m
            if dist == 0:
                src, conf = "ocr", 0.95 + 0.05 * min(1.0, ocr_conf)
            elif dist <= 1 and ocr_conf >= OCR_CONF_HIGH_MIN:
                src, conf = "ocr", 0.85
            elif dist <= 2 and ocr_conf >= OCR_CONF_MED_MIN:
                src, conf = "ocr", 0.70
            else:
                src, conf = None, 0.0
            if src:
                pet.update(source=src, seq=int(seq), name=title,
                           confidence=round(conf, 3), ocr_dist=int(dist))

        # --- 链路2: 图像 fallback (改名精灵 / OCR失效 / 强制图像模式) ---
        if pet["source"] == "none" and crop is not None:
            top = lib.match(crop)
            pet["image_top5"] = top
            if top:
                t1 = top[0]
                conf_map = {"high": 0.85, "medium": 0.60, "low": 0.35}
                pet.update(source="image", seq=t1["seq"], name=t1["name"],
                           confidence=conf_map.get(t1["confidence"], 0.3))

        pets.append(pet)
        nm = pet["name"] or "?"
        labels.append(f"{ri}:{nm}({pet['source']})")

    # 调试图 + 裁切头像
    if save_debug:
        RECOG_OUT_DIR.mkdir(parents=True, exist_ok=True)
        (RECOG_OUT_DIR / "crops").mkdir(exist_ok=True)
        stem = Path(img_path).stem
        try:
            draw_debug(img, rows, labels, boxes,
                       str(RECOG_OUT_DIR / f"debug_{stem}.jpg"))
        except Exception:
            pass
        for ri, pr in enumerate(rows):
            crop, _ = crop_pvp_avatar(img, pr)
            if crop is not None and pets[ri]["name"]:
                imwrite_unicode(str(
                    RECOG_OUT_DIR / "crops" /
                    f"{stem}_r{ri}_{pets[ri]['name']}.png"), crop)

    return {
        "file": str(img_path),
        "n_pets": len(rows),
        "pets": pets,
        "library": {"n_templates": len(lib.entries)},
        "elapsed_sec": round(time.time() - t0, 1),
    }


def recognize_path(target: Path, lib: PvpTemplateLibrary, out_json: Path = None,
                   force_image=False) -> List[Dict]:
    """文件或目录批量识别, 返回结果列表并可选写 JSON."""
    target = Path(target)
    files = sorted(target.glob("*.png")) if target.is_dir() else [target]
    ocr = init_ocr()
    titles = load_titles()
    results = []
    for i, fp in enumerate(files):
        r = recognize_image(fp, lib, ocr, titles, force_image=force_image)
        results.append(r)
        marks = "".join(
            "✔" if p["source"] in ("ocr", "image") and p["confidence"] >= 0.6
            else ("◷" if p["source"] != "none" else "✘")
            for p in r.get("pets", []))
        n_ok = sum(1 for p in r.get("pets", []) if p["source"] != "none")
        print(f"  [{i + 1}/{len(files)}] {fp.name}: {n_ok}/{r.get('n_pets', 0)} "
              f"识别 [{marks}]  {r.get('elapsed_sec', 0)}s", file=sys.stderr)
    if out_json:
        out_json = Path(out_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(results, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        print(f"  [out] JSON → {out_json}")
    return results


# ============================================================
# CLI
# ============================================================
def main():
    ap = argparse.ArgumentParser(description="PVP 精灵识别模板库 (详见 PVP_RECOGNITION.md)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ing = sub.add_parser("ingest", help="增量入库: OCR验名→裁头像→存模板")
    p_ing.add_argument("src", help="截图目录或单张图片 (可反复执行, 自动去重)")

    p_rec = sub.add_parser("recognize", help="识别截图 → JSON")
    p_rec.add_argument("src", help="截图目录或单张图片")
    p_rec.add_argument("--out", default=None, help="JSON 输出路径 (默认打印)")
    p_rec.add_argument("--force-image", action="store_true",
                       help="跳过OCR链强制图像识别 (模拟改名精灵, 测试用)")

    sub.add_parser("status", help="查看库规模")
    sub.add_parser("eval", help="留一法自测 (LOO)")

    args = ap.parse_args()
    lib = PvpTemplateLibrary().load()

    if args.cmd == "ingest":
        print(f"[ingest] {args.src} → {lib.lib_dir}")
        t0 = time.time()
        stats = lib.ingest(args.src)
        print(f"[ingest] 完成 ({time.time() - t0:.0f}s): "
              f"文件 {stats['files']} (跳过已入库 {stats['skipped_files']}), "
              f"新增模板 {stats['new_templates']}, "
              f"未匹配行(改名/OCR失败, 不入库) {stats['unmatched_rows']}")

    elif args.cmd == "recognize":
        print(f"[recognize] {args.src}  (库: {len(lib.entries)} 模板)", file=sys.stderr)
        out = Path(args.out) if args.out else None
        results = recognize_path(args.src, lib, out_json=out,
                                 force_image=args.force_image)
        # 单张且未指定 --out → JSON 打到 stdout (供外部程序管道读取)
        if not out and Path(args.src).is_file():
            print(json.dumps(results[0], ensure_ascii=False, indent=1))

    elif args.cmd == "status":
        st = lib.status()
        print(json.dumps(st, ensure_ascii=False, indent=2))

    elif args.cmd == "eval":
        print("[eval] LOO 留一法自测 (occ≥2 公平测)...")
        print(lib.loo_eval())


if __name__ == "__main__":
    main()
