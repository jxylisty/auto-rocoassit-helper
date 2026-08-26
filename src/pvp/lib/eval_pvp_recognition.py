# -*- coding: utf-8 -*-
"""
PVP 识别验证脚本 (v6 — GrabCut 抠图 + 标准化 + wiki 补充版)

核心改进 (相对 v5 GRADIENT Floodfill):
  Floodfill 系列 (v3 FIXED_RANGE±32 / v4 亮度阈值 / v5 FIXED_RANGE±60 / v5 GRADIENT±24)
  全部失败于 3D 渲染精灵的抗锯齿光晕轮廓——颜色是渐进式过渡不是硬突变。
  v6 改用 GrabCut (基于 GMM 的全局色彩聚类抠图):
    - 4 通道 RGBA → alpha < 128 当背景 (最准)
    - 3 通道 BGR → 强制 "边框 2 像素 100% 背景 (GC_BGD)"; 其余像素 "可能背景 (GC_PR_BGD)"
    - GrabCut 5 次迭代自动学习背景 GMM / 前景 GMM, 再重分配每个像素
    - 形态学 7x7 闭运算修洞 → 边界连通最大背景块 → 0.4% 孤岛清理
  不依赖相邻色差, 完美兼容:
    PVP 深蓝渐变 / ingame 浅白背景 / 深色精灵 / 浅色米白精灵 / 炫彩高饱和精灵
  其他不变: ORB 绝对匹配数 + 双路 masked 模板匹配 + wiki 补充库 (391 只)
"""
import json
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from build_ingame_dataset import (  # noqa: E402
    imread_unicode,
    init_ocr,
    run_ocr,
    best_match,
    load_titles,
    poly_box,
)

OUT_DIR = SCRIPT_DIR / "output" / "pvp_eval"
CROP_DIR = OUT_DIR / "crops"
DBG_DIR = OUT_DIR / "debug"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CROP_DIR.mkdir(parents=True, exist_ok=True)
DBG_DIR.mkdir(parents=True, exist_ok=True)

# ==========================================================
# 核心: 前景抠图 + 尺寸/位置 标准化 (v4 版)
# ==========================================================
CANVAS = 64          # 最终输出画布 64x64
FG_HEIGHT = 48       # 前景高度 = 48px (75% of 64, 上下各留 8px 白边)

# ---------- 抠图 v10 (最终版): K=4 多聚类 + 边界触碰+面积判定背景. 不再依赖"原型色距离"! ----------
#     (2026-08-25 修复3个不同域的背景完全失效的问题)
def _floodfill_background(img_bgr_or_rgba):
    """抠图 v10 (三域通用: wiki透明PNG / ingame图鉴贴边非白 / PVP深蓝渐变)

    为什么要放弃"近原型=背景"这一条规则:
      * wiki透明PNG: alpha通道直接搞定 ✓
      * ingame图鉴贴边: 左上角像素是精灵身体! KMeans用"四角采样颜色=背景原型"会吃掉精灵 ✗
      * PVP深蓝渐变: 整张图没有白色. 加白padding后K=2只分成 [白, 其他所有] → 全图=前景 ✗

    v10 最终策略 (多聚类 + 边界规则):
      1) 先统一加 PAD=12 纯白 padding → 保证至少有"一大片纯白边框"作为已知背景锚点
      2) 转 LAB, MiniBatchKMeans(K=4) 聚 4 簇 (覆盖: 白padding / 浅色背景 / 深色背景 / 精灵前景)
      3) 对每个簇: 如果"触碰 12px padding 外框 + 面积占比 ≥ 5%" → 标记背景簇
      4) 所有背景簇合并 = 背景候选 mask
      5) 形态学 5x5 闭运算 + 膨胀, 再最大连通域 = 最终背景
      6) 裁掉 padding, 返回与输入同 H×W mask
    """
    PAD = 12
    H0 = img_bgr_or_rgba.shape[0]; W0 = img_bgr_or_rgba.shape[1]
    N0 = H0 * W0

    # ------ 分支 1: RGBA → alpha 最准, 直接用 ------
    if img_bgr_or_rgba.shape[2] == 4:
        alpha = img_bgr_or_rgba[:, :, 3]
        bg_mask = alpha < 128
        num, labels, stats, _ = cv2.connectedComponentsWithStats(
            bg_mask.astype(np.uint8), connectivity=8)
        if num > 1:
            border_lb = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
            best_i = -1; best_a = 0
            for i in range(1, num):
                if i not in border_lb: continue
                a = int(stats[i, cv2.CC_STAT_AREA])
                if a > best_a: best_a = a; best_i = i
            if best_i > 0:
                bg_mask = (labels == best_i)
        return bg_mask.astype(np.bool_)

    # ------ 分支 2: BGR 3 通道 → padding + K=4 聚类 ------
    bgr = img_bgr_or_rgba
    bgr_p = cv2.copyMakeBorder(bgr, PAD, PAD, PAD, PAD,
                               cv2.BORDER_CONSTANT, value=(255, 255, 255))
    H = bgr_p.shape[0]; W = bgr_p.shape[1]
    N = H * W
    lab = cv2.cvtColor(bgr_p, cv2.COLOR_BGR2LAB).astype(np.float32)
    pixels = lab.reshape(-1, 3)

    # K=4 聚类 (白padding / 浅背景 / 深背景 / 精灵主体)
    try:
        from sklearn.cluster import MiniBatchKMeans
        km = MiniBatchKMeans(n_clusters=4, n_init=5, random_state=0, batch_size=4096, max_iter=30)
        km.fit(pixels)
        labels_k = km.labels_.astype(np.int32).reshape(H, W)
    except Exception:
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1.0)
        _, labels_k, _ = cv2.kmeans(
            pixels, 4, None, criteria, 5, cv2.KMEANS_PP_CENTERS)
        labels_k = labels_k.reshape(H, W).astype(np.int32)

    # padding 边框 = 原图像的外缘, 索引 [PAD-2, ...] 到 [-PAD+2] 内的环
    # 判定"触碰padding外缘(图像真正的4条边)" + 面积 ≥ 5% = 背景簇
    def touches_outer_border(mask_bool):
        return (mask_bool[0, :].any() or mask_bool[-1, :].any() or
                mask_bool[:, 0].any() or mask_bool[:, -1].any())

    bg_cand = np.zeros((H, W), dtype=np.bool_)
    for k in range(4):
        cmask = (labels_k == k)
        area_frac = cmask.sum() / N
        if touches_outer_border(cmask) and area_frac >= 0.05:
            bg_cand |= cmask

    # 兜底: 如果没有任何簇判为背景 (极少见), 直接用触碰外边框的所有簇合并
    if not bg_cand.any():
        for k in range(4):
            cmask = (labels_k == k)
            if touches_outer_border(cmask):
                bg_cand |= cmask
    # 再兜底: 还没有 → 取面积最大簇当背景
    if not bg_cand.any():
        max_k = -1; max_a = 0
        for k in range(4):
            a = (labels_k == k).sum()
            if a > max_a: max_a = a; max_k = k
        bg_cand = (labels_k == max_k)

    # 形态学修: 5x5椭圆闭运算 (填补背景中的噪点洞) + 3x3膨胀 (向前景方向内侵1px防边缘漏光)
    m = bg_cand.astype(np.uint8)
    k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k5, iterations=1)
    m = cv2.morphologyEx(m, cv2.MORPH_DILATE, k3, iterations=1)

    # 背景 = 触碰外边框的最大连通域 (避免背景被切成好几块)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    bg_mask_p = np.zeros((H, W), dtype=np.bool_)
    if num > 1:
        outer_border_lb = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
        best_i = -1; best_a = 0
        for i in range(1, num):
            if i not in outer_border_lb: continue
            a = int(stats[i, cv2.CC_STAT_AREA])
            if a > best_a: best_a = a; best_i = i
        if best_i > 0:
            bg_mask_p = (labels == best_i)

    # 背景内 < 0.4% 面积 前景孤岛并入背景
    not_bg = (1 - bg_mask_p.astype(np.uint8))
    num2, labels2, stats2, _ = cv2.connectedComponentsWithStats(not_bg, connectivity=8)
    min_a = max(8, int(N0 * 0.004))
    for i in range(1, num2):
        if stats2[i, cv2.CC_STAT_AREA] < min_a:
            bg_mask_p[labels2 == i] = True

    return bg_mask_p[PAD:-PAD, PAD:-PAD].astype(np.bool_)

def _largest_foreground_component(not_bg):
    """not_bg = True 表示非背景 (候选前景), 返回最大连通域作为最终前景 mask,
    去除细碎小前景块."""
    if not_bg.sum() == 0:
        return not_bg
    num, labels, stats, _ = cv2.connectedComponentsWithStats(
        not_bg.astype(np.uint8), connectivity=8)
    if num <= 1:  # 只有背景
        return np.zeros_like(not_bg, dtype=np.bool_)
    # 找最大 label (跳过 0=背景)
    max_i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return (labels == max_i)

def _center_and_scale(fg_mask_bool, bgr_src, canvas=CANVAS, fg_h=FG_HEIGHT):
    """输入: 原图 (HxWx3 BGR uint8), 前景 mask (HxW bool)
    输出: dict:
        canvas_bgr:  canvas x canvas x3 uint8 纯白底 + 前景居中缩放贴上去
        canvas_gray: 64x64 uint8 灰度
        canvas_edge: 64x64 uint8 Canny 边缘
        canvas_sobel: 64x64 uint8 0~255 Sobel 梯度幅度 (归一化)
        canvas_fg_mask: 64x64 bool 前景 mask
    """
    H, W = bgr_src.shape[:2]
    ys, xs = np.where(fg_mask_bool)
    if len(ys) < 16:
        # 没前景, 直接返回一个全白中心 + 空 mask + 空直方图
        return {
            "bgr": np.full((canvas, canvas, 3), 255, dtype=np.uint8),
            "gray": np.full((canvas, canvas), 255, dtype=np.uint8),
            "edge": np.zeros((canvas, canvas), dtype=np.uint8),
            "sobel": np.zeros((canvas, canvas), dtype=np.uint8),
            "fg_mask": np.zeros((canvas, canvas), dtype=np.bool_),
            "hog_hist": np.zeros((64,), dtype=np.float32),
            "hsv_hist": np.zeros((36,), dtype=np.float32),
            "lab_hist": np.zeros((24,), dtype=np.float32),
        }
    x0, y0, x1, y1 = xs.min(), ys.min(), xs.max(), ys.max()
    bw = x1 - x0 + 1; bh = y1 - y0 + 1
    # 切出前景块 (带 alpha: 非前景变透明)
    fg_crop_rgb = cv2.cvtColor(bgr_src[y0:y1+1, x0:x1+1, :], cv2.COLOR_BGR2RGB)
    fg_mask_crop = fg_mask_bool[y0:y1+1, x0:x1+1]  # (bh, bw) bool
    # 按 fg_h 缩放目标高
    scale = fg_h / max(1, bh)
    new_h = max(1, int(round(bh * scale)))
    new_w = max(1, int(round(bw * scale)))
    # 限制宽不超过 canvas-4 (避免贴出去)
    if new_w > canvas - 4:
        scale2 = (canvas - 4) / max(1, new_w)
        new_h = max(1, int(new_h * scale2))
        new_w = int(new_w * scale2)
    # 缩放前景 RGB 块 和 mask
    fg_pil = Image.fromarray(fg_crop_rgb).convert("RGBA")
    # 把 mask 合成 alpha 通道
    alpha = Image.fromarray((fg_mask_crop.astype(np.uint8) * 255), mode="L")
    fg_pil.putalpha(alpha)
    fg_resized = fg_pil.resize((new_w, new_h), Image.LANCZOS)
    # 居中贴到纯白 canvas
    canvas_pil = Image.new("RGBA", (canvas, canvas), (255, 255, 255, 255))
    ox = (canvas - new_w) // 2
    oy = (canvas - new_h) // 2
    canvas_pil.paste(fg_resized, (ox, oy), fg_resized)  # 第三个参数是 mask=透明
    # 提取前景 mask (缩放+偏移后的)
    alpha_arr = np.asarray(fg_resized.split()[-1], dtype=np.uint8)  # (new_h, new_w)
    mask_canvas = np.zeros((canvas, canvas), dtype=np.uint8)
    mask_canvas[oy:oy+new_h, ox:ox+new_w] = alpha_arr
    fg_mask_canvas_bool = mask_canvas > 127

    rgb = np.asarray(canvas_pil.convert("RGB"), dtype=np.uint8)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    # Canny 边缘 (自适应阈值)
    med = float(np.median(gray[fg_mask_canvas_bool])) if fg_mask_canvas_bool.any() else 128.0
    lo = int(max(0, med * 0.5)); hi = int(min(255, med * 1.6))
    edge = cv2.Canny(gray, lo, hi)
    # Sobel 梯度幅度 (归一到 0~255)
    sx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(sx*sx + sy*sy)
    mag_max = float(mag.max())
    if mag_max > 1:
        sobel = np.clip(255 * mag / mag_max, 0, 255).astype(np.uint8)
    else:
        sobel = np.zeros_like(gray)

    # ========= v11: HOG + HSV 色相直方图 (鲁棒特征) =========
    # HOG: 方向梯度直方图, 只在前景点上统计 64bin (抗异色/色偏/光照变化, 保留形状)
    hog_hist = np.zeros((64,), dtype=np.float32)
    # 1) 方向(0~180 unsigned, 避免方向翻转问题)
    ang = np.arctan2(np.abs(sy), np.abs(sx)) * (180.0 / np.pi)  # (canvas, canvas) 0~90?不, 用绝对化后 0~90 不够; 换 atan2(sy,sx) 取模 180 unsigned
    ang_full = np.arctan2(sy, sx) * (180.0 / np.pi) % 180.0
    if fg_mask_canvas_bool.sum() >= 9 and mag_max > 1:
        weights = mag[fg_mask_canvas_bool].astype(np.float32)
        wsum = float(weights.sum())
        if wsum > 1e-3:
            bin_idx = np.clip((ang_full[fg_mask_canvas_bool] / 180.0 * 64).astype(np.int32), 0, 63)
            np.add.at(hog_hist, bin_idx, weights)
            hog_hist /= wsum  # 归一化概率密度

    # HSV 色相直方图 (36bin = 每10°一格, + 饱和度权重 避免近灰近白扰动)
    hsv_hist = np.zeros((36,), dtype=np.float32)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)  # H 0-179 (OpenCV), S 0-255, V 0-255
    if fg_mask_canvas_bool.sum() >= 9:
        Harr = hsv[..., 0][fg_mask_canvas_bool].astype(np.float32)
        Sarr = hsv[..., 1][fg_mask_canvas_bool].astype(np.float32)
        Varr = hsv[..., 2][fg_mask_canvas_bool].astype(np.float32)
        # 仅统计"不是灰度"(色相较稳定) + "不是全黑全白"的像素: S>=25, V>20, V<245
        valid = (Sarr >= 25) & (Varr > 20) & (Varr < 245)
        if valid.sum() >= 4:
            bins = np.clip((Harr[valid] / 180.0 * 36).astype(np.int32), 0, 35)
            wts = Sarr[valid]  # 饱和度高更信
            np.add.at(hsv_hist, bins, wts)
            ws = float(hsv_hist.sum())
            if ws > 1e-3: hsv_hist /= ws

    # LAB ab 平面色相直方图 (24bin, 抗光照影响, 因为 L 通道分离)
    lab_hist = np.zeros((24,), dtype=np.float32)
    if fg_mask_canvas_bool.sum() >= 9:
        lab3 = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        a = lab3[..., 1][fg_mask_canvas_bool].astype(np.float32) - 128.0  # -128~127
        b = lab3[..., 2][fg_mask_canvas_bool].astype(np.float32) - 128.0
        r = np.sqrt(a*a + b*b)
        # 只看色相差点足够大的 (r>=10 意味着远离灰色中心)
        valid = r >= 10.0
        if valid.sum() >= 4:
            ang_ab = (np.arctan2(b[valid], a[valid]) * 180.0 / np.pi) % 360.0
            bins = np.clip((ang_ab / 360.0 * 24).astype(np.int32), 0, 23)
            wts = r[valid]  # 越远离中心越信
            np.add.at(lab_hist, bins, wts)
            ws = float(lab_hist.sum())
            if ws > 1e-3: lab_hist /= ws

    return {
        "bgr": bgr, "gray": gray, "edge": edge,
        "sobel": sobel, "fg_mask": fg_mask_canvas_bool,
        "hog_hist": hog_hist,     # shape=(64,) float32 L1归一化
        "hsv_hist": hsv_hist,     # shape=(36,) float32 L1归一化
        "lab_hist": lab_hist,     # shape=(24,) float32 L1归一化
    }


def preproc_for_match(img_bgr):
    """统一 pipeline: BGR/RGBA numpy → 标准化 dict.  是整个识别的核心.
    v4 改进: 不再预合成白底 (会破坏 PVP 深蓝背景的统计), 直接在原图上抠图,
             最后贴纯白画布自然得到白底.
    """
    if img_bgr is None or img_bgr.size == 0:
        return None
    ch = img_bgr.shape[2]
    # 1) 如果是 RGBA, 保留一份"合成白底的 BGR" 给后续 _center_and_scale 贴像素用 (否则透明变成黑/白不确定)
    #    同时把 RGBA 传给 _floodfill_background 用 alpha 通道精准抠图
    if ch == 4:
        # 合成白底 (供最终贴像素)
        pil_src = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGRA2RGBA))
        bg = Image.new("RGBA", pil_src.size, (255, 255, 255, 255))
        composed = Image.alpha_composite(bg, pil_src).convert("RGB")
        bgr_white = cv2.cvtColor(np.asarray(composed, dtype=np.uint8), cv2.COLOR_RGB2BGR)
        img_for_mask = img_bgr  # RGBA, _floodfill_background 会用 alpha 通道
    else:
        bgr_white = img_bgr  # 3 通道直接用
        img_for_mask = img_bgr
    # 2) 抠背景 (v4 亮度阈值 + 连通域)
    bg_mask = _floodfill_background(img_for_mask)
    # 3) 取前景 = 非背景 的最大连通域
    fg = _largest_foreground_component(~bg_mask)
    # 4) 前景居中 + 缩放贴到 64x64 纯白画布 (统一白底)
    return _center_and_scale(fg, bgr_white, CANVAS, FG_HEIGHT)


# ==========================================================
# A. Baseline: pHash(64) + dHash(64) (在标准化 64x64 灰度上重算, 与之前算法一致, 只是 resize 源图换成标准化后的 64x64)
# 这里还是用 32x32 输入, 把标准化后的 gray64 再缩到 32x32 做 pHash —— 至少背景一致了
# ==========================================================
N_PH, K_PH = 32, 8
_C_DCT_MAT = None
def _dct_matrix(n):
    global _C_DCT_MAT
    if _C_DCT_MAT is None or _C_DCT_MAT.shape != (n, n):
        k = np.arange(n).reshape(-1, 1); m = np.arange(n).reshape(1, -1)
        C = np.cos(np.pi * (2 * m + 1) * k / (2 * n))
        C[0, :] *= np.sqrt(1.0 / n); C[1:, :] *= np.sqrt(2.0 / n)
        _C_DCT_MAT = C
    return _C_DCT_MAT

def compute_phash_dhash_from_gray64(gray64_uint8):
    """输入: 标准化后的 64x64 灰度 uint8.  比从 BGR 重新合成要快."""
    if gray64_uint8 is None:
        return "0" * 16, "0" * 16
    pil32 = Image.fromarray(gray64_uint8, mode="L").resize((N_PH, N_PH), Image.LANCZOS)
    g32 = np.asarray(pil32, dtype=np.float64)
    C = _dct_matrix(N_PH)
    dct = C @ g32 @ C.T
    coeffs = dct[:K_PH, :K_PH].flatten()[1:]
    med = np.median(coeffs)
    bits = "".join("1" if v > med else "0" for v in coeffs) + "0"
    ph = format(int(bits, 2), "016x")
    pil9 = pil32.resize((9, 8), Image.LANCZOS)
    a9 = np.asarray(pil9, dtype=np.float64)
    bits_d = ""
    for row in a9:
        for x in range(8):
            bits_d += "1" if row[x] > row[x + 1] else "0"
    dh = format(int(bits_d, 2), "016x")
    return ph, dh

def hamming_sum(ph1, dh1, ph2, dh2):
    return bin(int(ph1, 16) ^ int(ph2, 16)).count("1") + bin(int(dh1, 16) ^ int(dh2, 16)).count("1")


# ==========================================================
# B. ORB 局部特征 —— 用标准化后的 64x64 灰度, 前景 mask 做 mask=参数限制 ORB 只在前景找关键点!
# ==========================================================
ORB_DET = cv2.ORB_create(
    nfeatures=1500,
    scaleFactor=1.12,
    nlevels=8,
    edgeThreshold=4,
    firstLevel=0,
    WTA_K=2,
    scoreType=cv2.ORB_HARRIS_SCORE,
    patchSize=15,
    fastThreshold=10,
)
BF_HAM = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
RATIO = 0.78

def extract_orb_masked(gray64, fg_mask_bool):
    """gray64: 64x64 uint8, fg_mask_bool: 64x64 bool.  只在前景区域找关键点 + 描述子.
    返回 (kp_count, des_array or None)
    """
    if gray64 is None:
        return 0, None
    # mask 需要 uint8, 0/255
    mask = (fg_mask_bool.astype(np.uint8) * 255) if fg_mask_bool is not None else None
    try:
        kp, des = ORB_DET.detectAndCompute(gray64, mask)
    except cv2.error:
        return 0, None
    return len(kp), des

def orb_match_score_raw(query_des, lib_des):
    """返回 good 匹配**绝对数量** (>=0 的整数 + 小 bonus).
    v11 修复: 新增硬性门限 good匹配<3 直接返回 0.0, 避免 1~2 匹配虚高(水蓝蓝1.0)
    含义: >=15 极强命中; 8~14 中等命中; 3~7 弱命中; <3 不相关.
    """
    if query_des is None or lib_des is None:
        return 0.0
    if len(query_des) < 2 or len(lib_des) < 2:
        return 0.0
    try:
        matches = BF_HAM.knnMatch(query_des, lib_des, k=2)
    except cv2.error:
        return 0.0
    good = []
    for pair in matches:
        if len(pair) < 2: continue
        m, n = pair
        if m.distance < RATIO * n.distance:
            good.append(m)
    ng = len(good)
    if ng < 3:  # v11 硬性门限
        return 0.0
    avg_dist = float(np.mean([m.distance for m in good]))
    # 距离奖励: 平均距离越小越可信 (范围 10~50 → 奖励 0~1.2)
    dist_bonus = max(0.0, (55 - avg_dist) / 45.0) * min(3.0, ng / 4.0)
    return float(ng) + dist_bonus


# ==========================================================
# C. 双路 masked 模板匹配 (前景像素才参与)
# ==========================================================
def _masked_score(arr_a, arr_b, mask_union):
    """两个 float32 图在 mask_union (bool) 上的归一化相关系数 [-1, 1]."""
    if mask_union.sum() < 40:
        return -1.0
    va = arr_a[mask_union].astype(np.float32)
    vb = arr_b[mask_union].astype(np.float32)
    sa = va.std(); sb = vb.std()
    if sa < 1e-4 or sb < 1e-4:
        return -1.0
    return float(np.corrcoef(va, vb)[0, 1])

def masked_template_sobel_score(pp_q, pp_l):
    """返回 (tmpl_corr, sobel_corr).  都在 [PVP_fg ∪ Lib_fg] 像素上算 Pearson 相关.
    tmpl 用 灰度 (0.3 权重), sobel 用梯度幅度 (0.7 权重 —— 形状纹理优先, 异色炫彩不怕)
    """
    if pp_q is None or pp_l is None:
        return -1.0, -1.0
    union = pp_q["fg_mask"] | pp_l["fg_mask"]
    inter = pp_q["fg_mask"] & pp_l["fg_mask"]
    # 前景交集太小 (< 30 像素) 说明前景完全不重叠, 大概率不是同一只
    if inter.sum() < 25 or union.sum() < 60:
        return -1.0, -1.0
    # 灰度相关
    gcorr = _masked_score(pp_q["gray"], pp_l["gray"], union)
    # 梯度幅度相关
    scorr = _masked_score(pp_q["sobel"], pp_l["sobel"], union)
    return gcorr, scorr


# ==========================================================
# D. HOG / HSV / LAB 直方图特征 (v11 新增: 抗颜色变换, 形状色相独立匹配)
# ==========================================================
def _hist_cosine(a, b):
    """两个 L1 归一化向量的 cosine 相似度. 范围 [0,1] 越大越像."""
    if a is None or b is None: return 0.0
    na = np.asarray(a, dtype=np.float32).flatten()
    nb = np.asarray(b, dtype=np.float32).flatten()
    if na.shape != nb.shape: return 0.0
    denom = float(np.linalg.norm(na) * np.linalg.norm(nb))
    if denom < 1e-6: return 0.0
    return float(np.clip((na @ nb) / denom, 0.0, 1.0))

def _chi2_sim(a, b):
    """χ² 距离 → 相似度. chi²越大越不像, sim = 1 / (1 + chi²).
    对颜色/直方图分布差更鲁棒.
    """
    if a is None or b is None: return 0.0
    na = np.asarray(a, dtype=np.float32).flatten()
    nb = np.asarray(b, dtype=np.float32).flatten()
    if na.shape != nb.shape: return 0.0
    # 只统计两边都有贡献的 bin
    sm = na + nb
    df = na - nb
    valid = sm > 1e-6
    if not valid.any(): return 1.0  # 两边都是空(全灰/无色) => 完美相似
    chi2 = float(((df[valid]**2) / sm[valid]).sum() * 0.5)
    return float(1.0 / (1.0 + chi2))

def hist_similarity(q_pp, l_pp):
    """综合 HOG + HSV + LAB 直方图的相似度, 返回 (hog, hsv, lab, combined) ∈ [0,1]"""
    if q_pp is None or l_pp is None:
        return 0.0, 0.0, 0.0, 0.0
    hog = 0.6 * _hist_cosine(q_pp["hog_hist"], l_pp["hog_hist"]) + 0.4 * _chi2_sim(q_pp["hog_hist"], l_pp["hog_hist"])
    hsv = 0.6 * _hist_cosine(q_pp["hsv_hist"], l_pp["hsv_hist"]) + 0.4 * _chi2_sim(q_pp["hsv_hist"], l_pp["hsv_hist"])
    lab = 0.6 * _hist_cosine(q_pp["lab_hist"], l_pp["lab_hist"]) + 0.4 * _chi2_sim(q_pp["lab_hist"], l_pp["lab_hist"])
    # HOG 形状优先(抗异色炫彩). 色相为辅助.
    combined = 0.50 * hog + 0.28 * hsv + 0.22 * lab
    return float(hog), float(hsv), float(lab), float(combined)

def topn_hists(q_pp, lib, n=5):
    out = []
    for e in lib:
        hg, hs, hl, c = hist_similarity(q_pp, e["pp"])
        out.append((c, hg, hs, hl, e))
    out.sort(key=lambda r: r[0], reverse=True)
    top = []
    for c, hg, hs, hl, e in out[:n]:
        top.append({"seq": e["seq"], "name": e["name"], "src": e["src"],
                    "raw_score": float(c),
                    "hog": round(hg, 3), "hsv": round(hs, 3), "lab": round(hl, 3),
                    "norm_score": float(c)})  # 本身已经 0~1
    return top


# ==========================================================
# 特征库 (只加载 ingame_avatars —— 域一致!)
# ==========================================================
class FeatureLibrary:
    def __init__(self, ingame_only=True):
        self.ingame_only = ingame_only
        self.entries = []
        self._seq_to_idx = {}

    def add_one(self, seq, name, img_bgr, src_tag, src_path):
        pp = preproc_for_match(img_bgr)
        if pp is None:
            return
        ph, dh = compute_phash_dhash_from_gray64(pp["gray"])
        kpn, des = extract_orb_masked(pp["gray"], pp["fg_mask"])
        idx = len(self.entries)
        self.entries.append({
            "idx": idx,
            "seq": int(seq), "name": str(name),
            "phash": ph, "dhash": dh,
            "orb_kpn": kpn, "orb_des": des,
            "pp": pp,  # gray/edge/sobel/fg_mask
            "src": src_tag, "path": str(src_path),
        })
        # 同 seq 后加载覆盖前者 (ingame_only=True 不会触发, 但写着安全)
        self._seq_to_idx[int(seq)] = idx

    def build(self):
        t0 = time.time()
        # 1) ingame_avatars/images (主库, 唯一)
        ingame_dir = SCRIPT_DIR / "output" / "ingame_avatars" / "images"
        n_ingame = 0
        if ingame_dir.exists():
            for fp in sorted(ingame_dir.glob("*.png")):
                m = re.match(r'^(\d+)_(.+)\.png$', fp.name)
                if not m: continue
                seq, name = int(m.group(1)), m.group(2)
                img = imread_unicode(str(fp))
                if img is None: continue
                self.add_one(seq, name, img, "ingame", fp)
                n_ingame += 1
        # 2) 可选 wiki 补充
        n_wiki = 0
        if not self.ingame_only:
            wiki_dir = SCRIPT_DIR / "output" / "avatar" / "images"
            if wiki_dir.exists():
                for fp in sorted(wiki_dir.glob("*.png")):
                    m = re.match(r'^(\d+)_(.+)\.png$', fp.name)
                    if not m: continue
                    seq = int(m.group(1))
                    if seq in self._seq_to_idx: continue
                    img = imread_unicode(str(fp))
                    if img is None: continue
                    self.add_one(seq, m.group(2), img, "wiki", fp)
                    n_wiki += 1
        print(f"[lib] ingame={n_ingame} wiki(补充)={n_wiki} → 共 {len(self.entries)} 条  "
              f"({time.time()-t0:.1f}s)")
        self.n_ingame = n_ingame
        self.n_wiki = n_wiki
        return self.entries


# ==========================================================
# PVP 行配对 / 头像裁切 (与 v2 完全一致, 不改动)
# ==========================================================
RE_LV = re.compile(r'^\s*(\d+)\s*级\s*$')

def pair_pvp_rows(ocr_lines):
    parsed = []
    for t, s, p in ocr_lines:
        if not p: continue
        x0, x1, y0, y1 = poly_box(p)
        is_lv = bool(RE_LV.fullmatch(t))
        score = float(s)
        # --- 过滤噪声 ---
        # 1) 非等级行, 文本长度<=1 (如单个字母O, 数字1, 标点等OCR噪声)
        if not is_lv and len(t.strip()) <= 1: continue
        # 2) 非等级行, 置信度低于 0.3 (OCR自己也不相信的噪声)
        if not is_lv and score < 0.3: continue
        parsed.append({
            "txt": t, "score": score, "poly": p,
            "x0": x0, "x1": x1, "y0": y0, "y1": y1,
            "cy": (y0 + y1) // 2, "h": max(y1 - y0, 1),
            "is_lv": is_lv,
        })
    parsed.sort(key=lambda r: (r["y0"], r["x0"]))
    used = [False] * len(parsed)
    rows = []
    for i, r in enumerate(parsed):
        if used[i] or r["is_lv"]: continue
        best_j = None; best_score = 1e9
        for j in range(i + 1, len(parsed)):
            if used[j] or not parsed[j]["is_lv"]: continue
            rj = parsed[j]
            if rj["y0"] < r["y1"] - 2 or rj["y0"] > r["y1"] + 60: continue
            dx = abs(r["x0"] - rj["x0"])
            if dx > 80: continue
            sc = rj["y0"] - r["y1"] + 0.1 * dx
            if sc < best_score: best_score = sc; best_j = j
        if best_j is not None:
            used[i] = used[best_j] = True
            rr = parsed[best_j]
            name_cy = (r["y0"] + r["y1"]) // 2
            pair_height = max(rr["y1"] - r["y0"], 1)
            rows.append({
                "name_txt": r["txt"], "name_score": r["score"],
                "name_poly": r["poly"],
                "name_box": (r["x0"], r["y0"], r["x1"], r["y1"]),
                "name_cy": name_cy, "name_h": r["h"], "pair_h": pair_height,
                "lv_txt": rr["txt"], "lv_score": rr["score"],
                "lv_poly": rr["poly"],
                "lv_box": (rr["x0"], rr["y0"], rr["x1"], rr["y1"]),
                "y0": r["y0"] - r["h"] // 4, "y1": rr["y1"] + rr["h"] // 4,
            })
            continue
        used[i] = True
        name_cy = (r["y0"] + r["y1"]) // 2
        rows.append({
            "name_txt": r["txt"], "name_score": r["score"],
            "name_poly": r["poly"],
            "name_box": (r["x0"], r["y0"], r["x1"], r["y1"]),
            "name_cy": name_cy, "name_h": r["h"], "pair_h": r["h"] * 3,
            "lv_txt": None, "lv_score": 0.0, "lv_poly": None, "lv_box": None,
            "y0": r["y0"] - r["h"] // 2, "y1": r["y1"] + r["h"],
        })
    if rows:
        hs = sorted(r["y1"] - r["y0"] for r in rows)
        med_h = hs[len(hs) // 2]
    else:
        med_h = 60
    rows.sort(key=lambda r: r["y0"])
    for r in rows:
        r["row_h"] = max(r["y1"] - r["y0"], med_h)
    return rows

def crop_pvp_avatar(img_np_bgr, pet_row):
    H, W = img_np_bgr.shape[:2]
    cy = int(pet_row["name_cy"])
    name_h = int(pet_row.get("name_h", pet_row["row_h"]))
    pair_h = int(pet_row.get("pair_h", pet_row["row_h"]))
    size = int(max(pair_h * 1.05, name_h * 2.2))
    size = max(size, 48)
    ay0 = max(0, cy - size // 2); ay1 = min(H, ay0 + size)
    ay0 = max(0, ay1 - size)
    pad_right = max(4, W // 80)
    ax1 = W - pad_right; ax0 = max(0, ax1 - size)
    ax1 = min(W, ax0 + size); ax0 = max(0, ax1 - size)
    if ax1 - ax0 < 16 or ay1 - ay0 < 16:
        return None, (int(ax0), int(ay0), int(ax1), int(ay1))
    crop = img_np_bgr[ay0:ay1, ax0:ax1]
    if crop.size == 0: return None, (0, 0, 0, 0)
    return crop, (int(ax0), int(ay0), int(ax1), int(ay1))

def draw_debug(img_bgr, rows, labels, avatars_boxes, out_path):
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(img_rgb).convert("RGB")
    draw = ImageDraw.Draw(pil)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 16)
    except Exception:
        font = ImageFont.load_default()
    for r, lbl, ab in zip(rows, labels, avatars_boxes):
        x0,y0,x1,y1 = r["name_box"]
        draw.rectangle([x0,y0,x1,y1], outline=(220,40,40), width=2)
        if r["lv_box"]:
            x0,y0,x1,y1 = r["lv_box"]
            draw.rectangle([x0,y0,x1,y1], outline=(220,120,40), width=1)
        ax0,ay0,ax1,ay1 = ab
        draw.rectangle([ax0,ay0,ax1,ay1], outline=(30,200,60), width=2)
        tx, ty = max(2, ax0 - 2), max(0, ay0 - 18)
        tw, th = draw.textbbox((0,0), lbl, font=font)[2:]
        draw.rectangle([tx, ty, tx+tw+6, ty+th+4], fill=(20,60,200,220))
        draw.text((tx+3, ty+2), lbl, fill=(255,255,255), font=font)
    pil.convert("RGB").save(out_path, "JPEG", quality=88)


# ==========================================================
# TopN 选择
# ==========================================================
def topn_hash(q_ph, q_dh, lib, n=5):
    out = [(hamming_sum(q_ph, q_dh, e["phash"], e["dhash"]), e) for e in lib]
    out.sort(key=lambda r: r[0])  # 越小越好
    top = []
    for d, e in out[:n]:
        top.append({"seq": e["seq"], "name": e["name"], "src": e["src"],
                    "raw_score": float(d),
                    "norm_score": float(max(0.0, 1 - d / 128.0))})
    return top

# ORB 得分归一化: 固定量程 0~30 (超过 30 也按 1.0 算)
ORB_MAX_SCORE = 30.0
def topn_orb(q_des, lib, n=5):
    out = []
    for e in lib:
        s = orb_match_score_raw(q_des, e["orb_des"])
        out.append((s, e))
    out.sort(key=lambda r: r[0], reverse=True)
    top = []
    for s, e in out[:n]:
        top.append({"seq": e["seq"], "name": e["name"], "src": e["src"],
                    "raw_score": float(s),
                    "norm_score": float(min(1.0, s / ORB_MAX_SCORE))})
    return top

# tmpl + sobel 合并为一个 norm_score = 0.30*gcorr + 0.70*scorr
# 相关系数范围 [-1, 1], 归一化: (x+1)/2 → [0,1]
def _norm_corr(c): return float(max(0.0, min(1.0, (c + 1.0) / 2.0)))

def topn_masked_template_sobel(q_pp, lib, n=5):
    out = []
    for e in lib:
        g, s = masked_template_sobel_score(q_pp, e["pp"])
        combined_raw = 0.30 * g + 0.70 * s
        out.append((combined_raw, g, s, e))
    out.sort(key=lambda r: r[0], reverse=True)
    top = []
    for comb, g, s, e in out[:n]:
        top.append({"seq": e["seq"], "name": e["name"], "src": e["src"],
                    "raw_score": float(comb),
                    "gray_corr": float(g), "sobel_corr": float(s),
                    "norm_score": _norm_corr(comb)})
    return top


def fusion_topn(th, to, ttm, tht, n=5):
    """v11 融合 (5路).
    新增权重: hists=0.55 (HOG形状 + HSV色相 + LAB色相, 抗异色/炫彩/色偏)
    旧算法权重降格为辅助: tmpl=0.15 ORB=0.15 pHash=0.05, 保留排名奖励
    """
    W = {"phash": 0.05, "orb": 0.15, "tmpl": 0.15, "hists": 0.55}
    RANK_BONUS = 0.05  # 排名奖励
    agg = {}
    for src_name, lst in (("phash", th), ("orb", to), ("tmpl", ttm), ("hists", tht)):
        w = W[src_name]
        for rank, t in enumerate(lst):
            key = t["seq"]
            bonus = max(0.0, (5 - rank)) * RANK_BONUS * (2.0 if src_name == "hists" else 1.0)
            score = t["norm_score"] * w + bonus
            if key not in agg:
                agg[key] = {"seq": t["seq"], "name": t["name"], "src": t["src"],
                            "_score": 0.0, "components": {}}
            agg[key]["_score"] += score
            agg[key]["components"][src_name] = {
                "raw_score": t["raw_score"], "norm_score": t["norm_score"], "rank": rank + 1
            }
    arr = sorted(agg.values(), key=lambda x: x["_score"], reverse=True)
    out = []
    for a in arr[:n]:
        s = a.pop("_score")
        a["fusion_score"] = float(s)
        # 理论上限 ≈ 0.05+0.15+0.15+0.55 + 0.25(hists)= 1.15, 归一
        a["norm_score"] = float(min(1.0, s / 1.10))
        out.append(a)
    return out


def check_hit(top_list, gt_seq):
    if not gt_seq or not top_list: return False, False, False
    return (top_list[0]["seq"] == gt_seq,
            any(t["seq"] == gt_seq for t in top_list[:3]),
            any(t["seq"] == gt_seq for t in top_list))

def imwrite_unicode(path, img_bgr):
    ext = Path(path).suffix
    ok, buf = cv2.imencode(ext, img_bgr)
    if ok: buf.tofile(str(path))


# ==========================================================
# 主流程
# ==========================================================
def main(pvp_dir: Path):
    files = sorted(pvp_dir.glob("*.png"))
    print(f"[scan] PVP截图 {len(files)} 张 @ {pvp_dir}")
    if not files:
        print("[error] 目录无 PNG"); return

    t00 = time.time()
    ocr = init_ocr()
    titles = load_titles()
    _fl = FeatureLibrary(ingame_only=False)
    lib = _fl.build()
    if not lib:
        print("[error] 特征库空, 先跑 build_ingame_dataset.py"); return

    all_records = []
    global_pet_counter = 0

    for idx, fp in enumerate(files):
        print(f"\n[{idx+1}/{len(files)}] {fp.name}")
        img = imread_unicode(str(fp))
        if img is None: print("  跳过: 无法读取"); continue
        lines = run_ocr(ocr, str(fp))
        rows = pair_pvp_rows(lines)
        print(f"  OCR {len(lines)} 行 → {len(rows)} 精灵行对")

        labels_list = []; avatar_boxes = []

        for ri, pr in enumerate(rows):
            gt = None
            m_ocr = best_match(pr["name_txt"], titles)
            if m_ocr:
                title, seq, pet_id, d_ocr = m_ocr
                gt = {"seq": seq, "name": title, "ocr_dist": d_ocr, "ocr_raw": pr["name_txt"]}
            crop, av_box = crop_pvp_avatar(img, pr)
            avatar_boxes.append(av_box)

            rec = {"src": fp.name, "row": ri, "gt": gt,
                   "ocr_raw": pr["name_txt"], "ocr_score": pr["name_score"],
                   "lv_raw": pr["lv_txt"], "lv_score": pr["lv_score"],
                   "avatar_box": list(av_box), "crop_size": None, "avatar_file": None}

            if crop is None:
                labels_list.append(f"{ri}:裁失败 '{pr['name_txt']}'")
                for k in ("phash", "orb", "tmpl", "fusion"):
                    rec[f"top_{k}"] = []
                    rec[f"top1_{k}"] = rec[f"top3_{k}"] = rec[f"top5_{k}"] = False
                all_records.append(rec); continue

            global_pet_counter += 1
            fs = f"{idx+1:02d}_{ri+1}"
            stem = f"{gt['seq']:03d}_{gt['name']}" if gt else "unknown"
            cname = f"{fs}_{stem}.png"; cpath = CROP_DIR / cname
            imwrite_unicode(str(cpath), crop)
            h, w = crop.shape[:2]
            rec["crop_size"] = [w, h]; rec["avatar_file"] = f"crops/{cname}"

            # --- 标准化预处理 ---
            q_pp = preproc_for_match(crop)
            if q_pp is None:
                labels_list.append(f"{ri}:预处理失败 '{pr['name_txt']}'")
                all_records.append(rec); continue
            q_ph, q_dh = compute_phash_dhash_from_gray64(q_pp["gray"])
            _, q_orb_des = extract_orb_masked(q_pp["gray"], q_pp["fg_mask"])

            # --- 4 算法 + 融合 ---
            th = topn_hash(q_ph, q_dh, lib, n=5)
            to = topn_orb(q_orb_des, lib, n=5)
            tt = topn_masked_template_sobel(q_pp, lib, n=5)
            tht = topn_hists(q_pp, lib, n=5)       # v11 HOG+HSV+LAB
            fu = fusion_topn(th, to, tt, tht, n=5)  # v11 传入 tht

            gt_seq = gt["seq"] if gt else None
            for k, lst in (("phash", th), ("orb", to), ("tmpl", tt), ("hists", tht), ("fusion", fu)):
                t1, t3, t5 = check_hit(lst, gt_seq)
                rec[f"top_{k}"] = lst
                rec[f"top1_{k}"], rec[f"top3_{k}"], rec[f"top5_{k}"] = t1, t3, t5

            # --- 诊断标签 (融合结果) ---
            fu0 = fu[0] if fu else None
            if gt:
                mark = "✔" if rec["top1_fusion"] else ("◷" if rec["top3_fusion"] else "✘")
                pred = f"{fu0['name']}(s={fu0['fusion_score']:.2f})" if fu0 else "-"
                lbl = f"{ri}{mark} {pr['name_txt']}→{gt['name']}  Fus={pred}"
            else:
                pred = f"{fu0['name']}(s={fu0['fusion_score']:.2f})" if fu0 else "-"
                lbl = f"{ri} ❓ '{pr['name_txt']}' Fus={pred}"
            labels_list.append(lbl)
            all_records.append(rec)

            # --- 单行日志 ---
            gt_s = f"seq={gt['seq']} {gt['name']}" if gt else "无GT"
            def _top1(t, f="norm_score"):
                if not t: return ("-", 0.0)
                return (t[0]["name"], round(t[0].get("fusion_score", t[0].get(f, 0)), 3))
            hp, hs = _top1(th); op, os_ = _top1(to); tp, ts = _top1(tt)
            hgp, hgs = _top1(tht)   # v11 hists
            fup, fus = (fu[0]["name"], round(fu[0]["fusion_score"], 3)) if fu else ("-", 0)
            def _m(k):
                return "✔" if rec[f"top1_{k}"] else ("◷" if rec[f"top3_{k}"] else "✘")
            print(f"    [{ri}] {_m('fusion')} GT={gt_s}")
            print(f"         pHash{_m('phash')}:{hp}({hs:.2f})  ORB{_m('orb')}:{op}({os_:.2f})  "
                  f"Tmpl{_m('tmpl')}:{tp}({ts:.2f})  Hist{_m('hists')}:{hgp}({hgs:.2f})  "
                  f"Fus{_m('fusion')}:{fup}({fus:.2f})")

        dbg_path = DBG_DIR / f"{fp.stem}_debug.jpg"
        draw_debug(img, rows, labels_list, avatar_boxes, str(dbg_path))
        print(f"  诊断图 -> {dbg_path}")

    # ==========================================================
    # 汇总
    # ==========================================================
    with_gt = [r for r in all_records if r.get("gt")]
    seqs_in_lib = set(e["seq"] for e in lib)
    covered = [r for r in with_gt if r["gt"]["seq"] in seqs_in_lib]
    missing = [r for r in with_gt if r["gt"]["seq"] not in seqs_in_lib]

    def _stat(subset, label):
        L = [f"\n==== 统计范围: {label} (n={len(subset)}) ===="]
        for k in ("phash", "orb", "tmpl", "hists", "fusion"):
            t1 = sum(1 for r in subset if r[f"top1_{k}"])
            t3 = sum(1 for r in subset if r[f"top3_{k}"])
            t5 = sum(1 for r in subset if r[f"top5_{k}"])
            tot = max(1, len(subset))
            L.append(f"  [{k:>6s}] Top1={t1:3d}/{tot} = {100*t1/tot:5.1f}%   "
                     f"Top3={t3:3d}/{tot} = {100*t3/tot:5.1f}%   "
                     f"Top5={t5:3d}/{tot} = {100*t5/tot:5.1f}%")
        return L

    rep = []
    rep.append("=" * 64)
    rep.append("PVP 头像识别评估报告 (v6 — GrabCut 抠图+标准化+ingame+wiki补充)")
    rep.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    rep.append(f"PVP 截图: {len(files)} 张, 裁切头像: {global_pet_counter} 只")
    rep.append(f"特征库规模: {len(lib)} 只 (ingame={_fl.n_ingame}, wiki补充={_fl.n_wiki})")
    rep.append(f"OCR+模糊匹配有 GT: {len(with_gt)}/{len(all_records)}")
    rep.append(f"GT 在特征库内: {len(covered)} 只  (特征库缺失: {len(missing)} 只)")
    rep.extend(_stat(with_gt, "全部带 GT 样本"))
    rep.extend(_stat(covered, "仅 GT 在特征库内的样本 (公平测)"))

    if missing:
        rep.append("\n【GT 不在特征库】(补充 ingame 截图即可提升召回)")
        for r in missing:
            rep.append(f"  {r['src']}[{r['row']}] seq={r['gt']['seq']} "
                        f"{r['gt']['name']}  OCR='{r['ocr_raw']}'")

    missed = [r for r in covered if not r["top5_fusion"]]
    if missed:
        rep.append(f"\n【融合 Top5 未命中】({len(missed)} 例)")
        for r in missed:
            rep.append(f"  ── {r['src']}[{r['row']}] GT=seq{r['gt']['seq']}/"
                        f"{r['gt']['name']}  OCR='{r['ocr_raw']}'")
            for k in ("phash", "orb", "tmpl", "hists", "fusion"):
                top = r[f"top_{k}"]
                t3 = [(t["seq"], t["name"], round(t.get("fusion_score",
                        t.get("norm_score", t.get("raw_score", 0))), 3)) for t in top[:3]]
                rep.append(f"     {k:>6s} Top3: {t3}")

    saved = [r for r in covered if r["top1_fusion"] and
             not r["top1_orb"] and not r["top1_tmpl"] and not r["top1_phash"] and not r["top1_hists"]]
    if saved:
        rep.append(f"\n【融合救活】(单一 Top1 均未中, 融合 Top1 命中) n={len(saved)}")
        for r in saved:
            rep.append(f"  {r['src']}[{r['row']}] GT=seq{r['gt']['seq']}/{r['gt']['name']}")

    # 单独: ORB 或 Tmpl 或 HISTS 至少一种 Top3 命中的"或集"命中率
    if covered:
        or_hit1 = sum(1 for r in covered if r["top1_orb"] or r["top1_tmpl"] or r["top1_hists"])
        or_hit3 = sum(1 for r in covered if r["top3_orb"] or r["top3_tmpl"] or r["top3_hists"])
        or_hit5 = sum(1 for r in covered if r["top5_orb"] or r["top5_tmpl"] or r["top5_hists"])
        rep.append(f"\n【ORB ∪ Tmpl ∪ Hists 联合】(纯图像: 至少一种算法命中)")
        tot = len(covered)
        rep.append(f"  Top1={or_hit1}/{tot} = {100*or_hit1/tot:.1f}%   "
                   f"Top3={or_hit3}/{tot} = {100*or_hit3/tot:.1f}%   "
                   f"Top5={or_hit5}/{tot} = {100*or_hit5/tot:.1f}%")

    report_txt = "\n".join(rep)
    print(report_txt)
    (OUT_DIR / "report.txt").write_text(report_txt, encoding="utf-8")
    (OUT_DIR / "eval.json").write_text(
        json.dumps({
            "generated_with": "eval_pvp_recognition.py v3",
            "src_dir": str(pvp_dir),
            "lib_size": len(lib),
            "canvas_px": CANVAS, "fg_height_px": FG_HEIGHT,
            "weights_fusion": {"phash":0.10,"orb":0.30,"tmpl":0.45,"tmpl_rank_bonus":1.5},
            "orb_range": ORB_MAX_SCORE,
            "count": len(all_records), "gt_count": len(with_gt),
            "gt_in_lib_count": len(covered),
            "records": all_records,
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n总耗时: {time.time()-t00:.1f}s")
    print(f"输出: {OUT_DIR}")
    print(f"  report.txt -> {OUT_DIR / 'report.txt'}")
    print(f"  eval.json   -> {OUT_DIR / 'eval.json'}")
    print(f"  crops/      -> {CROP_DIR}")
    print(f"  debug/      -> {DBG_DIR}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        default = PROJECT_ROOT / "pvp素材"
        print(f"[hint] python eval_pvp_recognition.py <pvp截图目录> (默认: {default})")
        target = default
    else:
        target = Path(sys.argv[1])
    main(target)
