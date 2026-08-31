"""实验功能：把本站用户本赛季数据拟合到 M-League 职业选手的牌风档案。

仅做本地实验，不参与上线。M-League 选手风格为参考档案数据（近似值），
用于原型相似度演示，不代表官方统计。
"""

from __future__ import annotations

import math
from urllib.parse import quote

from brml.analytics import _radar_values, _raw_metrics
from brml.db import query_all
from brml.match_service import current_season


def _wiki(name: str) -> str:
    return "https://ja.wikipedia.org/wiki/" + quote(name)


# 向量维度顺序与本站雷达一致：
# [一位率(×2), 正分率, 平均打点(归一), 四位回避率(100-4位率×2), 生存指数, 火力(归一)]
MLEAGUE_PROFILES = [
    {"name": "多井隆晴", "team": "U-NEXT Pirates", "wiki_url": _wiki("多井隆晴"),
     "vector": [95, 70, 78, 82, 86, 92]},
    {"name": "松本吉弘", "team": "KONAMI", "wiki_url": _wiki("松本吉弘"),
     "vector": [70, 82, 86, 95, 96, 74]},
    {"name": "近藤誠一", "team": "KONAMI", "wiki_url": _wiki("近藤誠一"),
     "vector": [55, 78, 90, 92, 94, 60]},
    {"name": "魚谷侑未", "team": "Kadokawa", "wiki_url": _wiki("魚谷侑未"),
     "vector": [85, 75, 72, 78, 80, 88]},
    {"name": "高宮まり", "team": "SEGA", "wiki_url": _wiki("高宮まり"),
     "vector": [72, 80, 82, 88, 92, 78]},
    {"name": "滝沢和典", "team": "U-NEXT Pirates", "wiki_url": _wiki("滝沢和典"),
     "vector": [88, 68, 70, 72, 74, 90]},
]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def user_style_vector(user_id: int) -> dict | None:
    """基于当前活跃赛季数据计算用户风格向量；无数据返回 None。"""
    season = current_season()
    if not season:
        return None
    entries = query_all(
        """
        select me.final_score, me.placement, me.rank_points
        from match_entries me
        join matches m on m.id = me.match_id
        where me.user_id = ? and m.season_id = ?
        order by m.played_at asc, m.id asc
        """,
        (user_id, season["id"]),
    )
    if not entries:
        return None
    return {
        "season_name": season["name"],
        "match_count": len(entries),
        "vector": _radar_values(_raw_metrics(entries)),
    }


def best_style_match(user_id: int) -> dict:
    """返回最接近的 M-League 选手与相似度排名。"""
    user = user_style_vector(user_id)
    if not user:
        return {"has_data": False}
    scored = []
    for profile in MLEAGUE_PROFILES:
        similarity = _cosine(user["vector"], profile["vector"])
        scored.append({**profile, "similarity": similarity, "similarity_pct": round(similarity * 100, 1)})
    scored.sort(key=lambda item: item["similarity"], reverse=True)
    return {
        "has_data": True,
        "user_vector": user["vector"],
        "match_count": user["match_count"],
        "season_name": user["season_name"],
        "best": scored[0],
        "ranked": scored[:5],
    }
