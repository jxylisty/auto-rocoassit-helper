# -*- coding: utf-8 -*-
"""
拟人化输入层 - 统一走 Interception 内核驱动,叠加人类行为特征

反统计检测的三件事:
1. 按键时长随机(每次按住 50~220ms 高斯波动,不是恒定瞬间)
2. 间隔分布拟人(高斯为主 + 偶发"分心"长停顿,不是均匀分布)
3. 鼠标移动多段化(加减速曲线 + 抖动 + 轻微过冲回修,不是一次大跳变)

本模块只做"计划"(纯函数,可离线测试)和"执行"(调 interception)。
"""

from __future__ import annotations

import math
import random


# ========================================
# 纯计划函数(不执行,可单测)
# ========================================

def plan_key_hold() -> float:
    """一次按键的自然按住时长(秒)"""
    return max(0.05, min(0.22, random.gauss(0.09, 0.035)))


def plan_delay(lo: float, hi: float) -> float:
    """操作间隔:高斯分布为主,偶发分心长停顿"""
    mid = (lo + hi) / 2
    sigma = max(0.05, (hi - lo) / 4)
    value = random.gauss(mid, sigma)
    value = max(lo, min(hi, value))
    # 8% 概率"分心":明显更长的反应延迟
    if random.random() < 0.08:
        value = min(hi * 3.5, value * random.uniform(1.8, 3.2))
    return value


def plan_mouse_move(dx: float, dy: float = 0.0) -> list[tuple[float, float, float]]:
    """规划一段拟人鼠标移动,返回 [(step_dx, step_dy, sleep_s), ...]

    特征:
    - 距离越长耗时越长(约 0.15~0.8s),步数 10~24
    - 速度曲线:缓入缓出(正弦钟形) + ±15% 逐步抖动
    - 20% 概率轻微过冲(1~4%),再花 1~2 小步修正回来
    """
    distance = math.hypot(dx, dy)
    if distance < 1:
        return []

    duration = 0.15 + (distance / 1600.0) * random.uniform(0.8, 1.3)
    duration = min(0.9, duration)
    steps = random.randint(10, 24)

    # 20% 概率过冲
    overshoot = 0.0
    if random.random() < 0.20:
        overshoot = random.uniform(0.01, 0.04) * (1 if dx >= 0 else -1)

    # 正弦钟形速度权重(缓入缓出)
    weights = [math.sin(math.pi * (i + 0.5) / steps) for i in range(steps)]
    weights = [w * random.uniform(0.85, 1.15) for w in weights]  # 逐步抖动
    total = sum(weights) or 1.0

    plan = []
    ux, uy = dx / distance, dy / distance
    target = distance * (1 + overshoot)
    for w in weights:
        step_len = target * w / total
        sleep = duration / steps * random.uniform(0.7, 1.3)
        plan.append((step_len * ux, step_len * uy, sleep))

    # 过冲修正:1~2 小步走回来
    if distance * abs(overshoot) > 2:
        back = -overshoot * distance
        for _ in range(random.randint(1, 2)):
            plan.append((back / 2 * ux, back / 2 * uy, random.uniform(0.03, 0.08)))
    return plan


# ========================================
# 执行层(调 interception 内核驱动)
# ========================================

def press(key: str) -> None:
    """拟人按键:按住时长随机"""
    import time

    import interception
    interception.key_down(key)
    time.sleep(plan_key_hold())
    interception.key_up(key)


def key_down(key: str) -> None:
    import interception
    interception.key_down(key)


def key_up(key: str) -> None:
    import interception
    interception.key_up(key)


def move_relative(dx: float, dy: float = 0.0) -> None:
    """拟人鼠标移动:按计划的多段小步执行"""
    import time

    import interception
    for step_dx, step_dy, sleep in plan_mouse_move(dx, dy):
        interception.move_relative(int(round(step_dx)), int(round(step_dy)))
        time.sleep(sleep)


def wait(lo: float, hi: float, stop_event=None) -> None:
    """拟人间隔等待(可被停止事件打断)"""
    duration = plan_delay(lo, hi)
    if stop_event is not None:
        stop_event.wait(duration)
    else:
        import time
        time.sleep(duration)
