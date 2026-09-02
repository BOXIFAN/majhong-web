"""俱乐部记账路由：公开只读总览 + 仅超级管理员可写的后台。"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

from flask import Response, flash, g, redirect, render_template, request, url_for

from brml.auth import role_required
from brml.db import execute, get_db, query_all, query_one
from brml.finance import (
    EXPENSE_COLORS,
    INCOME_COLORS,
    fetch_transactions,
    member_income_stats,
    summary,
)
from brml.i18n import translate
from brml.timeutils import now


def _active_users() -> list:
    return query_all(
        "select id, display_name from users where is_deleted = 0 order by display_name"
    )


def _parse_amount(value: str):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return round(amount, 2)


def _parse_occurred_at(value: str):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _validate(kind: str, category: str, description: str, amount: float,
              occurred_at: str, user_id: int | None) -> str | None:
    allowed = INCOME_COLORS if kind == "income" else EXPENSE_COLORS
    if kind not in ("income", "expense"):
        return translate("finance.error_kind")
    if category not in allowed:
        return translate("finance.error_category")
    if amount is None or amount <= 0:
        return translate("finance.error_amount")
    if occurred_at is None:
        return translate("finance.error_date")
    if kind == "income" and user_id:
        user = query_one("select id from users where id = ? and is_deleted = 0", (user_id,))
        if not user:
            return translate("finance.error_user")
    return None


def register_routes(app) -> None:
    # ----- 公开只读总览：所有用户可访问 -----

    @app.route("/finance")
    @role_required("super_admin", "referee")
    def finance():
        data = summary()
        transactions = fetch_transactions(limit=50)
        return render_template("finance.html", data=data, transactions=transactions)

    @app.route("/finance/export")
    @role_required("super_admin", "referee")
    def finance_export():
        rows = query_all(
            """
            select t.*, u.display_name as member_name
            from transactions t
            left join users u on u.id = t.user_id
            where t.deleted_at is null
            order by t.occurred_at desc, t.id desc
            """
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                translate("finance.date"),
                translate("finance.kind"),
                translate("finance.category"),
                translate("finance.description"),
                translate("finance.member"),
                translate("finance.amount"),
            ]
        )
        for row in rows:
            kind_label = (
                translate("finance.income_label")
                if row["kind"] == "income"
                else translate("finance.expense_label")
            )
            category_label = translate(f"finance.category.{row['category']}")
            writer.writerow(
                [
                    row["occurred_at"],
                    kind_label,
                    category_label,
                    row["description"] or "",
                    row["member_name"] or "",
                    f"{row['amount']:.2f}",
                ]
            )
        filename = f"club-ledger-{date.today().isoformat()}.csv"
        return Response(
            "\ufeff" + output.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # ----- 后台记账：仅超级管理员可读写 -----

    @app.route("/admin/finance", methods=("GET",))
    @role_required("super_admin")
    def admin_finance():
        return redirect(url_for("admin_users", tab="finance"))

    @app.route("/admin/finance/create", methods=("POST",))
    @role_required("super_admin")
    def finance_create():
        kind = request.form.get("kind", "")
        category = request.form.get("category", "")
        description = request.form.get("description", "").strip()
        amount = _parse_amount(request.form.get("amount", ""))
        occurred_at = _parse_occurred_at(request.form.get("occurred_at", ""))
        user_id = request.form.get("user_id", type=int)
        error = _validate(kind, category, description, amount, occurred_at, user_id)
        if error:
            flash(error, "error")
        else:
            execute(
                """
                insert into transactions
                  (kind, category, description, amount, user_id, recorded_by, occurred_at, recorded_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (kind, category, description, amount, user_id if kind == "income" else None,
                 g.user["id"], occurred_at, now()),
            )
            flash(translate("finance.created"), "success")
        return redirect(url_for("admin_users", tab="finance"))

    @app.route("/admin/finance/<int:transaction_id>/edit", methods=("GET", "POST"))
    @role_required("super_admin")
    def finance_edit(transaction_id: int):
        transaction = query_one(
            "select * from transactions where id = ? and deleted_at is null",
            (transaction_id,),
        )
        if not transaction:
            flash(translate("finance.missing"), "error")
            return redirect(url_for("admin_users", tab="finance"))
        if request.method == "POST":
            kind = request.form.get("kind", "")
            category = request.form.get("category", "")
            description = request.form.get("description", "").strip()
            amount = _parse_amount(request.form.get("amount", ""))
            occurred_at = _parse_occurred_at(request.form.get("occurred_at", ""))
            user_id = request.form.get("user_id", type=int)
            error = _validate(kind, category, description, amount, occurred_at, user_id)
            if error:
                flash(error, "error")
            else:
                db = get_db()
                db.execute(
                    """
                    update transactions
                    set kind = ?, category = ?, description = ?, amount = ?,
                        user_id = ?, occurred_at = ?
                    where id = ?
                    """,
                    (kind, category, description, amount,
                     user_id if kind == "income" else None, occurred_at, transaction_id),
                )
                db.commit()
                flash(translate("finance.updated"), "success")
                return redirect(url_for("admin_users", tab="finance"))
        return render_template(
            "finance_form.html",
            transaction=transaction,
            members=_active_users(),
        )

    @app.route("/admin/finance/<int:transaction_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def finance_delete(transaction_id: int):
        transaction = query_one(
            "select id from transactions where id = ? and deleted_at is null",
            (transaction_id,),
        )
        if not transaction:
            flash(translate("finance.missing"), "error")
        else:
            execute(
                "update transactions set deleted_at = ? where id = ?",
                (now(), transaction_id),
            )
            flash(translate("finance.deleted"), "success")
        return redirect(url_for("admin_users", tab="finance"))
