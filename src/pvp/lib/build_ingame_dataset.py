# -*- coding: utf-8 -*-
"""
图鉴截图 -> OCR 识别精灵名 -> 模糊匹配 pet_detail 620 个 page_title -> 切出精灵头像
用途: 快速构建「游戏内真实头像 + 正确名字」的训练样本库

使用:
    python crawler_official_api/build_ingame_dataset.py  <截图目录>
    # 例: 截图放在 D:/洛克王国ai/lkwgai_pvp_assistant/图鉴截图/
    # 产物: crawler_official_api\output\ingame_avatars\ 下每只精灵 1 张 PNG + index.json
"""
from __future__ import annotations
import sys, io, os, json, re, time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

PROJECT = Path(__file__).resolve().parents[4]  # lkwgai_pvp_assistant root
PET_DETAIL = PROJECT / "src" / "pvp" / "data" / "pet_detail.js"
OUT = Path(__file__).resolve().parent / "output" / "ingame_avatars"
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "images").mkdir(exist_ok=True)
SRC_DIR: Optional[Path] = None

@dataclass
class Row:
    src_file: str
    line_y0: int
    line_y1: int
    bbox_text: list          # OCR 检测框 4 点 [x1,y1..x4,y4] (np.array shape (4,2) 可序列化)
    ocr_text: str
    ocr_score: float
    # 匹配结果
    match_title: Optional[str] = None
    match_seq: Optional[int] = None
    match_pet_id: Optional[str] = None
    match_distance: Optional[int] = None
    avatar_path: Optional[str] = None   # 导出的头像文件相对路径 (images/xxx.png)

# -------- 1) 加载 620 个图鉴名 --------
def load_titles():
    src = PET_DETAIL.read_text(encoding="utf-8")
    entries = []
    for m in re.finditer(r'"(\d+)":\s*\[', src):
        seq = int(m.group(1)); start = m.end() - 1
        depth = 0; end = start
        for i in range(start, len(src)):
            if src[i] == "[": depth += 1
            elif src[i] == "]":
                depth -= 1
                if depth == 0: end = i; break
        block = src[start:end]
        for vm in re.finditer(r'\{\s*"page_title":\s*"([^"]+)"(.*?)\}', block, re.S):
            title, body = vm.group(1), vm.group(2)
            img_m = re.search(r'"img":\s*"([^"]*)"', body)
            img = img_m.group(1) if img_m else ""
            pid_m = re.search(r"/pets/(\d+)/icon\.png", img)
            entries.append({
                "seq": seq, "page_title": title,
                "pet_id": pid_m.group(1) if pid_m else None,
            })
    print(f"[dict] {len(entries)} 个图鉴变体")
    return entries

# -------- 2) 字形纠错 + 模糊匹配 --------
# 形近字替换表: OCR 常认错的字
SHAPE_REPLACEMENTS = [
    ("幻", "幼"), ("幼", "幻"),
    ("王", "土"), ("土", "王"),
    ("主", "王"), ("王", "主"),
    ("板", "般"), ("般", "板"),
    ("狐", "孤"), ("孤", "狐"),
    ("狼", "狠"), ("狠", "狼"),
    ("蝙", "编"), ("编", "蝙"),
    ("蝎", "蝎"), ("魔", "磨"), ("磨", "魔"),
    ("巨", "区"), ("区", "巨"),
    ("蓝", "篮"), ("篮", "蓝"),
    ("罗", "萝"), ("萝", "罗"),
    ("隐", "稳"), ("稳", "隐"),
    ("犬", "大"), ("大", "犬"),
    ("蒂", "带"), ("带", "蒂"),
    ("顶", "钉"), ("钉", "顶"),
]
# 常见 OCR 漏字前缀 (因为左边离头像近, 检测框切漏一两个字)
# 先不枚举, 用编辑距离 + 「后缀包含」 兜底

def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b): a, b = b, a
    if not b: return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        cur = [i + 1]
        for j, cb in enumerate(b):
            cur.append(min(
                prev[j + 1] + 1,     # 删
                cur[j] + 1,          # 插
                prev[j] + (0 if ca == cb else 1),  # 改
            ))
        prev = cur
    return prev[-1]

def best_match(ocr_text: str, titles):
    """返回 (page_title, seq, pet_id, 距离) 或 None
    分层匹配（从前到后命中即采用）:
      1) 编辑距离 + 形近字替换后 <= 阈值 （优先，因为精确）
      2) OCR文本 == title后缀 或 == title前缀 （OCR漏了前缀字/后缀字最常见）
      3) OCR文本 被包含在title里 且 长度差 <= 3
    """
    text = ocr_text.strip().replace(" ", "").replace("　", "")
    if not text: return None

    # 预计算每个 title 的综合距离；存所有候选
    scored = []  # [(score, levd, tier, title)]
    for t in titles:
        title = t["page_title"]

        # 1) 基础编辑距离 + 形近字替换
        lev = levenshtein(text, title)
        for a, b in SHAPE_REPLACEMENTS:
            d2 = levenshtein(text.replace(a, b), title)
            if d2 < lev: lev = d2
        # 2) 前缀/后缀包含奖励 (OCR 漏前缀/后缀字的情况)
        suffix_match = title.endswith(text) and len(title) - len(text) <= 4
        prefix_match = title.startswith(text) and len(title) - len(text) <= 4
        exact_contain = (text in title) and (0 < len(title) - len(text) <= 3)

        # tier: 越小越优先. suffix/prefix 给 "在同tier里" 额外优先的权重
        tiebreak = 1 if (suffix_match or prefix_match or exact_contain) else 0
        # 纯 lev 命中的阈值: 越短的 OCR 文本要求越严 (2字及以下必须 0~1, 否则容易被形近字乱牵)
        strict_lev_thresh = (
            1 if len(text) <= 2
            else 2 if len(text) <= 4
            else max(2, len(text) // 2 + 1)
        )
        if tiebreak:
            # 有包含关系, 用宽松阈值 (因为前缀/后缀字被 OCR 切漏了)
            lev_thresh_ok = lev <= max(3, len(text) // 2 + 1)
        else:
            lev_thresh_ok = lev <= strict_lev_thresh
        if lev_thresh_ok:
            tier = 0
            score = lev - tiebreak  # 包含型 + 近距离同时成立, 更可信
        elif suffix_match:
            tier = 1
            score = len(title) - len(text)
        elif prefix_match:
            tier = 2
            score = len(title) - len(text)
        elif exact_contain:
            tier = 3
            score = len(title) - len(text)
        else:
            tier = 9
            score = lev
        scored.append((tier, score, lev, -tiebreak, title))

    # tuple: (tier, score, lev, -tiebreak, title) 按顺序排
    scored.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    best = scored[0]
    tier, score, levd, _, title = best
    # 可接受阈值: tier<=3 (必须命中4类规则之一)
    if tier > 3:
        return None
    hit = next(t for t in titles if t["page_title"] == title)
    return hit["page_title"], hit["seq"], hit["pet_id"], levd

# -------- 3) OCR + 行切片 --------
def init_ocr():
    from paddleocr import PaddleOCR
    # mobile 版比 server 版快 10 倍以上；图鉴是常规印刷字，精度足够
    return PaddleOCR(
        lang="ch",
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="PP-OCRv5_mobile_rec",
        use_doc_orientation_classify=False,   # 图鉴截图正向，不需要文档方向校正
        use_doc_unwarping=False,
        use_textline_orientation=False,        # 文字是水平的
        text_det_limit_side_len=1920,         # 大图缩到 1920 长边，提速
        text_rec_score_thresh=0.3,            # 低了可以先召回
    )

def run_ocr(ocr, img_path: Path):
    recs = list(ocr.predict(str(img_path)))
    out = []  # (text, score, poly)
    for rec in recs:
        texts = rec.get("rec_texts") or []
        scores = rec.get("rec_scores") or []
        polys = rec.get("rec_polys") or rec.get("dt_polys") or []
        for i, t in enumerate(texts):
            score = float(scores[i]) if i < len(scores) else 0.0
            poly = polys[i] if i < len(polys) else None
            if poly is not None:
                poly = [[int(round(float(c))) for c in pt] for pt in poly]
            out.append((t, score, poly))
    # 按 y 升序（行从上到下）；y 相近的按 x
    def y_of(poly):
        if not poly: return 0
        return sum(pt[1] for pt in poly) // 4
    out.sort(key=lambda r: (y_of(r[2]) // 10, (r[2][0][0] if r[2] else 0)))
    return out

def poly_box(poly):
    xs=[pt[0] for pt in poly]; ys=[pt[1] for pt in poly]
    return min(xs),max(xs),min(ys),max(ys)

def is_numline(t: str) -> bool:
    t=t.strip()
    if re.fullmatch(r'[\dOoODQIZS]+\s*', t): return True
    return False

# -------- 4) 把 OCR 行配对: [序号, 名字] 组合成一个"精灵行" --------
def pair_pet_rows(ocr_lines, W_img):
    """
    图鉴通常每个精灵: [seq(数字) y=上一行] [名字 y=下一行] 两 OCR 行, 视觉上是一个 row 对
    返回 list of dict: {y0, y1, cell_h, name_txt, name_score, name_poly, seq_poly (可选)}
    """
    import re
    rows=[]  # 最终的 pair
    used=[False]*len(ocr_lines)
    # 预处理: 算每个的 bbox + y_center
    info=[]
    for i,(t,s,p) in enumerate(ocr_lines):
        if not p: continue
        tx0,tx1,ty0,ty1=poly_box(p)
        info.append({
            'idx':i,'t':t,'s':s,'p':p,
            'x0':tx0,'x1':tx1,'y0':ty0,'y1':ty1,
            'cy':(ty0+ty1)//2,'h':max(ty1-ty0,1),
            'is_num':is_numline(t)
        })
    for e in info:
        if used[e['idx']]: continue
        used[e['idx']]=True
        # 如果当前是数字行, 匹配其后 y 最近, 并且不在数字/纯符号的一行做名字行
        if e['is_num']:
            # 找名字: 下一个, y 距离 < 1.5 * self.h, x0 接近 (同一列偏左就行), 不是数字
            best=None; best_score=1e9
            for f in info:
                if used[f['idx']]: continue
                if f['is_num']: continue
                dy = abs(f['cy'] - (e['cy']+e['h']*0.8))   # 名字中心应该在数字中心下方 ~h
                if f['y0'] < e['y0']-4: continue            # 名字不能在数字顶上
                if f['y0'] > e['y1'] + e['h']*1.5: continue  # 离太远 (>1.5行)
                dx = abs(f['x0'] - e['x0'])
                sc = dy + dx*0.2
                if sc < best_score:
                    best_score=sc; best=f
            if best is not None:
                used[best['idx']]=True
                rows.append({
                    'y0': min(e['y0'], best['y0']),
                    'y1': max(e['y1'], best['y1']),
                    'cell_h': max(e['h'], best['h']),
                    'name_idx': best['idx'], 'name_txt': best['t'], 'name_score':best['s'], 'name_poly':best['p'],
                    'seq_idx': e['idx'],   'seq_txt': e['t'],    'seq_score':e['s'],  'seq_poly':e['p'],
                })
                continue
        # 否则当前是名字行 (也可能是没配对上的孤行, 没有数字对应), 单独输出
        rows.append({
            'y0': e['y0']-e['h'],  'y1': e['y1']+e['h']//2,
            'cell_h': e['h'],
            'name_idx': e['idx'], 'name_txt': e['t'], 'name_score':e['s'], 'name_poly':e['p'],
            'seq_idx': None, 'seq_txt': None, 'seq_score':0.0, 'seq_poly':None,
        })
    # 每个 row 额外给一个"建议的头像 x 区间"
    # 阈值: 窄屏用更高 0.65, 宽屏用 0.55
    # — 长名字(5字+)容易跨过中线, 不要因为跨过 0.45W 就切反了
    thresh = 0.65*W_img if W_img < 400 else (0.60*W_img if W_img < 900 else 0.55*W_img)
    for r in rows:
        nx0,nx1,_,_=poly_box(r['name_poly'])
        sx0=sx1=0
        if r['seq_poly']: sx0,sx1,_,_=poly_box(r['seq_poly'])
        max_right_x = max(nx1,sx1)
        if max_right_x < thresh:
            # 头像在右侧: 占满行高, 右对齐, 正方形边长 = (y1-y0) * 1.0  (不要扩太大避免跨 row)
            r['avatar_side'] = 'right'
        else:
            r['avatar_side'] = 'left'
    return rows

# -------- 4a) 按配对的 row 裁切头像 --------
def crop_avatar_by_row(full_img_np, pet_row):
    import numpy as np
    H, W = full_img_np.shape[:2]
    y0, y1 = pet_row['y0'], pet_row['y1']
    row_h = max(y1 - y0, 16)
    size = int(row_h * 1.05)   # 边长 ≈ 整行高
    cy = (y0 + y1) // 2
    ay0 = max(0, cy - size//2)
    ay1 = min(H, ay0 + size)
    ay0 = max(0, ay1 - size)  # 强制 y 方向是 size
    if pet_row['avatar_side']=='right':
        # 右半屏: 正方形靠右边界留出 padding
        pad_right = max(6, W//60)
        ax1 = W - pad_right
        ax0 = ax1 - size
    else:
        # 左半屏: 正方形靠左
        nx0,_,_,_=poly_box(pet_row['name_poly'])
        pad_left = max(4, W//120)
        ax0 = pad_left
        ax1 = min(nx0, ax0 + size)
        ax0 = ax1 - size
    # 强制 x 方向是 size (边界情况也别裁成竖条)
    if ax0 < 0: ax0 = 0; ax1 = min(W, size)
    if ax1 > W: ax1 = W; ax0 = max(0, W - size)
    if ax1 - ax0 < 10:
        return None, (int(ax0), int(ay0), int(ax1), int(ay1))
    crop = full_img_np[ay0:ay1, ax0:ax1]
    if crop.size == 0:
        return None, (0,0,0,0)
    return crop, (int(ax0), int(ay0), int(ax1), int(ay1))

# 旧 API 兼容 (main 里未配对前也用)
def crop_avatar(full_img_np, text_poly):
    return crop_avatar_by_row(full_img_np, {
        'y0': min(p[1] for p in text_poly),
        'y1': max(p[1] for p in text_poly),
        'cell_h': max((max(p[1] for p in text_poly)-min(p[1] for p in text_poly)),16),
        'name_poly': text_poly,
        'seq_poly': None,
        'avatar_side': ('right' if max(p[0] for p in text_poly) < full_img_np.shape[1]*0.45 else 'left'),
    })

# -------- 4b) 绘制诊断图: OCR 框(红) + 头像裁切区(绿) + 匹配名 --------
def draw_debug_view(full_img_np, ocr_lines, matches, rows_this_img, out_path: Path):
    import cv2, numpy as np
    vis = full_img_np.copy()
    H, W = vis.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    for (txt, score, poly), (match_info, avatar_box) in zip(ocr_lines, matches):
        if not poly: continue
        xs = [pt[0] for pt in poly]; ys = [pt[1] for pt in poly]
        # OCR 文字框 红
        pts = np.array(poly, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(vis, [pts], True, (0, 0, 255), 2)
        # 头像裁切区 绿
        ax0, ay0, ax1, ay1 = avatar_box
        if ax1 > ax0 and ay1 > ay0:
            cv2.rectangle(vis, (ax0, ay0), (ax1, ay1), (0, 200, 0), 2)
        # 顶部标签: OCR 文 + 匹配名 (蓝)
        tag = f"'{txt}' → {match_info}"
        y_label = max(16, min(ys) - 6)
        # 自适应缩放: 大图用大字体
        scale = 0.6 if W < 900 else (0.8 if W < 1600 else 1.0)
        cv2.putText(vis, tag, (max(0, min(xs) - 4), y_label),
                    font, scale, (255, 0, 0), 2, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if ok:
        buf.tofile(str(out_path))

import cv2, numpy as np
def imread_unicode(p: Path):
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)

# -------- main --------
def main():
    if len(sys.argv) < 2:
        print("用法: python crawler_official_api/build_ingame_dataset.py <图鉴截图文件夹路径>")
        return
    src_dir = Path(sys.argv[1])
    if not src_dir.exists():
        print(f"找不到目录: {src_dir}"); return

    titles = load_titles()
    print(f"[OCR] PaddleOCR 初始化... (首次会慢, 之后缓存)"); t0 = time.time()
    ocr = init_ocr(); print(f"  {time.time()-t0:.1f}s 初始化完成")

    rows_all: list[Row] = []
    exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    files = [f for f in sorted(src_dir.iterdir()) if f.suffix.lower() in exts]
    print(f"[scan] 找到 {len(files)} 张截图")

    debug_out = OUT / "debug"
    debug_out.mkdir(exist_ok=True)

    for idx, fp in enumerate(files):
        img = imread_unicode(fp)
        if img is None: print(f"  ⚠ 无法打开 {fp.name}"); continue
        H_img, W_img = img.shape[:2]
        print(f"\n[{idx+1}/{len(files)}] {fp.name} {W_img}x{H_img}")
        try:
            ocr_lines = run_ocr(ocr, fp)
        except Exception as e:
            print(f"  ⚠ OCR 失败: {e}"); continue
        pet_rows = pair_pet_rows(ocr_lines, W_img)
        print(f"  OCR {len(ocr_lines)} 行 → {len(pet_rows)} 个精灵行")
        # 做 debug: 每行 OCR 加上绿框参考 (未匹配也显示)
        debug_ocr_sidecars = []  # 每个 pet_row 对应若干 OCR 行的标注，画绿框+蓝标签
        for ri, pr in enumerate(pet_rows):
            matched = best_match(pr['name_txt'], titles)
            avatar_box = (0, 0, 0, 0)
            tag_extra = ""
            if matched:
                title, seq, pid, d = matched
                crop, avatar_box = crop_avatar_by_row(img, pr)
                if crop is not None and crop.size > 0:
                    out_name = f"{seq:03d}_{title}.png"
                    rel = f"images/{out_name}"
                    out_path = OUT / rel
                    if not out_path.exists():
                        ok, buf = cv2.imencode(".png", crop)
                        if ok:
                            buf.tofile(str(out_path))
                    tag_extra = f"✔ d={d} {title}"
                    row = Row(
                        src_file=fp.name, line_y0=pr['y0'], line_y1=pr['y1'],
                        bbox_text=[list(x) for x in pr['name_poly']],
                        ocr_text=pr['name_txt'], ocr_score=pr['name_score'],
                        match_title=title, match_seq=seq, match_pet_id=pid,
                        match_distance=d, avatar_path=rel if crop is not None else None,
                    )
                else:
                    tag_extra = f"✔ d={d} crop_fail"
                    row = Row(
                        src_file=fp.name, line_y0=pr['y0'], line_y1=pr['y1'],
                        bbox_text=[list(x) for x in pr['name_poly']],
                        ocr_text=pr['name_txt'], ocr_score=pr['name_score'],
                        match_title=title, match_seq=seq, match_pet_id=pid, match_distance=d,
                    )
            else:
                _, avatar_box = crop_avatar_by_row(img, pr)
                tag_extra = "❌ 未匹配"
                row = Row(
                    src_file=fp.name, line_y0=pr['y0'], line_y1=pr['y1'],
                    bbox_text=[list(x) for x in pr['name_poly']],
                    ocr_text=pr['name_txt'], ocr_score=pr['name_score'],
                )
            seq_tag = f"[seq={pr['seq_txt']}] " if pr['seq_txt'] else ""
            print(f"    [{ri}] {seq_tag}s={pr['name_score']:.2f} '{pr['name_txt']}' -> {tag_extra}")
            rows_all.append(row)
            # 调试数据: 每个 pet_row 对应 1 或 2 个 OCR 文本 (名字+序号), 画图时所有行的文本多边形都用同一只精灵同一 avatar_box
            debug_ocr_sidecars.append({
                'name_poly': pr['name_poly'], 'seq_poly': pr['seq_poly'],
                'avatar_box': avatar_box,
                'label': f"'{pr['name_txt']}' → {matched[0] if matched else '❓'}",
            })
        # 画诊断图: 把 1-2 个 OCR 框 + 1 个头像框, 逐行展开
        debug_path = debug_out / (fp.stem + "_debug.jpg")
        try:
            import numpy as np
            vis = img.copy()
            H, W = vis.shape[:2]
            font = cv2.FONT_HERSHEY_SIMPLEX
            scale = 0.6 if W < 900 else (0.8 if W < 1600 else 1.0)
            for sc in debug_ocr_sidecars:
                # 红框: OCR 文字 (名字+序号)
                for poly in [sc['name_poly'], sc['seq_poly']]:
                    if not poly: continue
                    pts = np.array(poly, dtype=np.int32).reshape((-1, 1, 2))
                    cv2.polylines(vis, [pts], True, (0, 0, 255), 2)
                # 绿框: 头像裁切区
                ax0,ay0,ax1,ay1 = sc['avatar_box']
                if ax1>ax0 and ay1>ay0:
                    cv2.rectangle(vis, (ax0, ay0), (ax1, ay1), (0, 200, 0), 2)
                # 蓝标签: 放在名字框正上方
                xs=[p[0] for p in sc['name_poly']]; ys=[p[1] for p in sc['name_poly']]
                xlab=max(0,min(xs)-4); ylab=max(16,min(ys)-8)
                cv2.putText(vis, sc['label'], (xlab, ylab), font, scale, (255, 0, 0), 2, cv2.LINE_AA)
            ok, buf = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 88])
            if ok: buf.tofile(str(debug_path))
        except Exception as ee:
            print(f"  [debug] 绘失败: {ee}")
        print(f"  诊断图 -> {debug_path}")

    # 保存 index.json
    index_path = OUT / "index.json"
    json.dump(
        {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "src_dir": str(src_dir),
            "total_rows": len(rows_all),
            "matched_rows": sum(1 for r in rows_all if r.match_title),
            "avatars_exported": sum(1 for r in rows_all if r.avatar_path),
            "rows": [asdict(r) for r in rows_all],
        },
        open(index_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1,
    )
    print(f"\n✅ 完成: {sum(1 for r in rows_all if r.avatar_path)} 个头像导出到 {OUT}")
    print(f"   index: {index_path}")

if __name__ == "__main__":
    main()
