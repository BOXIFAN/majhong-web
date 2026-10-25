"""赛季列表、规则版本管理与赛季删除路由。

WP5 改造（报告 P0-4 / 可用性 T4 / P1 长页章节感）：
把规则文档整理成 8 个带编号的章节，供模板生成 sticky 目录、锚点与行式参数。
本模块只读取 ``brml.rules`` 的标签定义，不改动数据结构。
"""

from __future__ import annotations

import json
import re

from flask import flash, g, redirect, render_template, request, url_for
from werkzeug.security import check_password_hash

from brml.auth import role_required
from brml.db import execute, get_db, query_all, query_one
from brml.i18n import TRANSLATIONS, translate
from brml.rules import DEFAULT_RULES, FIELD_LABELS, RULE_LABELS, normalize_rules, parse_rules_form
from brml.timeutils import now

# 目录顺序 = 页面 01–08 编号顺序，与 DEFAULT_RULES 的键保持一致。
RULE_GROUPS = (
    "points",
    "dora",
    "dealer_repeats",
    "common",
    "abortive_draws",
    "yakuman",
    "others",
    "penalties",
)

# 标签较短、值也短的章节在桌面用两列行式布局提高信息密度（每 4 项一条发丝线）；
# points 是数值最密集的核心章节，保持单列以便逐条核对；窄屏一律退回单列。
TWO_COLUMN_GROUPS = frozenset(
    {"dora", "dealer_repeats", "common", "abortive_draws", "yakuman", "others"}
)

# 罚则行「诈和：-4pt」里的短数值，用右对齐数值呈现；长说明保留整段文字。
_SHORT_PENALTY_VALUE = re.compile(r"^[+\-−]?\d+(?:[.,]\d+)?\s*(?:pt|点)?$", re.IGNORECASE)

_NORMAL_UMA_KEYS = frozenset({"uma_1st", "uma_2nd", "uma_3rd", "uma_4th"})


def _split_label(label: str) -> tuple[str, str]:
    """把 ``RULE_LABELS/FIELD_LABELS`` 里的「中文 / English」拆成两层。"""
    zh, _, en = label.partition(" / ")
    return zh.strip(), en.strip()


def _label_pair(key: str, fallback_label: str) -> tuple[str, str]:
    """优先取 i18n 分片里的改写文案，取不到时回退到 rules.py 的原始标签。"""
    fallback_zh, fallback_en = _split_label(fallback_label)
    return (
        TRANSLATIONS["zh"].get(key, fallback_zh),
        TRANSLATIONS["en"].get(key, fallback_en),
    )


def _format_number(value) -> str:
    """参数值统一展示：整数使用千分位，布尔与文本保持原样。"""
    if isinstance(value, bool):
        return translate("rules.bool_on") if value else translate("rules.bool_off")
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _is_visible_field(group: str, key: str, fields: dict) -> bool:
    """沿用原模板逻辑：A 规关闭时不显示 A 规马点，启用时隐藏普通马点。"""
    if group != "points":
        return True
    if fields.get("use_a_rules") and key in _NORMAL_UMA_KEYS:
        return False
    if not fields.get("use_a_rules") and key.startswith("a_uma_"):
        return False
    return True


def _field_view(key: str, value) -> dict:
    label_zh, label_en = _label_pair(f"rules.field.{key}", FIELD_LABELS.get(key, key))
    return {
        "key": key,
        "zh": label_zh,
        "en": label_en,
        "kind": "bool" if isinstance(value, bool) else "value",
        "value": value,
        "display": "" if isinstance(value, bool) else _format_number(value),
    }


def _penalty_items(value) -> list[dict]:
    """把罚则多行文本拆成「条目 + 分值」，长说明不强行塞进数值列。"""
    items: list[dict] = []
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        label, detail = line, ""
        for separator in ("：", ":"):
            if separator in line:
                label, _, detail = line.partition(separator)
                label, detail = label.strip(), detail.strip()
                break
        is_short_value = bool(detail) and bool(_SHORT_PENALTY_VALUE.match(detail))
        items.append({"label": label, "detail": detail, "is_value": is_short_value})
    return items


def build_rule_sections(rules: dict) -> list[dict]:
    """为模板准备 8 个规则章节（编号、锚点、双语标题、行式字段）。"""
    sections: list[dict] = []
    for index, group in enumerate(RULE_GROUPS, start=1):
        fields = rules.get(group)
        if not isinstance(fields, dict):
            continue
        title_zh, title_en = _label_pair(f"rules.section.{group}", RULE_LABELS.get(group, group))
        section = {
            "group": group,
            "anchor": f"rule-{group}",
            "number": f"{index:02d}",
            "title_zh": title_zh,
            "title_en": title_en,
            "two_column": group in TWO_COLUMN_GROUPS,
            "fields": [],
            "penalties": [],
            "count": 0,
        }
        if group == "penalties":
            text = fields.get("penalty_policy", "")
            section["penalties"] = _penalty_items(text)
            section["count"] = len(section["penalties"])
        else:
            section["fields"] = [
                _field_view(key, value)
                for key, value in fields.items()
                if _is_visible_field(group, key, fields)
            ]
            section["count"] = len(section["fields"])
        sections.append(section)
    return sections


def build_key_facts(rules: dict) -> dict | None:
    """页面顶部的 4 项速览：起始分数 / 原点 / 决赛资格 / 负分后继续。"""
    points = rules.get("points")
    if not isinstance(points, dict):
        return None
    return {
        "starting": _format_number(points.get("default_starting_points", "")),
        "return_points": _format_number(points.get("return_points", "")),
        "final": _format_number(points.get("final_required_matches", "")),
        "negative": bool(points.get("continue_after_negative")),
    }


def _season_card(season) -> dict:
    """模板用赛季卡片：补一个测试赛季标记（往期规则里并列 tester 版本时标注）。"""
    card = dict(season)
    name = str(card.get("name") or "")
    card["is_test"] = "tester" in name.lower()
    return card


def register_routes(app) -> None:
    # ----- 赛季、成绩、排行榜与导出 -----

    @app.route("/seasons")
    def seasons():
        seasons_data = query_all("select * from seasons order by start_date desc, id desc")
        active_season_row = query_one("select * from seasons where status = 'active' order by id desc limit 1")
        if not active_season_row and seasons_data:
            active_season_row = seasons_data[0]
        active_season = _season_card(active_season_row) if active_season_row else None
        active_rules = normalize_rules(json.loads(active_season_row["rules_json"])) if active_season_row else None
        past_seasons = [
            _season_card(season)
            for season in seasons_data
            if not active_season_row or season["id"] != active_season_row["id"]
        ]
        return render_template(
            "seasons.html",
            seasons=seasons_data,
            active_season=active_season,
            active_rules=active_rules,
            past_seasons=past_seasons,
            rule_sections=build_rule_sections(active_rules) if active_rules else [],
            key_facts=build_key_facts(active_rules) if active_rules else None,
        )

    @app.route("/seasons/new", methods=("GET", "POST"))
    @role_required("super_admin")
    def season_new():
        source_id = request.args.get("copy")
        source = query_one("select * from seasons where id = ?", (source_id,)) if source_id else None
        rules = normalize_rules(json.loads(source["rules_json"])) if source else DEFAULT_RULES
        if request.method == "POST":
            name = request.form["name"].strip()
            status = request.form["status"]
            parsed_rules = parse_rules_form(request.form)
            if not name:
                flash(translate("flash.season_name_required"), "error")
            else:
                if status == "active":
                    execute("update seasons set status = 'archived' where status = 'active'")
                execute(
                    """
                    insert into seasons (name, status, start_date, rules_json, version, created_at, updated_at)
                    values (?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        name,
                        status,
                        request.form["start_date"],
                        json.dumps(parsed_rules, ensure_ascii=False),
                        now(),
                        now(),
                    ),
                )
                flash(translate("flash.season_created"), "success")
                return redirect(url_for("seasons"))
        return render_template("season_form.html", season=None, rules=rules)

    @app.route("/seasons/<int:season_id>")
    def season_detail(season_id: int):
        season = query_one("select * from seasons where id = ?", (season_id,))
        if not season:
            flash(translate("flash.season_missing"), "error")
            return redirect(url_for("seasons"))
        rules = normalize_rules(json.loads(season["rules_json"]))
        return render_template(
            "season_detail.html",
            season=_season_card(season),
            rules=rules,
            rule_sections=build_rule_sections(rules),
            key_facts=build_key_facts(rules),
        )

    @app.route("/seasons/<int:season_id>/edit", methods=("GET", "POST"))
    @role_required("super_admin")
    def season_edit(season_id: int):
        season = query_one("select * from seasons where id = ?", (season_id,))
        if not season:
            flash(translate("flash.season_missing"), "error")
            return redirect(url_for("seasons"))
        rules = normalize_rules(json.loads(season["rules_json"]))
        if request.method == "POST":
            parsed_rules = parse_rules_form(request.form)
            if request.form["status"] == "active":
                execute("update seasons set status = 'archived' where status = 'active' and id != ?", (season_id,))
            execute(
                """
                update seasons
                set name = ?, status = ?, start_date = ?, rules_json = ?, version = version + 1, updated_at = ?
                where id = ?
                """,
                (
                    request.form["name"].strip(),
                    request.form["status"],
                    request.form["start_date"],
                    json.dumps(parsed_rules, ensure_ascii=False),
                    now(),
                    season_id,
                ),
            )
            execute(
                "insert into rule_versions (season_id, rules_json, changed_by, changed_at) values (?, ?, ?, ?)",
                (season_id, json.dumps(parsed_rules, ensure_ascii=False), g.user["id"], now()),
            )
            flash(translate("flash.season_updated"), "success")
            return redirect(url_for("season_detail", season_id=season_id))
        return render_template("season_form.html", season=season, rules=rules)

    @app.route("/seasons/<int:season_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def season_delete(season_id: int):
        season = query_one("select * from seasons where id = ?", (season_id,))
        if not season:
            flash(translate("flash.season_missing"), "error")
            return redirect(url_for("seasons"))

        password = request.form.get("password", "")
        if not check_password_hash(g.user["password_hash"], password):
            flash(translate("flash.season_password_invalid"), "error")
            return redirect(url_for("season_detail", season_id=season_id))

        db = get_db()
        try:
            db.execute(
                "delete from match_entries where match_id in (select id from matches where season_id = ?)",
                (season_id,),
            )
            db.execute("delete from penalties where season_id = ?", (season_id,))
            db.execute("delete from matches where season_id = ?", (season_id,))
            db.execute("delete from rule_versions where season_id = ?", (season_id,))
            db.execute("delete from seasons where id = ?", (season_id,))
            db.commit()
        except Exception:
            db.rollback()
            raise

        flash(translate("flash.season_deleted", name=season["name"]), "success")
        return redirect(url_for("seasons"))
