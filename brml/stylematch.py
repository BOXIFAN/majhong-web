"""实验功能：把本站用户本赛季数据拟合到 M-League 职业选手的牌风档案。

仅做本地实验，不参与上线。拟合对象来自 ``brml.mleague_data.MLEAGUE_PLAYERS``
，共 54 位职业选手（Mリーグ常规赛通算个人真实成绩）。

因为公开数据只提供“累计 pt / 平均着顺 / 各顺位次数”，没有逐局 final_score 与
rank_points，无法严格复刻本站六维；以下六维按真实字段近似推算，仅用于原型相似度
演示，页面上会明确标注“参考拟合 / 近似”。不代表官方统计，也不代表选手真实牌风
的权威评价。

六维近似口径（与站点雷达顺序一致）：
  [0] 一位率×2        = first/games*100*2                （与本站一致）
  [1] 正分率          = (first+second)/games*100          （取前二位数占比近似正分率）
  [2] 平均打点        = map(points/games) 到 0-100        （线性缩放近似）
  [3] 四位回避率      = 100 - fourth/games*100*2          （与本站一致）
  [4] 生存指数        = 100 - (third*0.6+fourth*1.4)/games*100 （避免垫底/末位近似）
  [5] 火力            = map(points/games) 到 0-100        （更陡的胜者火力缩放近似）
"""

from __future__ import annotations

import math
from urllib.parse import quote

from brml.analytics import _clip100, _radar_values, _raw_metrics
from brml.db import query_all
from brml.match_service import current_season
from brml.mleague_data import MLEAGUE_PLAYERS, MLEAGUE_TEAMS


def _wiki(name: str) -> str:
    return "https://ja.wikipedia.org/wiki/" + quote(name)


def _mleague_vector(profile: dict) -> list[float]:
    """从 M-League 真实字段近似推算本站同口径六维（0-100）。"""
    games = profile["games"]
    if games <= 0:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    first = profile["first"]
    second = profile["second"]
    third = profile["third"]
    fourth = profile["fourth"]
    avg_pt = profile["points"] / games  # 平均每局累计 pt

    return [
        _clip100((first / games) * 200),                     # 一位率 ×2
        _clip100(((first + second) / games) * 100),          # 正分率（前二占比近似）
        _clip100(((avg_pt + 15) / 30) * 100),                # 平均打点（线性缩放）
        _clip100(100 - (fourth / games) * 200),              # 四位回避率
        _clip100(100 - ((third * 0.6 + fourth * 1.4) / games) * 100),  # 生存指数
        _clip100((avg_pt / 8) * 100),                        # 火力（胜者火力）
    ]


def _mleague_display(profile: dict) -> list[str]:
    """生成与本站口径一致的六维展示文本（不含误导性百分比）。

    四个“率”维度用真实字段算真正的百分比；两个“点”维度用 Mリーグ积分单位：
    平均打点 = 场均累计 pt（所有对局平均）；火力 = 每次一位平均累计 pt（近似）。
    """
    games = profile["games"]
    if games <= 0:
        return ["—"] * 6
    first = profile["first"]
    second = profile["second"]
    third = profile["third"]
    fourth = profile["fourth"]
    avg_pt = profile["points"] / games
    first_rate = first / games * 100
    positive_rate = (first + second) / games * 100
    fourth_avoid = _clip100(100 - fourth / games * 200)
    survival = _clip100(100 - (third * 0.6 + fourth * 1.4) / games * 100)
    firepower = profile["points"] / first if first else 0.0
    return [
        f"{first_rate:.1f}%",
        f"{positive_rate:.1f}%",
        f"{avg_pt:,.1f}pt",
        f"{fourth_avoid:.1f}%",
        f"{survival:.1f}%",
        f"{firepower:,.1f}pt",
    ]


def _build_profiles() -> list[dict]:
    """把真实 54 位选手的数据打包为带六维向量的档案列表。"""
    profiles = []
    for player in MLEAGUE_PLAYERS:
        name = player["name"]
        profiles.append(
            {
                "name": name,
                "team": MLEAGUE_TEAMS.get(name, "Mリーグ"),
                "wiki_url": _wiki(name),
                "games": player["games"],
                "points": player["points"],
                "avg_place": player["avg_place"],
                "first": player["first"],
                "second": player["second"],
                "third": player["third"],
                "fourth": player["fourth"],
                "vector": _mleague_vector(player),
                "display": _mleague_display(player),
            }
        )
    return profiles


MLEAGUE_PROFILES = _build_profiles()


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
