"""赛季规则默认值、表单解析与旧版本兼容。"""

from __future__ import annotations

import json

DEFAULT_RULES = {
    "points": {
        "default_starting_points": 25000,
        "return_points": 30000,
        "minimum_points_to_win": 1000,
        "final_required_matches": 8,
        "continue_after_negative": True,
        "riichi_bet_points": 1000,
        "repeat_counter_points": 300,
        "noten_penalty_1_tenpai": 3000,
        "noten_penalty_2_tenpai": 1500,
        "noten_penalty_3_tenpai": 1000,
        "use_a_rules": False,
        "uma_1st": 20,
        "uma_2nd": 10,
        "uma_3rd": -10,
        "uma_4th": -20,
        "a_uma_1_positive_1st": 12,
        "a_uma_1_positive_2nd": -1,
        "a_uma_1_positive_3rd": -3,
        "a_uma_1_positive_4th": -8,
        "a_uma_2_positive_1st": 8,
        "a_uma_2_positive_2nd": 4,
        "a_uma_2_positive_3rd": -4,
        "a_uma_2_positive_4th": -8,
        "a_uma_3_positive_1st": 8,
        "a_uma_3_positive_2nd": 3,
        "a_uma_3_positive_3rd": 1,
        "a_uma_3_positive_4th": -12,
    },
    "dora": {
        "open_dora": True,
        "ura_dora": True,
        "kan_dora": True,
        "reveal_dora_after_open_kan": True,
        "kan_ura_dora": True,
    },
    "dealer_repeats": {
        "dealer_repeats_on_win": True,
        "dealer_repeats_if_tenpai": True,
        "all_last_dealer_win_ends_if_first": True,
        "all_last_dealer_tenpai_ends_if_first": True,
    },
    "common": {
        "open_tanyao": True,
        "red_five": "3赤",
        "han_limit": "1番",
        "kiriage_mangan": True,
        "head_bump": True,
        "busting": True,
    },
    "abortive_draws": {
        "four_kan_draw": True,
        "four_wind_draw": True,
        "four_riichi_draw": True,
        "nine_terminals_draw": True,
        "triple_ron_draw": True,
    },
    "yakuman": {
        "counted_yakuman": True,
        "double_yakuman": True,
        "multiple_yakuman": True,
        "kokushi_13_wait_robbing_kan": False,
    },
    "others": {
        "renhou": "满贯",
        "pay_responsibility": True,
        "mangan_at_draw": True,
        "ippatsu": True,
        "west_extension": False,
        "local_yaku": False,
        "last_turn_riichi": False,
        "double_wind_4_fu": True,
    },
    "penalties": {
        "penalty_policy": "诈和：-4pt\n迟到：-2pt\n终局报分错误：-1pt\n违规操作：由裁判记录原因并按管理决定扣分",
    },
}

RULE_LABELS = {
    "points": "基础分数 / Points",
    "dora": "宝牌规则 / Dora Rules",
    "dealer_repeats": "连庄规则 / Dealer Repeat Rules",
    "common": "常用规则 / Common Rules",
    "abortive_draws": "中途流局规则 / Abortive Draw Rules",
    "yakuman": "役满规则 / Yakuman Rules",
    "others": "其他规则 / Other Rules",
    "penalties": "罚则 / Penalties",
}

FIELD_LABELS = {
    "default_starting_points": "四家起始分数 / Default Starting Points",
    "return_points": "原点 / Return Points",
    "minimum_points_to_win": "终场分数最低要求 / Minimum Final Score",
    "final_required_matches": "参与决赛需要场次 / Final Qualification Matches",
    "continue_after_negative": "负分后是否继续 / Continue After Negative Score",
    "riichi_bet_points": "立直棒点数 / Riichi Bet Points",
    "repeat_counter_points": "本场棒点数 / Repeat Counter Points",
    "noten_penalty_1_tenpai": "流局罚符：1人听牌 / Draw Penalty: 1 Tenpai",
    "noten_penalty_2_tenpai": "流局罚符：2人听牌 / Draw Penalty: 2 Tenpai",
    "noten_penalty_3_tenpai": "流局罚符：3人听牌 / Draw Penalty: 3 Tenpai",
    "use_a_rules": "是否 A 规 / Use A Rules",
    "uma_1st": "顺位马点：1位 / Placement Uma: 1st",
    "uma_2nd": "顺位马点：2位 / Placement Uma: 2nd",
    "uma_3rd": "顺位马点：3位 / Placement Uma: 3rd",
    "uma_4th": "顺位马点：4位 / Placement Uma: 4th",
    "a_uma_1_positive_1st": "A规马点：1人正分 1位 / A-Rule Uma: 1 Positive, 1st",
    "a_uma_1_positive_2nd": "A规马点：1人正分 2位 / A-Rule Uma: 1 Positive, 2nd",
    "a_uma_1_positive_3rd": "A规马点：1人正分 3位 / A-Rule Uma: 1 Positive, 3rd",
    "a_uma_1_positive_4th": "A规马点：1人正分 4位 / A-Rule Uma: 1 Positive, 4th",
    "a_uma_2_positive_1st": "A规马点：2人正分 1位 / A-Rule Uma: 2 Positive, 1st",
    "a_uma_2_positive_2nd": "A规马点：2人正分 2位 / A-Rule Uma: 2 Positive, 2nd",
    "a_uma_2_positive_3rd": "A规马点：2人正分 3位 / A-Rule Uma: 2 Positive, 3rd",
    "a_uma_2_positive_4th": "A规马点：2人正分 4位 / A-Rule Uma: 2 Positive, 4th",
    "a_uma_3_positive_1st": "A规马点：3人正分 1位 / A-Rule Uma: 3 Positive, 1st",
    "a_uma_3_positive_2nd": "A规马点：3人正分 2位 / A-Rule Uma: 3 Positive, 2nd",
    "a_uma_3_positive_3rd": "A规马点：3人正分 3位 / A-Rule Uma: 3 Positive, 3rd",
    "a_uma_3_positive_4th": "A规马点：3人正分 4位 / A-Rule Uma: 3 Positive, 4th",
    "open_dora": "开启表宝牌 / Open Dora",
    "ura_dora": "开启里宝牌 / Ura Dora",
    "kan_dora": "开启杠宝牌 / Kan Dora",
    "reveal_dora_after_open_kan": "开杠后立即翻宝牌 / Reveal Dora After Open Kan",
    "kan_ura_dora": "开启杠里宝牌 / Kan-Ura Dora",
    "dealer_repeats_on_win": "庄家和牌连庄 / Dealer Repeats on Win",
    "dealer_repeats_if_tenpai": "庄家听牌连庄 / Dealer Repeats if Tenpai",
    "all_last_dealer_win_ends_if_first": "南四庄家一位和牌是否结束 / All-Last Dealer Win Ends if First",
    "all_last_dealer_tenpai_ends_if_first": "南四庄家一位听牌是否结束 / All-Last Dealer Tenpai Ends if First",
    "open_tanyao": "食断 / Open Tanyao",
    "red_five": "赤宝数量 / Red Five",
    "han_limit": "番缚 / Han Limit",
    "kiriage_mangan": "切上满贯 / Kiriage Mangan",
    "head_bump": "头跳 / Head-Bump",
    "busting": "击飞 / Busting",
    "four_kan_draw": "四杠散了 / Four Kan Draw",
    "four_wind_draw": "四风连打 / Four Wind Draw",
    "four_riichi_draw": "四家立直 / Four Riichi Draw",
    "nine_terminals_draw": "九种九牌 / Nine Terminals Draw",
    "triple_ron_draw": "三家和 / Triple Ron Draw",
    "counted_yakuman": "累计役满 / Counted Yakuman",
    "double_yakuman": "双倍役满 / Double Yakuman",
    "multiple_yakuman": "复合役满 / Multiple Yakuman",
    "kokushi_13_wait_robbing_kan": "抢杠十三面 / Kokushi 13-Wait Robbing Kan",
    "renhou": "人和 / Hand of Man",
    "pay_responsibility": "包牌 / Pay Responsibility",
    "mangan_at_draw": "流局满贯 / Mangan at Draw",
    "ippatsu": "一发 / Ippatsu",
    "west_extension": "西入 / Extension to South/West",
    "local_yaku": "古役 / Local Yaku",
    "last_turn_riichi": "最后一巡立直 / Last-Turn Riichi",
    "double_wind_4_fu": "双风4符 / Double Wind 4 Fu",
    "penalty_policy": "罚则内容 / Penalty Policy",
}


def parse_rules_form(form) -> dict:
    """依据默认规则的类型，把扁平表单还原为嵌套规则字典。"""
    parsed = {}
    for group, fields in DEFAULT_RULES.items():
        parsed[group] = {}
        for key, default in fields.items():
            raw = form.get(f"rule__{group}__{key}")
            if isinstance(default, bool):
                parsed[group][key] = raw == "on"
            elif isinstance(default, int):
                parsed[group][key] = int(raw or 0)
            else:
                parsed[group][key] = raw or ""
    return parsed


def normalize_rules(rules: dict) -> dict:
    """把旧版规则合并到最新默认结构，确保新增字段始终有默认值。"""
    normalized = json.loads(json.dumps(DEFAULT_RULES))
    for group, fields in rules.items():
        if group not in normalized or not isinstance(fields, dict):
            normalized[group] = fields
            continue
        for key in normalized[group]:
            if key in fields:
                normalized[group][key] = fields[key]
    normalized.get("others", {}).pop("swap_calling", None)
    return normalized


