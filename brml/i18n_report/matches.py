"""最近对局列表与对局详情页文案（调研报告 P1-7 / 可用性 4）。

命名空间：``match.list.*``（列表时间线）、``match.detail.*``（详情页身份与口径）。
只补本页新增的键，不改动主表里既有的 ``match.*`` 文案。
"""

T = {
    "zh": {
        # ----- 列表：页头与筛选 -----
        "match.list.count": "共 {count} 场",
        "match.list.order": "按日期倒序",
        "match.list.season_filter": "赛季",
        # ----- 列表：每行摘要（报告示例：「1 位 Evan +60.2 · Justin / Leaf / DD」）-----
        "match.list.winner": "1 位 {name}",
        "match.list.winner_tied": "{placement} 位 {name}",
        "match.list.no_result": "暂无结算",
        "match.list.referee": "裁判 {name}",
        # ----- 列表：空态 -----
        "match.list.empty_title": "还没有对局记录",
        "match.list.empty_body": "这个筛选下还没有录入对局。换个赛季看看，或去活动页找下一场牌局。",
        "match.list.empty_action": "查看活动安排",
        # ----- 详情：页头导航 -----
        "match.detail.back": "返回最近对局",
        "match.detail.nav_label": "对局导航",
        "match.detail.prev": "上一场",
        "match.detail.next": "下一场",
        # ----- 详情：身份信息（桌型、人数、赛季、裁判）-----
        "match.detail.table": "桌型",
        "match.detail.players": "参赛人数",
        "match.detail.player_count": "{count} 人",
        "match.detail.season": "所属赛季",
        "match.detail.referee": "裁判",
        # ----- 详情：赛果与口径 -----
        "match.detail.results": "本场赛果",
        "match.detail.unit": "1 场（半庄）",
        "match.detail.points_note": "一场对局即一个半庄；结算积分 =（终局点数 − 返还点）÷ 1000 + 顺位点（UMA）− 罚分，可为负数。",
        # ----- 详情：罚则摘要 -----
        "match.detail.penalties": "罚则摘要",
        "match.detail.penalty_count": "{count} 项",
        "match.detail.no_penalty_title": "本场无罚则",
        "match.detail.no_penalty_body": "四位牌手都按赛果正常结算，没有额外扣分。",
        "match.detail.admin": "管理操作",
        # ----- 分页页码 -----
        "pagination.page_number": "第 {page} 页",
    },
    "en": {
        "match.list.count": "{count} matches",
        "match.list.order": "Newest first",
        "match.list.season_filter": "Season",
        "match.list.winner": "1st {name}",
        "match.list.winner_tied": "{placement} place {name}",
        "match.list.no_result": "No result recorded",
        "match.list.referee": "Referee {name}",
        "match.list.empty_title": "No matches recorded yet",
        "match.list.empty_body": "Nothing has been recorded for this filter. Try another season, or check the meetups page for the next game.",
        "match.list.empty_action": "See upcoming meetups",
        "match.detail.back": "Back to recent matches",
        "match.detail.nav_label": "Match navigation",
        "match.detail.prev": "Previous",
        "match.detail.next": "Next",
        "match.detail.table": "Format",
        "match.detail.players": "Players",
        "match.detail.player_count": "{count} players",
        "match.detail.season": "Season",
        "match.detail.referee": "Referee",
        "match.detail.results": "Match results",
        "match.detail.unit": "1 game (hanchan)",
        "match.detail.points_note": "One match counts as one hanchan. Rank points = (final score − return points) ÷ 1,000 + placement bonus (uma) − penalties; the total can be negative.",
        "match.detail.penalties": "Penalties",
        "match.detail.penalty_count": "{count} total",
        "match.detail.no_penalty_title": "No penalties in this match",
        "match.detail.no_penalty_body": "All players were settled on the raw result with no deductions.",
        "match.detail.admin": "Admin actions",
        "pagination.page_number": "Page {page}",
    },
}
