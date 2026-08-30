"""立直麻将顺位与赛季积分计算。"""

from __future__ import annotations

def calculate_placements(scores: list[int]) -> list[float]:
    """按平均名次处理同点，例如并列第一返回 1.5、1.5、3、4。"""
    placements = []
    sorted_scores = sorted(scores, reverse=True)
    for score in scores:
        indexes = [idx + 1 for idx, item in enumerate(sorted_scores) if item == score]
        placements.append(sum(indexes) / len(indexes))
    return placements


def calculate_rank_points(scores: list[int], placements: list[float], rules: dict, penalties: list[int]) -> list[float]:
    """计算 ``(终局点-返还点)/1000 + UMA - 罚分``，同点均分对应 UMA。"""
    point_rules = rules["points"]
    return_points = int(point_rules.get("return_points", point_rules["default_starting_points"]))
    uma = get_uma_points(scores, return_points, point_rules)
    results = []
    sorted_scores = sorted(scores, reverse=True)
    for score, placement, penalty in zip(scores, placements, penalties):
        tied_places = [idx + 1 for idx, item in enumerate(sorted_scores) if item == score]
        avg_uma = sum(uma[place] for place in tied_places) / len(tied_places)
        base = (score - return_points) / 1000
        results.append(round(base + avg_uma - penalty, 1))
    return results


def get_uma_points(scores: list[int], return_points: int, point_rules: dict) -> dict[int, int]:
    """返回各顺位 UMA；A 规则按达到返还点的人数选择一组配置。"""
    if point_rules.get("use_a_rules"):
        positive_count = max(1, min(3, sum(1 for score in scores if score >= return_points)))
        return {
            place: int(point_rules[f"a_uma_{positive_count}_positive_{place}st"])
            if place == 1
            else int(point_rules[f"a_uma_{positive_count}_positive_{place}nd"])
            if place == 2
            else int(point_rules[f"a_uma_{positive_count}_positive_{place}rd"])
            if place == 3
            else int(point_rules[f"a_uma_{positive_count}_positive_{place}th"])
            for place in range(1, 5)
        }
    return {
        1: int(point_rules["uma_1st"]),
        2: int(point_rules["uma_2nd"]),
        3: int(point_rules["uma_3rd"]),
        4: int(point_rules["uma_4th"]),
    }


def placement_to_places(placement: float) -> list[int]:
    """把平均顺位还原为占用名次，用于同分情况下的统计。"""
    if placement == 1:
        return [1]
    if placement == 2:
        return [2]
    if placement == 3:
        return [3]
    if placement == 4:
        return [4]
    if placement == 1.5:
        return [1, 2]
    if placement == 2.5:
        return [2, 3]
    if placement == 3.5:
        return [3, 4]
    return [1, 2, 3, 4]


