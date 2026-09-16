# -*- coding: utf-8 -*-
"""
洛克王国：世界 — 天梯赛季永久战报数据库与 ELO 克制分析引擎
打破官方仅保存 20 场的限制，本地持久化存储成百上千场实战对局。
"""

import json
import sqlite3
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DATA_DIR / "history.db"


class HistoryDB:
    """天梯历史战绩数据库管理器"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据表结构"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pvp_matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_time TEXT NOT NULL,
                    result TEXT NOT NULL,
                    my_team TEXT NOT NULL,
                    enemy_team TEXT NOT NULL,
                    enemy_seen_count INTEGER DEFAULT 1,
                    duration_sec INTEGER DEFAULT 0,
                    is_crush INTEGER DEFAULT 0,
                    rank_tier TEXT DEFAULT '天梯排位',
                    notes TEXT DEFAULT ''
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_match_time ON pvp_matches(match_time DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_result ON pvp_matches(result)")
            conn.commit()

    def record_match(
        self,
        result: str,
        my_team: List[Dict[str, Any]],
        enemy_team: List[Dict[str, Any]],
        duration_sec: int = 0,
        rank_tier: str = "天梯排位",
        is_crush: Optional[bool] = None,
        match_time: Optional[str] = None,
        notes: str = ""
    ) -> int:
        """
        录入新战报
        :param result: 'WIN' 或 'LOSS'
        :param my_team: 我方参战精灵列表
        :param enemy_team: 敌方实际出战精灵列表 (1~6只)
        :param duration_sec: 耗时秒数
        :param rank_tier: 段位
        :param is_crush: 是否判定为碾压局（若留空则自动判定：敌方出战<=2只且我方胜利）
        """
        if not match_time:
            match_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        enemy_seen_count = len(enemy_team)
        if is_crush is None:
            is_crush = (result.upper() == "WIN" and enemy_seen_count <= 2)

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO pvp_matches (
                    match_time, result, my_team, enemy_team, 
                    enemy_seen_count, duration_sec, is_crush, rank_tier, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                match_time,
                result.upper(),
                json.dumps(my_team, ensure_ascii=False),
                json.dumps(enemy_team, ensure_ascii=False),
                enemy_seen_count,
                duration_sec,
                1 if is_crush else 0,
                rank_tier,
                notes
            ))
            conn.commit()
            return cursor.lastrowid

    def get_history(self, limit: int = 50, offset: int = 0, filter_result: str = "ALL") -> List[Dict[str, Any]]:
        """分页获取历史战报"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM pvp_matches"
            params = []
            if filter_result.upper() in ("WIN", "LOSS"):
                query += " WHERE result = ?"
                params.append(filter_result.upper())
            elif filter_result.upper() == "CRUSH":
                query += " WHERE is_crush = 1"

            query += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            res = []
            for r in rows:
                item = dict(r)
                item["my_team"] = json.loads(item["my_team"]) if item["my_team"] else []
                item["enemy_team"] = json.loads(item["enemy_team"]) if item["enemy_team"] else []
                item["is_crush"] = bool(item["is_crush"])
                res.append(item)
            return res

    def get_summary_stats(self) -> Dict[str, Any]:
        """计算核心大盘统计（胜率、连胜、碾压数等）"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as total FROM pvp_matches")
            total = cursor.fetchone()["total"]

            if total == 0:
                return {
                    "total": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                    "current_streak": 0, "max_win_streak": 0, "crush_wins": 0,
                    "avg_duration": "0分0秒"
                }

            cursor.execute("SELECT COUNT(*) as wins FROM pvp_matches WHERE result = 'WIN'")
            wins = cursor.fetchone()["wins"]
            losses = total - wins
            win_rate = round((wins / total) * 100, 1)

            cursor.execute("SELECT COUNT(*) as crush FROM pvp_matches WHERE is_crush = 1 AND result = 'WIN'")
            crush_wins = cursor.fetchone()["crush"]

            cursor.execute("SELECT AVG(duration_sec) as avg_d FROM pvp_matches WHERE duration_sec > 0")
            avg_d = cursor.fetchone()["avg_d"] or 0
            avg_min = int(avg_d // 60)
            avg_sec = int(avg_d % 60)
            avg_duration = f"{avg_min}分{avg_sec}秒"

            # 连胜计算 (从最近对局往回倒推)
            cursor.execute("SELECT result FROM pvp_matches ORDER BY id DESC")
            all_results = [row["result"] for row in cursor.fetchall()]

            current_streak = 0
            if all_results:
                first_res = all_results[0]
                for r in all_results:
                    if r == first_res:
                        current_streak += 1 if first_res == "WIN" else -1
                    else:
                        break

            # 历史最高连胜
            max_win_streak = 0
            cur_streak = 0
            for r in reversed(all_results):
                if r == "WIN":
                    cur_streak += 1
                    if cur_streak > max_win_streak:
                        max_win_streak = cur_streak
                else:
                    cur_streak = 0

            return {
                "total": total,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "current_streak": current_streak,
                "max_win_streak": max_win_streak,
                "crush_wins": crush_wins,
                "avg_duration": avg_duration
            }

    def get_elo_counter_stats(self, top_n: int = 6) -> Dict[str, Any]:
        """
        ELO 遇敌克制统计
        - 遇到最频繁的敌方精灵 TOP N (遭遇数、我对战它的胜率)
        - 敌方精灵属性分布占比 (验证是否被系统分配了克制属性)
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT result, enemy_team FROM pvp_matches ORDER BY id DESC LIMIT 200")
            rows = cursor.fetchall()

            pet_stats: Dict[str, Dict[str, Any]] = {}
            attr_counts: Dict[str, int] = {}
            total_enemy_pets = 0

            for row in rows:
                is_win = (row["result"] == "WIN")
                enemy_pets = json.loads(row["enemy_team"]) if row["enemy_team"] else []
                for p in enemy_pets:
                    pname = p.get("name", "").strip()
                    if not pname or pname == "未知":
                        continue
                    total_enemy_pets += 1
                    if pname not in pet_stats:
                        pet_stats[pname] = {"name": pname, "encounters": 0, "wins": 0}
                    pet_stats[pname]["encounters"] += 1
                    if is_win:
                        pet_stats[pname]["wins"] += 1

                    for attr in p.get("types", []):
                        attr_counts[attr] = attr_counts.get(attr, 0) + 1

            sorted_pets = sorted(pet_stats.values(), key=lambda x: x["encounters"], reverse=True)[:top_n]
            for sp in sorted_pets:
                sp["win_rate"] = round((sp["wins"] / sp["encounters"]) * 100, 1)

            total_attrs = sum(attr_counts.values()) or 1
            attr_dist = [
                {
                    "attr": a,
                    "count": c,
                    "pct": round((c / total_attrs) * 100, 1)
                }
                for a, c in sorted(attr_counts.items(), key=lambda x: x[1], reverse=True)[:8]
            ]

            return {
                "top_enemy_pets": sorted_pets,
                "enemy_attr_distribution": attr_dist,
                "sample_matches": len(rows)
            }

    def clear_all(self):
        """清空历史战绩"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM pvp_matches")
            conn.commit()

    def generate_mock_data(self, count: int = 15):
        """生成初始实战演示数据（方便首发体验与界面预览）"""
        import random

        sample_my_pets = [
            {"name": "迪莫", "types": ["光"], "hp_pct": 1.0},
            {"name": "水灵", "types": ["水"], "hp_pct": 0.8},
            {"name": "寂灭骨龙", "types": ["龙", "幽"], "hp_pct": 0.5},
            {"name": "圣尊武王", "types": ["武"], "hp_pct": 1.0},
            {"name": "烈火战神", "types": ["火"], "hp_pct": 0.0},
        ]
        sample_enemies = [
            [{"name": "水灵", "types": ["水"], "hp_pct": 0.0}, {"name": "夜枭", "types": ["翼", "幽"], "hp_pct": 0.0}],
            [{"name": "火魔", "types": ["火"], "hp_pct": 0.0}, {"name": "暴角龙", "types": ["龙", "地"], "hp_pct": 0.0}, {"name": "海皇波塞冬", "types": ["水"], "hp_pct": 0.0}],
            [{"name": "幻鳐", "types": ["幻", "水"], "hp_pct": 0.4}, {"name": "流火蝶", "types": ["火", "虫"], "hp_pct": 0.0}, {"name": "雷霆狮王", "types": ["电"], "hp_pct": 0.0}, {"name": "雪影娃娃", "types": ["冰"], "hp_pct": 0.0}],
            [{"name": "水灵", "types": ["水"], "hp_pct": 0.0}],
            [{"name": "深渊魔王", "types": ["恶", "幽"], "hp_pct": 0.2}, {"name": "离心舞者", "types": ["幻"], "hp_pct": 0.0}, {"name": "海皇波塞冬", "types": ["水"], "hp_pct": 0.0}, {"name": "火魔", "types": ["火"], "hp_pct": 0.0}, {"name": "迪莫", "types": ["光"], "hp_pct": 0.0}],
        ]

        now = datetime.datetime.now()
        for i in range(count):
            t = (now - datetime.timedelta(minutes=random.randint(10, 1440) * (count - i))).strftime("%Y-%m-%d %H:%M:%S")
            res = "WIN" if random.random() < 0.65 else "LOSS"
            enemy_team = random.choice(sample_enemies)
            my_team = random.sample(sample_my_pets, k=random.randint(3, 5))
            duration = random.randint(90, 320)
            self.record_match(
                result=res,
                my_team=my_team,
                enemy_team=enemy_team,
                duration_sec=duration,
                rank_tier="大师段位" if i % 2 == 0 else "星耀段位",
                match_time=t
            )


_history_db_instance: Optional[HistoryDB] = None


def get_history_db() -> HistoryDB:
    global _history_db_instance
    if _history_db_instance is None:
        _history_db_instance = HistoryDB()
    return _history_db_instance
