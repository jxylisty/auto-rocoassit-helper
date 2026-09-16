"""
从官方 API 下载全部咕噜球图标 (供球槽模板匹配 / UI 展示使用)

用法:
    python tools/fetch_ball_icons.py          # 下载普通图标
    python tools/fetch_ball_icons.py --big    # 同时下载高清大图

数据源: src/pvp/data/balls_data.json 中 is_ball=true 的条目
输出:  data/vision/ball_icons/{id}_{名称}.png (+ {id}_{名称}_big.png)
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from src.pvp.resource_updater import get_api_key  # noqa: E402

BALLS_JSON = PROJECT_ROOT / "src" / "pvp" / "data" / "balls_data.json"
OUT_DIR = PROJECT_ROOT / "data" / "vision" / "ball_icons"


def main() -> int:
    import requests

    with_big = "--big" in sys.argv
    balls = json.loads(BALLS_JSON.read_text(encoding="utf-8"))
    targets = [b for b in balls if b.get("is_ball")]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "X-API-Key": get_api_key(),
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    })

    ok, fail = 0, 0
    print(f"共 {len(targets)} 种咕噜球, 输出目录: {OUT_DIR}")
    for b in targets:
        name = f"{b['id']}_{b['name']}"
        jobs = [("icon", b["icon"], f"{name}.png")]
        if with_big and b.get("big_icon"):
            jobs.append(("big", b["big_icon"], f"{name}_big.png"))
        for kind, url, filename in jobs:
            out = OUT_DIR / filename
            if out.exists() and out.stat().st_size > 0:
                print(f"  跳过(已存在): {filename}")
                ok += 1
                continue
            try:
                resp = session.get(url, timeout=15)
                resp.raise_for_status()
                if not resp.content.startswith(b"\x89PNG"):
                    raise RuntimeError(f"响应不是 PNG ({resp.headers.get('Content-Type')})")
                out.write_bytes(resp.content)
                print(f"  ✅ [{kind}] {filename} ({len(resp.content) // 1024} KB)")
                ok += 1
            except Exception as e:
                print(f"  ❌ [{kind}] {b['name']}: {e}")
                fail += 1

    print(f"\n完成: 成功 {ok}, 失败 {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
