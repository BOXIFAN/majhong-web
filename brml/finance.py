"""俱乐部记账的只读统计逻辑：汇总、分类占比与会员收入统计。"""

from __future__ import annotations

from brml.db import query_all, query_one


# 分类颜色（与 brml/i18n.py 中 finance.category.* 文案一一对应）。
INCOME_COLORS = {
    "membership": "#0f766e",
    "event": "#2dd4bf",
    "sponsorship": "#14b8a6",
    "other": "#99f6e4",
}
EXPENSE_COLORS = {
    "venue": "#c2410c",
    "prize": "#f97316",
    "equipment": "#ea580c",
    "food": "#fb923c",
    "other": "#9a3412",
}


def fetch_transactions(limit: int | None = None) -> list:
    """返回未删除的收支记录，按发生时间倒序。"""
    sql = """
        select t.*, u.display_name as member_name
        from transactions t
        left join users u on u.id = t.user_id
        where t.deleted_at is null
        order by t.occurred_at desc, t.id desc
    """
    if limit:
        sql += f" limit {int(limit)}"
    return query_all(sql)


def totals() -> dict:
    """返回收入总额、支出总额与净结余（均为浮点金额）。"""
    row = query_one(
        """
        select
          coalesce(sum(case when kind = 'income' then amount end), 0) as income_total,
          coalesce(sum(case when kind = 'expense' then amount end), 0) as expense_total
        from transactions
        where deleted_at is null
        """
    )
    income = float(row["income_total"] or 0)
    expense = float(row["expense_total"] or 0)
    return {
        "income_total": income,
        "expense_total": expense,
        "net": income - expense,
    }


def _ratio(part: float, whole: float):
    """返回占整体百分比；整体为 0 时返回 None。"""
    return (part / whole * 100.0) if whole else None


def _pie_gradient(rows: list, colors: dict[str, str]) -> tuple[str | None, float]:
    """由分类金额生成 conic-gradient 字符串与结束百分比。"""
    total = sum(float(row["amount"]) for row in rows)
    if total <= 0:
        return None, 0.0
    stops: list[str] = []
    acc = 0.0
    for row in rows:
        color = colors.get(row["category"], "#94a3b8")
        acc += float(row["amount"]) / total * 100.0
        stops.append(f"{color} {acc - float(row['amount']) / total * 100.0:.3f}% {acc:.3f}%")
    return "conic-gradient(" + ", ".join(stops) + ")", acc


def breakdown(kind: str) -> dict:
    """返回指定方向（income/expense）的分类统计与扇形图数据。"""
    rows = query_all(
        """
        select category, sum(amount) as amount, count(*) as records
        from transactions
        where kind = ? and deleted_at is null
        group by category
        order by amount desc
        """,
        (kind,),
    )
    total = sum(float(row["amount"]) for row in rows)
    colors = INCOME_COLORS if kind == "income" else EXPENSE_COLORS
    gradient, _ = _pie_gradient(rows, colors)
    categories = []
    for row in rows:
        amount = float(row["amount"])
        pct = _ratio(amount, total)
        categories.append(
            {
                "category": row["category"],
                "amount": amount,
                "records": row["records"],
                "color": colors.get(row["category"], "#94a3b8"),
                "pct": pct,
                "pct_label": f"{pct:.1f}%".rstrip("0").rstrip(".") + "%" if pct is not None else "0%",
            }
        )
    return {"total": total, "gradient": gradient, "categories": categories}


def member_income_stats() -> list:
    """按注册会员汇总其被记入的收入（用于后台会员收入统计）。"""
    rows = query_all(
        """
        select u.display_name, u.role, count(t.id) as records, sum(t.amount) as income
        from transactions t
        join users u on u.id = t.user_id
        where t.kind = 'income' and t.deleted_at is null
        group by u.id
        order by income desc, u.display_name asc
        """
    )
    total = sum(float(row["income"]) for row in rows)
    result = []
    for row in rows:
        income = float(row["income"])
        result.append(
            {
                "display_name": row["display_name"],
                "role": row["role"],
                "records": row["records"],
                "income": income,
                "pct": _ratio(income, total),
            }
        )
    return result


def summary() -> dict:
    """一次性汇总页面所需数据：总额、净结余、占比、分类与扇形图。"""
    total = totals()
    expense_ratio = _ratio(total["expense_total"], total["income_total"])
    income = breakdown("income")
    expense = breakdown("expense")
    return {
        "income_total": total["income_total"],
        "expense_total": total["expense_total"],
        "net": total["net"],
        "spend_ratio": expense_ratio,
        "net_ratio": _ratio(total["net"], total["income_total"]),
        "income": income,
        "expense": expense,
    }
