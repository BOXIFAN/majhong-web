from __future__ import annotations

import csv
import functools
import io
import json
import os
import secrets
import sqlite3
import string
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    Response,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "instance" / "mahjong.db"))
SEED_DEMO_DATA = os.environ.get("SEED_DEMO_DATA", "false").lower() in {"1", "true", "yes", "on"}

ADMIN_PASSWORD_HASH = "pbkdf2:sha256:600000$OE6JuNaR26tucuw6$c7c3987d9ac3d9e86f2fab2c689c8b49dab963e674f571e8d32d78bf5aaf8c80"
ADMIN_PASSWORD_MIGRATION = "set-admin-password-2026-08-24"
DEFAULT_MEETUP_VENUE = "upc 8 Gillingham street, QLD4102"

SUPPORTED_LOCALES = ("zh", "en")

ROLE_LABELS = {
    "zh": {
        "super_admin": "超级管理员",
        "referee": "裁判",
        "user": "普通用户",
    },
    "en": {
        "super_admin": "Super Admin",
        "referee": "Referee",
        "user": "Player",
    },
}

ROLES = ROLE_LABELS["zh"]

TRANSLATIONS = {
    "zh": {
        "language.switch": "切换语言",
        "nav.home": "首页",
        "nav.leaderboard": "排行榜",
        "nav.matches": "最近对局",
        "nav.rules": "赛季规则",
        "nav.about": "关于我们",
        "nav.meetups": "活动报名",
        "nav.match_entry": "录入比赛",
        "nav.admin": "后台管理",
        "nav.invites": "邀请码",
        "nav.open_menu": "打开导航菜单",
        "auth.login": "登录",
        "auth.logout": "退出",
        "auth.register": "注册",
        "auth.email": "邮箱",
        "auth.password": "密码",
        "auth.remember": "记住我（30 天）",
        "auth.display_name": "显示名称",
        "auth.invite_code": "邀请码",
        "auth.create_account": "创建账号",
        "account.guest": "访客",
        "account.guest_mobile_hint": "登录后可录入或发布",
        "account.guest_desktop_hint": "加入社群后可记录成绩",
        "meetup.title": "活动报名",
        "meetup.subtitle": "按时间查看 Meetup，并点击报名参加。",
        "meetup.create": "创建 Meetup",
        "meetup.edit": "编辑 Meetup",
        "meetup.time": "Meetup 时间",
        "meetup.deadline": "报名截止时间",
        "meetup.venue": "地点与场地",
        "meetup.timezone": "布里斯班时间",
        "meetup.save": "保存时间",
        "meetup.signup": "报名",
        "meetup.signed_up": "已报名",
        "meetup.attendees": "报名成员",
        "meetup.attendee_count": "{count} 人",
        "meetup.no_attendees": "还没有人报名。",
        "meetup.none": "目前还没有可报名的 Meetup。",
        "meetup.time_required": "请选择有效的 Meetup 时间。",
        "meetup.created": "Meetup 已创建。",
        "meetup.updated": "Meetup 时间已更新。",
        "meetup.missing": "Meetup 不存在。",
        "meetup.signup_success": "报名成功。",
        "meetup.signup_duplicate": "你已经报名该 Meetup。",
        "meetup.view_signup": "查看并报名",
        "meetup.detail": "报名详情",
        "meetup.back": "返回报名列表",
        "meetup.open": "报名中",
        "meetup.closed": "报名已截止",
        "meetup.archived": "已归档",
        "meetup.archive": "归档报名",
        "meetup.archive_confirm": "确认归档这个 Meetup？归档后普通成员不能再报名。",
        "meetup.archived_success": "Meetup 已归档。",
        "meetup.delete": "删除 Meetup",
        "meetup.delete_confirm": "确认永久删除这个 Meetup？全部报名记录也会一并删除，此操作无法撤销。",
        "meetup.deleted_success": "Meetup 及其报名记录已删除。",
        "meetup.signup_closed": "该 Meetup 已截止或归档，无法报名。",
        "meetup.deadline_order": "报名截止时间不能晚于 Meetup 时间。",
        "meetup.manage_attendees": "管理报名成员",
        "meetup.choose_member": "选择成员",
        "meetup.add_member": "加入成员",
        "meetup.remove_member": "移除",
        "meetup.remove_confirm": "确认将 {name} 从报名名单中移除？",
        "meetup.member_added": "成员已加入报名名单。",
        "meetup.member_removed": "成员已从报名名单移除。",
        "meetup.member_missing": "成员不存在或无法报名。",
        "home.title_fallback": "立直麻将社群平台",
        "home.subtitle": "赛季规则、比赛录入、自动算分、排行榜和个人数据集中管理。",
        "home.view_leaderboard": "查看排行榜",
        "home.current_season": "当前赛季",
        "home.not_enabled": "未启用",
        "home.rule_version": "规则版本 v{version}",
        "home.all": "全部",
        "home.no_matches": "还没有比赛记录。",
        "home.recent_matches": "最近对局",
        "home.match_count": "{count} 场",
        "home.unnamed_match": "未命名牌桌",
        "home.referee": "裁判：{name}",
        "home.system": "系统",
        "home.first_match_hint": "录入第一场比赛后会显示在这里。",
        "announcement.title": "公告",
        "announcement.latest": "最新公告",
        "announcement.archive": "往期公告",
        "announcement.none": "暂时还没有公告。",
        "announcement.no_archive": "暂时还没有往期公告。",
        "announcement.published_by": "{date} · 由 {name} 发布",
        "announcement.manage": "管理公告",
        "announcement.manage_hint": "新公告发布后会显示在首页顶部；已有公告可以继续编辑。",
        "announcement.new": "发布新公告",
        "announcement.edit": "编辑公告",
        "announcement.subject": "公告标题",
        "announcement.content": "公告内容",
        "announcement.publish": "发布公告",
        "announcement.save": "保存修改",
        "announcement.delete": "删除公告",
        "announcement.delete_confirm": "确认删除公告“{title}”？此操作无法撤销。",
        "announcement.required": "请填写公告标题和内容。",
        "announcement.created": "公告已发布。",
        "announcement.updated": "公告已更新。",
        "announcement.deleted": "公告已删除。",
        "announcement.missing": "公告不存在。",
        "pagination.recent_matches": "最近对局翻页",
        "pagination.meetups": "活动报名翻页",
        "pagination.prev": "上一页",
        "pagination.next": "下一页",
        "table.player": "玩家",
        "table.points": "积分",
        "table.avg_place": "均顺",
        "table.matches": "对局",
        "table.first_rate": "一位率",
        "table.fourth_rate": "四位率",
        "table.placement": "顺位",
        "table.final_score": "终局点数",
        "table.rank_points": "结算积分",
        "table.penalty_points": "已计入罚分",
        "leaderboard.empty": "该赛季还没有排行榜数据。",
        "finals.title": "决赛资格",
        "finals.distance": "您距离决赛还有",
        "finals.matches_met": "您已满足局数要求",
        "finals.matches_done": "已完成 {matches} 个半庄，需要 {required} 个。",
        "finals.matches_remaining": "{count} 个半庄",
        "finals.matches_progress": "需要 {required} 个，当前已完成 {matches} 个。",
        "finals.status": "决赛资格",
        "finals.login_to_view": "登录后查看您的决赛资格。",
        "finals.championship_met": "您已满足冠军杯决赛标准。",
        "finals.yakitori_met": "您已满足烧鸡杯要求。",
        "finals.not_enough_data": "该赛季暂时没有足够的排行榜数据计算杯赛分界线。",
        "finals.not_met": "您尚未满足冠军杯或烧鸡杯标准。",
        "finals.gap_both": "距离冠军杯还差 {championship} pt；距离烧鸡杯还差 {yakitori} pt。",
        "finals.gap_yakitori": "距离冠军杯还差 {championship} pt；距离烧鸡杯还需下降 {yakitori} pt。",
        "finals.rank_points": "当前排名第 {rank} 位，积分 {points} pt。",
        "finals.select_season": "请选择赛季后查看决赛资格。",
        "status.enabled": "开启",
        "status.disabled": "关闭",
        "status.used": "已使用",
        "status.available": "可用",
        "status.deleted": "已删除",
        "status.normal": "正常",
        "status.preserved": "历史战绩保留中",
        "season.rules": "赛季规则",
        "season.new": "新建赛季",
        "season.edit": "编辑赛季",
        "season.edit_rules": "编辑规则",
        "season.edit_current": "编辑当前规则",
        "season.copy": "复制为新赛季",
        "season.export_csv": "导出排行榜 CSV",
        "season.start_version": "开始日期：{date} · 规则版本 v{version}",
        "season.archive": "往期规则",
        "season.archive_count": "{count} 个",
        "season.no_archive": "还没有往期赛季。",
        "season.no_rules": "还没有创建赛季规则。",
        "season.back": "返回赛季列表",
        "season.name": "赛季名称",
        "season.status": "状态",
        "season.start_date": "开始日期",
        "season.save_rules": "保存赛季规则",
        "season.delete": "删除赛季",
        "season.delete_warning": "删除后，该赛季的全部比赛、排行榜、罚则和规则版本都会永久删除。请输入当前管理员密码确认。",
        "season.delete_password": "管理员密码",
        "season.delete_confirm": "确定永久删除赛季“{name}”及其全部排行榜和比赛数据？",
        "match.entry": "录入比赛",
        "match.edit": "编辑比赛",
        "match.edit_hint": "修改后会按当前赛季规则重新计算顺位、pt、马点和罚分。",
        "match.season_total": "当前赛季总分校验：{total}",
        "match.time": "比赛时间",
        "match.time_automatic": "提交时自动记录当前时间（布里斯班时间）",
        "match.type": "对局类型",
        "match.type_meetup": "Meetup",
        "match.type_private": "私下对局",
        "match.memo": "备注",
        "match.optional": "可选",
        "match.player_n": "玩家 {number}",
        "match.search_player": "输入姓名或角色搜索",
        "match.choose_player": "选择玩家",
        "match.deleted_user": "已删除",
        "match.final_score": "最终分数",
        "match.penalty": "罚分（直接扣入最终积分）",
        "match.penalty_type": "违规类型",
        "match.penalty_type_placeholder": "终局报分错误",
        "match.penalty_reason": "罚分原因",
        "match.penalty_reason_placeholder": "有罚分时必填",
        "match.current_total": "当前总分：",
        "match.target_total": "目标总分：{total}",
        "match.submit": "提交比赛",
        "match.cancel": "取消",
        "match.save_recalculate": "保存并重算",
        "match.unknown_title": "比赛 #{id}",
        "match.meta": "{time} · 裁判：{referee}",
        "match.penalty_records": "罚则记录",
        "match.no_penalty_records": "暂无罚则记录。",
        "match.delete": "删除对局",
        "match.delete_confirm": "确认删除这场对局？删除后排行榜会重新计算。",
        "admin.title": "后台管理",
        "admin.subtitle": "编辑用户名称、角色与账号状态。删除用户不会移除已录入战绩。",
        "admin.users": "用户",
        "admin.user_count": "{count} 人",
        "admin.registered_at": "{email} · {role} · 注册于 {created_at}",
        "admin.name_label": "用户名称",
        "admin.role_label": "用户角色",
        "admin.save": "保存",
        "admin.reset_password": "重置密码",
        "admin.reset_confirm": "确认重置 {name} 的密码？新临时密码只会显示一次。",
        "admin.delete": "删除",
        "admin.delete_confirm": "确认删除 {name}？历史战绩会保留。",
        "invites.title": "邀请码",
        "invites.generate_title": "生成新邀请码",
        "invites.generate_hint": "系统会自动创建唯一邀请码。",
        "invites.generate": "生成",
        "invites.code": "邀请码",
        "invites.role": "角色",
        "invites.status": "状态",
        "invites.used_by": "使用者",
        "player.current_points": "当前积分",
        "player.matches": "对局数",
        "player.avg_place": "平均顺位",
        "player.first_fourth": "一位 / 四位",
        "player.recent_trend": "近 10 场趋势",
        "player.trend_aria": "近 10 场顺位折线图",
        "player.placement_detail": "{placement} 位 · {score}",
        "player.no_matches": "暂无对局。",
        "player.penalties": "罚则",
        "player.no_penalties": "暂无罚则记录。",
        "flash.login_required": "请先登录。",
        "flash.permission_denied": "当前账号没有操作权限。",
        "flash.register_missing": "请填写所有注册信息。",
        "flash.invite_invalid": "邀请码无效或已被使用。",
        "flash.email_registered": "该邮箱已注册。",
        "flash.register_success": "注册成功，请登录。",
        "flash.login_success": "欢迎回来。",
        "flash.login_invalid": "邮箱或密码不正确。",
        "flash.logout_success": "已退出登录。",
        "flash.invite_role_invalid": "邀请码角色不正确。",
        "flash.invite_created": "邀请码 {code} 已创建。",
        "flash.invite_conflict": "邀请码生成冲突，请重试。",
        "flash.user_missing": "用户不存在。",
        "flash.user_name_required": "用户名称不能为空。",
        "flash.deleted_user_locked": "已删除用户不能编辑。",
        "flash.user_role_invalid": "只能将用户设为裁判或普通用户。",
        "flash.user_updated": "{name} 已更新。",
        "flash.super_admin_delete_denied": "不能删除超级管理员。",
        "flash.user_deleted": "{name} 已删除，历史战绩已保留。",
        "flash.deleted_user_password_locked": "已删除用户不能重置密码。",
        "flash.super_admin_password_locked": "超级管理员密码请由本人修改，避免误锁定后台。",
        "flash.temporary_password": "{name} 的临时密码：{password}。请只告知本人并提醒尽快更改。",
        "flash.season_name_required": "请输入赛季名称。",
        "flash.season_created": "赛季已创建。",
        "flash.season_missing": "赛季不存在。",
        "flash.season_updated": "赛季规则已更新，版本记录已保留。",
        "flash.season_password_invalid": "管理员密码不正确，赛季未删除。",
        "flash.season_deleted": "赛季“{name}”及其排行榜和比赛数据已删除。",
        "flash.season_required": "请先创建并启用赛季。",
        "flash.match_created": "比赛已录入，排行榜已自动更新。",
        "flash.match_missing": "比赛不存在。",
        "flash.match_updated": "比赛结果已更新，并已重新计算积分。",
        "flash.match_delete_missing": "对局不存在或已被删除。",
        "flash.match_deleted": "对局已删除，排行榜已按剩余记录重新计算。",
        "flash.player_missing": "玩家不存在。",
        "validation.players_required": "必须选择满 4 名玩家。",
        "validation.players_unique": "玩家不可重复。",
        "validation.score_total": "四家总分必须等于当前赛季起始分总和：{total}。",
        "validation.penalty_reason_required": "罚分必须填写原因。",
        "match.default_penalty_type": "管理处罚",
    },
    "en": {
        "language.switch": "Switch language",
        "nav.home": "Home",
        "nav.leaderboard": "Leaderboard",
        "nav.matches": "Recent Matches",
        "nav.rules": "Season Rules",
        "nav.about": "About Us",
        "nav.meetups": "Meetup Sign-up",
        "nav.match_entry": "Match Entry",
        "nav.admin": "Admin",
        "nav.invites": "Invites",
        "nav.open_menu": "Open navigation menu",
        "auth.login": "Log In",
        "auth.logout": "Log Out",
        "auth.register": "Register",
        "auth.email": "Email",
        "auth.password": "Password",
        "auth.remember": "Remember me for 30 days",
        "auth.display_name": "Display Name",
        "auth.invite_code": "Invite Code",
        "auth.create_account": "Create Account",
        "account.guest": "Guest",
        "account.guest_mobile_hint": "Log in to enter or publish matches",
        "account.guest_desktop_hint": "Join the club to record results",
        "meetup.title": "Meetup Sign-up",
        "meetup.subtitle": "View upcoming meetups in time order and sign up to attend.",
        "meetup.create": "Create Meetup",
        "meetup.edit": "Edit Meetup",
        "meetup.time": "Meetup Time",
        "meetup.deadline": "Sign-up Deadline",
        "meetup.venue": "Location & Venue",
        "meetup.timezone": "Brisbane time",
        "meetup.save": "Save Time",
        "meetup.signup": "Sign Up",
        "meetup.signed_up": "Signed Up",
        "meetup.attendees": "Attendees",
        "meetup.attendee_count": "{count} people",
        "meetup.no_attendees": "No one has signed up yet.",
        "meetup.none": "There are no meetups available yet.",
        "meetup.time_required": "Please choose a valid meetup time.",
        "meetup.created": "Meetup created.",
        "meetup.updated": "Meetup time updated.",
        "meetup.missing": "Meetup not found.",
        "meetup.signup_success": "You have signed up.",
        "meetup.signup_duplicate": "You have already signed up for this meetup.",
        "meetup.view_signup": "View & Sign Up",
        "meetup.detail": "Sign-up Details",
        "meetup.back": "Back to Meetups",
        "meetup.open": "Open",
        "meetup.closed": "Sign-up Closed",
        "meetup.archived": "Archived",
        "meetup.archive": "Archive Sign-up",
        "meetup.archive_confirm": "Archive this meetup? Members will no longer be able to sign up.",
        "meetup.archived_success": "Meetup archived.",
        "meetup.delete": "Delete Meetup",
        "meetup.delete_confirm": "Permanently delete this meetup and all of its sign-ups? This cannot be undone.",
        "meetup.deleted_success": "Meetup and its sign-ups deleted.",
        "meetup.signup_closed": "This meetup is closed or archived and cannot accept sign-ups.",
        "meetup.deadline_order": "The sign-up deadline cannot be later than the meetup time.",
        "meetup.manage_attendees": "Manage Attendees",
        "meetup.choose_member": "Choose Member",
        "meetup.add_member": "Add Member",
        "meetup.remove_member": "Remove",
        "meetup.remove_confirm": "Remove {name} from this meetup?",
        "meetup.member_added": "Member added to the attendee list.",
        "meetup.member_removed": "Member removed from the attendee list.",
        "meetup.member_missing": "Member not found or unavailable.",
        "home.title_fallback": "Riichi Mahjong League Platform",
        "home.subtitle": "Manage season rules, match entry, scoring, leaderboards, and player data in one place.",
        "home.view_leaderboard": "View Leaderboard",
        "home.current_season": "Current Season",
        "home.not_enabled": "Not Enabled",
        "home.rule_version": "Rules v{version}",
        "home.all": "All",
        "home.no_matches": "No match records yet.",
        "home.recent_matches": "Recent Matches",
        "home.match_count": "{count} matches",
        "home.unnamed_match": "Untitled Match",
        "home.referee": "Referee: {name}",
        "home.system": "System",
        "home.first_match_hint": "The first entered match will appear here.",
        "announcement.title": "Announcements",
        "announcement.latest": "Latest Announcement",
        "announcement.archive": "Past Announcements",
        "announcement.none": "There are no announcements yet.",
        "announcement.no_archive": "There are no past announcements yet.",
        "announcement.published_by": "{date} · Published by {name}",
        "announcement.manage": "Manage Announcements",
        "announcement.manage_hint": "New announcements appear at the top of the home page; existing announcements can be edited.",
        "announcement.new": "Publish Announcement",
        "announcement.edit": "Edit Announcement",
        "announcement.subject": "Title",
        "announcement.content": "Content",
        "announcement.publish": "Publish",
        "announcement.save": "Save Changes",
        "announcement.delete": "Delete Announcement",
        "announcement.delete_confirm": "Delete announcement “{title}”? This cannot be undone.",
        "announcement.required": "Please enter both a title and content.",
        "announcement.created": "Announcement published.",
        "announcement.updated": "Announcement updated.",
        "announcement.deleted": "Announcement deleted.",
        "announcement.missing": "Announcement not found.",
        "pagination.recent_matches": "Recent match pagination",
        "pagination.meetups": "Meetup pagination",
        "pagination.prev": "Previous",
        "pagination.next": "Next",
        "table.player": "Player",
        "table.points": "Points",
        "table.avg_place": "Avg. Place",
        "table.matches": "Matches",
        "table.first_rate": "1st Rate",
        "table.fourth_rate": "4th Rate",
        "table.placement": "Place",
        "table.final_score": "Final Score",
        "table.rank_points": "PT",
        "table.penalty_points": "Penalty Included",
        "leaderboard.empty": "No leaderboard data for this season yet.",
        "finals.title": "Final Qualification",
        "finals.distance": "Matches until final",
        "finals.matches_met": "Match-count requirement met",
        "finals.matches_done": "{matches} hanchan completed; {required} required.",
        "finals.matches_remaining": "{count} hanchan",
        "finals.matches_progress": "{required} required; {matches} completed.",
        "finals.status": "Final Qualification",
        "finals.login_to_view": "Log in to view your final qualification.",
        "finals.championship_met": "You meet the Championship Cup final standard.",
        "finals.yakitori_met": "You meet the Yakitori Cup requirement.",
        "finals.not_enough_data": "This season does not have enough leaderboard data to calculate cup cutoffs yet.",
        "finals.not_met": "You have not met the Championship Cup or Yakitori Cup standard yet.",
        "finals.gap_both": "{championship} pt short of Championship Cup; {yakitori} pt short of Yakitori Cup.",
        "finals.gap_yakitori": "{championship} pt short of Championship Cup; drop {yakitori} pt more for Yakitori Cup.",
        "finals.rank_points": "Current rank #{rank}, {points} pt.",
        "finals.select_season": "Select a season to view final qualification.",
        "status.enabled": "Enabled",
        "status.disabled": "Disabled",
        "status.used": "Used",
        "status.available": "Available",
        "status.deleted": "Deleted",
        "status.normal": "Active",
        "status.preserved": "Historical results retained",
        "season.rules": "Season Rules",
        "season.new": "New Season",
        "season.edit": "Edit Season",
        "season.edit_rules": "Edit Rules",
        "season.edit_current": "Edit Current Rules",
        "season.copy": "Copy as New Season",
        "season.export_csv": "Export Leaderboard CSV",
        "season.start_version": "Start Date: {date} · Rules v{version}",
        "season.archive": "Past Rules",
        "season.archive_count": "{count}",
        "season.no_archive": "No past seasons yet.",
        "season.no_rules": "No season rules created yet.",
        "season.back": "Back to Seasons",
        "season.name": "Season Name",
        "season.status": "Status",
        "season.start_date": "Start Date",
        "season.save_rules": "Save Season Rules",
        "season.delete": "Delete Season",
        "season.delete_warning": "All matches, leaderboard results, penalties, and rule versions for this season will be permanently deleted. Enter your current admin password to confirm.",
        "season.delete_password": "Admin Password",
        "season.delete_confirm": "Permanently delete season “{name}” and all of its leaderboard and match data?",
        "match.entry": "Match Entry",
        "match.edit": "Edit Match",
        "match.edit_hint": "Changes will recalculate placement, PT, uma, and penalties with the current season rules.",
        "match.season_total": "Current season total check: {total}",
        "match.time": "Match Time",
        "match.time_automatic": "The current Brisbane time is recorded automatically on submission",
        "match.type": "Match Type",
        "match.type_meetup": "Meetup",
        "match.type_private": "Private Game",
        "match.memo": "Memo",
        "match.optional": "Optional",
        "match.player_n": "Player {number}",
        "match.search_player": "Search by name or role",
        "match.choose_player": "Choose Player",
        "match.deleted_user": "Deleted",
        "match.final_score": "Final Score",
        "match.penalty": "Penalty (deducted from final PT)",
        "match.penalty_type": "Penalty Type",
        "match.penalty_type_placeholder": "Score reporting error",
        "match.penalty_reason": "Penalty Reason",
        "match.penalty_reason_placeholder": "Required when penalty exists",
        "match.current_total": "Current Total: ",
        "match.target_total": "Target Total: {total}",
        "match.submit": "Submit Match",
        "match.cancel": "Cancel",
        "match.save_recalculate": "Save and Recalculate",
        "match.unknown_title": "Match #{id}",
        "match.meta": "{time} · Referee: {referee}",
        "match.penalty_records": "Penalty Records",
        "match.no_penalty_records": "No penalty records.",
        "match.delete": "Delete Match",
        "match.delete_confirm": "Delete this match? The leaderboard will be recalculated.",
        "admin.title": "Admin",
        "admin.subtitle": "Edit user names, roles, and account status. Deleting users does not remove recorded results.",
        "admin.users": "Users",
        "admin.user_count": "{count}",
        "admin.registered_at": "{email} · {role} · Registered {created_at}",
        "admin.name_label": "User Name",
        "admin.role_label": "User Role",
        "admin.save": "Save",
        "admin.reset_password": "Reset Password",
        "admin.reset_confirm": "Reset {name}'s password? The temporary password is shown only once.",
        "admin.delete": "Delete",
        "admin.delete_confirm": "Delete {name}? Historical results will be retained.",
        "invites.title": "Invites",
        "invites.generate_title": "Generate New Invite",
        "invites.generate_hint": "The system creates a unique invite code automatically.",
        "invites.generate": "Generate",
        "invites.code": "Invite Code",
        "invites.role": "Role",
        "invites.status": "Status",
        "invites.used_by": "Used By",
        "player.current_points": "Current Points",
        "player.matches": "Matches",
        "player.avg_place": "Avg. Place",
        "player.first_fourth": "1st / 4th",
        "player.recent_trend": "Last 10 Trend",
        "player.trend_aria": "Last 10 placement line chart",
        "player.placement_detail": "{placement} place · {score}",
        "player.no_matches": "No matches yet.",
        "player.penalties": "Penalties",
        "player.no_penalties": "No penalty records.",
        "flash.login_required": "Please log in first.",
        "flash.permission_denied": "This account does not have permission.",
        "flash.register_missing": "Please complete all registration fields.",
        "flash.invite_invalid": "The invite code is invalid or has already been used.",
        "flash.email_registered": "This email is already registered.",
        "flash.register_success": "Registration complete. Please log in.",
        "flash.login_success": "Welcome back.",
        "flash.login_invalid": "Email or password is incorrect.",
        "flash.logout_success": "Logged out.",
        "flash.invite_role_invalid": "Invite role is invalid.",
        "flash.invite_created": "Invite code {code} created.",
        "flash.invite_conflict": "Invite code collision. Please try again.",
        "flash.user_missing": "User not found.",
        "flash.user_name_required": "User name is required.",
        "flash.deleted_user_locked": "Deleted users cannot be edited.",
        "flash.user_role_invalid": "Users can only be set as Referee or Player.",
        "flash.user_updated": "{name} updated.",
        "flash.super_admin_delete_denied": "The super admin cannot be deleted.",
        "flash.user_deleted": "{name} deleted. Historical results were retained.",
        "flash.deleted_user_password_locked": "Deleted users cannot have passwords reset.",
        "flash.super_admin_password_locked": "The super admin password should be changed by the owner to avoid locking the admin account.",
        "flash.temporary_password": "{name}'s temporary password: {password}. Share it only with that user and remind them to change it soon.",
        "flash.season_name_required": "Please enter a season name.",
        "flash.season_created": "Season created.",
        "flash.season_missing": "Season not found.",
        "flash.season_updated": "Season rules updated and version history retained.",
        "flash.season_password_invalid": "The admin password is incorrect. The season was not deleted.",
        "flash.season_deleted": "Season “{name}” and its leaderboard and match data were deleted.",
        "flash.season_required": "Please create and activate a season first.",
        "flash.match_created": "Match entered and leaderboard recalculated.",
        "flash.match_missing": "Match not found.",
        "flash.match_updated": "Match result updated and points recalculated.",
        "flash.match_delete_missing": "Match not found or already deleted.",
        "flash.match_deleted": "Match deleted and leaderboard recalculated from remaining records.",
        "flash.player_missing": "Player not found.",
        "validation.players_required": "Please choose all 4 players.",
        "validation.players_unique": "Players cannot be duplicated.",
        "validation.score_total": "The four final scores must equal the season starting total: {total}.",
        "validation.penalty_reason_required": "Penalty reason is required when penalty points are entered.",
        "match.default_penalty_type": "Admin penalty",
    },
}

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


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    is_render = os.environ.get("RENDER", "false").lower() in {"1", "true", "yes", "on"}
    secure_cookie = os.environ.get(
        "SESSION_COOKIE_SECURE",
        "true" if is_render else "false",
    ).lower() in {"1", "true", "yes", "on"}
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=secure_cookie,
        SESSION_REFRESH_EACH_REQUEST=True,
    )
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    @app.before_request
    def load_user() -> None:
        ensure_database_initialized()
        ensure_user_soft_delete_columns()
        ensure_announcements_table()
        ensure_meetups_tables()
        ensure_admin_password()
        ensure_match_type_values()
        user_id = session.get("user_id")
        g.user = query_one("select * from users where id = ? and is_deleted = 0", (user_id,)) if user_id else None
        if user_id and g.user is None:
            session.clear()

    @app.context_processor
    def inject_globals() -> dict:
        season = current_season()
        locale = get_locale()
        return {
            "current_user": g.get("user"),
            "roles": ROLE_LABELS[locale],
            "current_season": season,
            "rule_labels": RULE_LABELS,
            "field_labels": FIELD_LABELS,
            "today_date": today_date(),
            "locale": locale,
            "t": translate,
            "match_type_label": match_type_label,
            "default_meetup_venue": DEFAULT_MEETUP_VENUE,
        }

    @app.cli.command("init-db")
    def init_db_command() -> None:
        init_db()
        print("Initialized the database.")

    @app.route("/")
    def index():
        announcements = query_all(
            """
            select a.*, u.display_name as author_name
            from announcements a left join users u on u.id = a.author_id
            order by a.created_at desc, a.id desc
            """
        )
        return render_template(
            "index.html",
            latest_announcement=announcements[0] if announcements else None,
            past_announcements=announcements[1:],
        )

    @app.route("/about")
    def about():
        return render_template("about.html")

    @app.route("/meetups")
    @login_required
    def meetups():
        auto_archive_expired_meetups()
        per_page = 8
        page = max(request.args.get("page", 1, type=int), 1)
        total = query_one("select count(*) as c from meetups")["c"]
        pages = max((total + per_page - 1) // per_page, 1)
        if page > pages:
            return redirect(url_for("meetups", page=pages))
        meetup_rows = query_all(
            """
            select m.*, u.display_name as creator_name, count(ms.id) as attendee_count
            from meetups m
            left join users u on u.id = m.created_by
            left join meetup_signups ms on ms.meetup_id = m.id
            group by m.id
            order by m.meetup_at desc, m.id desc
            limit ? offset ?
            """,
            (per_page, (page - 1) * per_page),
        )
        meetup_items = []
        for meetup in meetup_rows:
            item = dict(meetup)
            item["status"] = meetup_status(meetup)
            meetup_items.append(item)
        pagination = {
            "page": page,
            "pages": pages,
            "total": total,
            "has_prev": page > 1,
            "has_next": page < pages,
            "prev_page": page - 1,
            "next_page": page + 1,
        }
        return render_template("meetups.html", meetups=meetup_items, pagination=pagination)

    @app.route("/meetups/<int:meetup_id>")
    @login_required
    def meetup_detail(meetup_id: int):
        auto_archive_expired_meetups()
        meetup = query_one(
            """
            select m.*, u.display_name as creator_name
            from meetups m left join users u on u.id = m.created_by
            where m.id = ?
            """,
            (meetup_id,),
        )
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        attendees = query_all(
            """
            select ms.user_id, ms.created_at, u.display_name, u.role
            from meetup_signups ms join users u on u.id = ms.user_id
            where ms.meetup_id = ?
            order by ms.created_at asc, ms.id asc
            """,
            (meetup_id,),
        )
        eligible_users = []
        if g.user["role"] == "super_admin":
            eligible_users = query_all(
                """
                select u.id, u.display_name, u.role
                from users u
                where u.is_deleted = 0
                  and not exists (
                    select 1 from meetup_signups ms
                    where ms.meetup_id = ? and ms.user_id = u.id
                  )
                order by u.display_name
                """,
                (meetup_id,),
            )
        status = meetup_status(meetup)
        is_signed_up = any(attendee["user_id"] == g.user["id"] for attendee in attendees)
        return render_template(
            "meetup_detail.html",
            meetup=meetup,
            attendees=attendees,
            eligible_users=eligible_users,
            status=status,
            is_signed_up=is_signed_up,
        )

    @app.route("/admin/meetups/new", methods=("POST",))
    @role_required("super_admin")
    def meetup_new():
        meetup_at = parse_local_datetime(request.form.get("meetup_at", ""))
        signup_deadline = parse_local_datetime(request.form.get("signup_deadline", ""))
        venue = request.form.get("venue", "").strip() or DEFAULT_MEETUP_VENUE
        if not meetup_at or not signup_deadline:
            flash(translate("meetup.time_required"), "error")
        elif signup_deadline > meetup_at:
            flash(translate("meetup.deadline_order"), "error")
        else:
            timestamp = now()
            execute(
                "insert into meetups (meetup_at, signup_deadline, venue, created_by, created_at, updated_at) values (?, ?, ?, ?, ?, ?)",
                (meetup_at, signup_deadline, venue, g.user["id"], timestamp, timestamp),
            )
            flash(translate("meetup.created"), "success")
        return redirect(url_for("meetups"))

    @app.route("/admin/meetups/<int:meetup_id>/edit", methods=("GET", "POST"))
    @role_required("super_admin")
    def meetup_edit(meetup_id: int):
        meetup = query_one("select * from meetups where id = ?", (meetup_id,))
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        if request.method == "POST":
            meetup_at = parse_local_datetime(request.form.get("meetup_at", ""))
            signup_deadline = parse_local_datetime(request.form.get("signup_deadline", ""))
            venue = request.form.get("venue", "").strip() or DEFAULT_MEETUP_VENUE
            if not meetup_at or not signup_deadline:
                flash(translate("meetup.time_required"), "error")
            elif signup_deadline > meetup_at:
                flash(translate("meetup.deadline_order"), "error")
            else:
                execute(
                    "update meetups set meetup_at = ?, signup_deadline = ?, venue = ?, updated_at = ? where id = ?",
                    (meetup_at, signup_deadline, venue, now(), meetup_id),
                )
                flash(translate("meetup.updated"), "success")
                return redirect(url_for("meetup_detail", meetup_id=meetup_id))
        return render_template(
            "meetup_form.html",
            meetup=meetup,
            meetup_time=meetup["meetup_at"].replace(" ", "T")[:16],
            signup_deadline=meetup["signup_deadline"].replace(" ", "T")[:16],
            meetup_venue=meetup["venue"],
        )

    @app.route("/meetups/<int:meetup_id>/signup", methods=("POST",))
    @login_required
    def meetup_signup(meetup_id: int):
        auto_archive_expired_meetups()
        meetup = query_one("select * from meetups where id = ?", (meetup_id,))
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        if meetup_status(meetup) != "open":
            flash(translate("meetup.signup_closed"), "error")
            return redirect(url_for("meetup_detail", meetup_id=meetup_id))
        try:
            execute(
                "insert into meetup_signups (meetup_id, user_id, created_at) values (?, ?, ?)",
                (meetup_id, g.user["id"], now()),
            )
            flash(translate("meetup.signup_success"), "success")
        except sqlite3.IntegrityError:
            flash(translate("meetup.signup_duplicate"), "error")
        return redirect(url_for("meetup_detail", meetup_id=meetup_id))

    @app.route("/admin/meetups/<int:meetup_id>/archive", methods=("POST",))
    @role_required("super_admin")
    def meetup_archive(meetup_id: int):
        meetup = query_one("select id from meetups where id = ?", (meetup_id,))
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        execute(
            "update meetups set archived_at = coalesce(archived_at, ?), archived_by = coalesce(archived_by, ?), updated_at = ? where id = ?",
            (now(), g.user["id"], now(), meetup_id),
        )
        flash(translate("meetup.archived_success"), "success")
        return redirect(url_for("meetup_detail", meetup_id=meetup_id))

    @app.route("/admin/meetups/<int:meetup_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def meetup_delete(meetup_id: int):
        meetup = query_one("select id from meetups where id = ?", (meetup_id,))
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        db = get_db()
        db.execute("delete from meetup_signups where meetup_id = ?", (meetup_id,))
        db.execute("delete from meetups where id = ?", (meetup_id,))
        db.commit()
        flash(translate("meetup.deleted_success"), "success")
        return redirect(url_for("meetups"))

    @app.route("/admin/meetups/<int:meetup_id>/attendees/add", methods=("POST",))
    @role_required("super_admin")
    def meetup_attendee_add(meetup_id: int):
        meetup = query_one("select id from meetups where id = ?", (meetup_id,))
        user_id = request.form.get("user_id", type=int)
        user = query_one("select id from users where id = ? and is_deleted = 0", (user_id,)) if user_id else None
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        if not user:
            flash(translate("meetup.member_missing"), "error")
        else:
            try:
                execute(
                    "insert into meetup_signups (meetup_id, user_id, created_at) values (?, ?, ?)",
                    (meetup_id, user_id, now()),
                )
                flash(translate("meetup.member_added"), "success")
            except sqlite3.IntegrityError:
                flash(translate("meetup.signup_duplicate"), "error")
        return redirect(url_for("meetup_detail", meetup_id=meetup_id))

    @app.route("/admin/meetups/<int:meetup_id>/attendees/<int:user_id>/remove", methods=("POST",))
    @role_required("super_admin")
    def meetup_attendee_remove(meetup_id: int, user_id: int):
        meetup = query_one("select id from meetups where id = ?", (meetup_id,))
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        signup = query_one(
            "select id from meetup_signups where meetup_id = ? and user_id = ?",
            (meetup_id, user_id),
        )
        if not signup:
            flash(translate("meetup.member_missing"), "error")
        else:
            execute("delete from meetup_signups where id = ?", (signup["id"],))
            flash(translate("meetup.member_removed"), "success")
        return redirect(url_for("meetup_detail", meetup_id=meetup_id))

    @app.route("/matches")
    def matches():
        per_page = 20
        page = max(request.args.get("page", 1, type=int), 1)
        total = query_one("select count(*) as c from matches")["c"]
        pages = max((total + per_page - 1) // per_page, 1)
        if page > pages:
            return redirect(url_for("matches", page=pages))
        rows = query_all(
            """
            select m.*, u.display_name as referee_name
            from matches m left join users u on u.id = m.referee_id
            order by m.played_at desc, m.id desc limit ? offset ?
            """,
            (per_page, (page - 1) * per_page),
        )
        pagination = {
            "page": page,
            "pages": pages,
            "total": total,
            "has_prev": page > 1,
            "has_next": page < pages,
            "prev_page": page - 1,
            "next_page": page + 1,
        }
        return render_template("matches.html", matches=rows, pagination=pagination)

    @app.route("/admin/announcements", methods=("GET", "POST"))
    @role_required("super_admin")
    def announcements():
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            if not title or not content:
                flash(translate("announcement.required"), "error")
            else:
                timestamp = now()
                execute(
                    "insert into announcements (title, content, author_id, created_at, updated_at) values (?, ?, ?, ?, ?)",
                    (title, content, g.user["id"], timestamp, timestamp),
                )
                flash(translate("announcement.created"), "success")
                return redirect(url_for("announcements"))
        rows = query_all(
            """
            select a.*, u.display_name as author_name
            from announcements a left join users u on u.id = a.author_id
            order by a.created_at desc, a.id desc
            """
        )
        return render_template("announcements.html", announcements=rows)

    @app.route("/admin/announcements/<int:announcement_id>/edit", methods=("GET", "POST"))
    @role_required("super_admin")
    def announcement_edit(announcement_id: int):
        announcement = query_one("select * from announcements where id = ?", (announcement_id,))
        if not announcement:
            flash(translate("announcement.missing"), "error")
            return redirect(url_for("announcements"))
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            if not title or not content:
                flash(translate("announcement.required"), "error")
            else:
                execute(
                    "update announcements set title = ?, content = ?, updated_at = ? where id = ?",
                    (title, content, now(), announcement_id),
                )
                flash(translate("announcement.updated"), "success")
                return redirect(url_for("announcements"))
        return render_template("announcement_form.html", announcement=announcement)

    @app.route("/admin/announcements/<int:announcement_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def announcement_delete(announcement_id: int):
        announcement = query_one("select id from announcements where id = ?", (announcement_id,))
        if not announcement:
            flash(translate("announcement.missing"), "error")
        else:
            execute("delete from announcements where id = ?", (announcement_id,))
            flash(translate("announcement.deleted"), "success")
        return redirect(url_for("announcements"))

    @app.route("/favicon.ico")
    def favicon():
        return redirect(url_for("static", filename="web_logo.jpg"))

    @app.route("/language/<locale>")
    def set_language(locale: str):
        if locale in SUPPORTED_LOCALES:
            session["locale"] = locale
        return redirect(request.referrer or url_for("index"))

    @app.route("/register", methods=("GET", "POST"))
    def register():
        if request.method == "POST":
            display_name = request.form["display_name"].strip()
            email = request.form["email"].strip().lower()
            password = request.form["password"]
            invite_code = request.form["invite_code"].strip().upper()
            invite = query_one(
                "select * from invite_codes where code = ? and used_by is null",
                (invite_code,),
            )
            error = None
            if not display_name or not email or not password:
                error = translate("flash.register_missing")
            elif not invite:
                error = translate("flash.invite_invalid")
            elif query_one("select id from users where email = ? and is_deleted = 0", (email,)):
                error = translate("flash.email_registered")

            if error:
                flash(error, "error")
            else:
                db = get_db()
                cur = db.execute(
                    """
                    insert into users (display_name, email, password_hash, role, created_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        display_name,
                        email,
                        generate_password_hash(password, method="pbkdf2:sha256"),
                        invite["role"],
                        now(),
                    ),
                )
                db.execute(
                    "update invite_codes set used_by = ?, used_at = ? where id = ?",
                    (cur.lastrowid, now(), invite["id"]),
                )
                db.commit()
                flash(translate("flash.register_success"), "success")
                return redirect(url_for("login"))
        return render_template("register.html")

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if request.method == "POST":
            email = request.form["email"].strip().lower()
            password = request.form["password"]
            user = query_one("select * from users where email = ? and is_deleted = 0", (email,))
            if user and check_password_hash(user["password_hash"], password):
                selected_locale = session.get("locale")
                session.clear()
                session.permanent = request.form.get("remember") == "1"
                if selected_locale in SUPPORTED_LOCALES:
                    session["locale"] = selected_locale
                session["user_id"] = user["id"]
                flash(translate("flash.login_success"), "success")
                return redirect(url_for("index"))
            flash(translate("flash.login_invalid"), "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        selected_locale = session.get("locale")
        session.clear()
        if selected_locale in SUPPORTED_LOCALES:
            session["locale"] = selected_locale
        flash(translate("flash.logout_success"), "success")
        return redirect(url_for("index"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return redirect(url_for("index"))

    @app.route("/admin/invites", methods=("GET", "POST"))
    @role_required("super_admin")
    def invites():
        if request.method == "POST":
            role = request.form["role"]
            if role not in ("referee", "user"):
                flash(translate("flash.invite_role_invalid"), "error")
            else:
                code = generate_invite_code(role)
                try:
                    execute(
                        "insert into invite_codes (code, role, created_by, created_at) values (?, ?, ?, ?)",
                        (code, role, g.user["id"], now()),
                    )
                    flash(translate("flash.invite_created", code=code), "success")
                except sqlite3.IntegrityError:
                    flash(translate("flash.invite_conflict"), "error")
        codes = query_all(
            """
            select i.*, u.display_name as used_by_name
            from invite_codes i left join users u on u.id = i.used_by
            order by i.created_at desc
            """
        )
        return render_template("invites.html", codes=codes)

    @app.route("/admin/users")
    @role_required("super_admin")
    def admin_users():
        users = query_all(
            """
            select u.*
            from users u
            order by u.is_deleted asc, u.role asc, u.created_at desc
            """
        )
        return render_template("admin_users.html", users=users)

    @app.route("/admin/users/<int:user_id>/update", methods=("POST",))
    @role_required("super_admin")
    def admin_user_update(user_id: int):
        display_name = request.form.get("display_name", "").strip()
        role = request.form.get("role", "")
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            flash(translate("flash.user_missing"), "error")
        elif not display_name:
            flash(translate("flash.user_name_required"), "error")
        elif user["is_deleted"]:
            flash(translate("flash.deleted_user_locked"), "error")
        elif user["role"] != "super_admin" and role not in ("referee", "user"):
            flash(translate("flash.user_role_invalid"), "error")
        elif user["role"] == "super_admin":
            execute("update users set display_name = ? where id = ?", (display_name, user_id))
            flash(translate("flash.user_updated", name=display_name), "success")
        else:
            execute("update users set display_name = ?, role = ? where id = ?", (display_name, role, user_id))
            flash(translate("flash.user_updated", name=display_name), "success")
        return redirect(url_for("admin_users"))

    @app.route("/admin/users/<int:user_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def admin_user_delete(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            flash(translate("flash.user_missing"), "error")
        elif user["role"] == "super_admin":
            flash(translate("flash.super_admin_delete_denied"), "error")
        else:
            execute("update users set is_deleted = 1, deleted_at = ? where id = ?", (now(), user_id))
            flash(translate("flash.user_deleted", name=user["display_name"]), "success")
        return redirect(url_for("admin_users"))

    @app.route("/admin/users/<int:user_id>/reset-password", methods=("POST",))
    @role_required("super_admin")
    def admin_user_reset_password(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            flash(translate("flash.user_missing"), "error")
        elif user["is_deleted"]:
            flash(translate("flash.deleted_user_password_locked"), "error")
        elif user["role"] == "super_admin":
            flash(translate("flash.super_admin_password_locked"), "error")
        else:
            temporary_password = generate_temporary_password()
            execute(
                "update users set password_hash = ? where id = ?",
                (generate_password_hash(temporary_password, method="pbkdf2:sha256"), user_id),
            )
            flash(
                translate("flash.temporary_password", name=user["display_name"], password=temporary_password),
                "success",
            )
        return redirect(url_for("admin_users"))

    @app.route("/seasons")
    def seasons():
        seasons_data = query_all("select * from seasons order by start_date desc, id desc")
        active_season = query_one("select * from seasons where status = 'active' order by id desc limit 1")
        if not active_season and seasons_data:
            active_season = seasons_data[0]
        active_rules = normalize_rules(json.loads(active_season["rules_json"])) if active_season else None
        past_seasons = [season for season in seasons_data if not active_season or season["id"] != active_season["id"]]
        return render_template(
            "seasons.html",
            seasons=seasons_data,
            active_season=active_season,
            active_rules=active_rules,
            past_seasons=past_seasons,
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
        return render_template("season_detail.html", season=season, rules=normalize_rules(json.loads(season["rules_json"])))

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

    @app.route("/matches/new", methods=("GET", "POST"))
    @role_required("super_admin", "referee")
    def match_new():
        season = current_season()
        if not season:
            flash(translate("flash.season_required"), "error")
            return redirect(url_for("seasons"))
        players = query_all("select * from users where role in ('referee', 'user') and is_deleted = 0 order by display_name")
        if request.method == "POST":
            result = create_match_from_form(season, request.form)
            if result["ok"]:
                flash(translate("flash.match_created"), "success")
                return redirect(url_for("match_detail", match_id=result["match_id"]))
            for error in result["errors"]:
                flash(error, "error")
        return render_template(
            "match_form.html",
            season=season,
            players=players,
            rules=normalize_rules(json.loads(season["rules_json"])),
            match_time=current_match_time(),
        )

    @app.route("/matches/<int:match_id>")
    def match_detail(match_id: int):
        match = query_one(
            """
            select m.*, s.name as season_name, u.display_name as referee_name
            from matches m
            join seasons s on s.id = m.season_id
            left join users u on u.id = m.referee_id
            where m.id = ?
            """,
            (match_id,),
        )
        if not match:
            flash(translate("flash.match_missing"), "error")
            return redirect(url_for("index"))
        entries = query_all(
            """
            select me.*, u.display_name
            from match_entries me join users u on u.id = me.user_id
            where me.match_id = ?
            order by me.placement asc, me.final_score desc
            """,
            (match_id,),
        )
        penalties = query_all(
            """
            select p.*, u.display_name
            from penalties p join users u on u.id = p.user_id
            where p.match_id = ?
            order by p.id
            """,
            (match_id,),
        )
        return render_template("match_detail.html", match=match, entries=entries, penalties=penalties)

    @app.route("/matches/<int:match_id>/edit", methods=("GET", "POST"))
    @role_required("super_admin")
    def match_edit(match_id: int):
        match = query_one(
            """
            select m.*, s.name as season_name, s.rules_json
            from matches m join seasons s on s.id = m.season_id
            where m.id = ?
            """,
            (match_id,),
        )
        if not match:
            flash(translate("flash.match_missing"), "error")
            return redirect(url_for("index"))
        entries = query_all(
            "select * from match_entries where match_id = ? order by id",
            (match_id,),
        )
        involved_ids = [entry["user_id"] for entry in entries]
        if involved_ids:
            placeholders = ",".join("?" for _ in involved_ids)
            players = query_all(
                f"""
                select * from users
                where is_deleted = 0 or id in ({placeholders})
                order by display_name
                """,
                tuple(involved_ids),
            )
        else:
            players = query_all("select * from users where is_deleted = 0 order by display_name")

        if request.method == "POST":
            result = parse_match_result_form(match, request.form)
            if result["ok"]:
                update_match_from_result(match_id, match, request.form, result)
                flash(translate("flash.match_updated"), "success")
                return redirect(url_for("match_detail", match_id=match_id))
            for error in result["errors"]:
                flash(error, "error")

        penalty_lookup = {
            row["user_id"]: row
            for row in query_all(
                """
                select user_id, sum(points) as points,
                       group_concat(penalty_type, ' / ') as penalty_type,
                       group_concat(reason, '；') as reason
                from penalties
                where match_id = ?
                group by user_id
                """,
                (match_id,),
            )
        }
        edit_rows = []
        for entry in entries:
            penalty = penalty_lookup.get(entry["user_id"])
            edit_rows.append({"entry": entry, "penalty": penalty})
        rules = normalize_rules(json.loads(match["rules_json"]))
        return render_template(
            "match_edit.html",
            match=match,
            match_time=match["played_at"].replace(" ", "T")[:16],
            rows=edit_rows,
            players=players,
            rules=rules,
        )

    @app.route("/matches/<int:match_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def match_delete(match_id: int):
        match = query_one("select * from matches where id = ?", (match_id,))
        if not match:
            flash(translate("flash.match_delete_missing"), "error")
            return redirect(url_for("index"))

        db = get_db()
        db.execute("delete from penalties where match_id = ?", (match_id,))
        db.execute("delete from match_entries where match_id = ?", (match_id,))
        db.execute("delete from matches where id = ?", (match_id,))
        db.commit()
        flash(translate("flash.match_deleted"), "success")
        return redirect(url_for("leaderboard", season_id=match["season_id"]))

    @app.route("/leaderboard")
    def leaderboard():
        seasons_data = query_all("select * from seasons order by start_date desc, id desc")
        season_id = request.args.get("season_id", type=int)
        season = query_one("select * from seasons where id = ?", (season_id,)) if season_id else current_season()
        rows = get_leaderboard(season["id"]) if season else []
        finals_status = build_finals_status(season, rows, g.user) if season else None
        return render_template(
            "leaderboard.html",
            seasons=seasons_data,
            selected_season=season,
            rows=rows,
            finals_status=finals_status,
        )

    @app.route("/players/<int:user_id>")
    def player_profile(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            flash(translate("flash.player_missing"), "error")
            return redirect(url_for("leaderboard"))
        season = current_season()
        leaderboard = get_leaderboard(season["id"]) if season else []
        player_stats = next((row for row in leaderboard if row["user_id"] == user_id), None)
        history = query_all(
            """
            select m.played_at, me.final_score, me.placement, me.rank_points
            from match_entries me join matches m on m.id = me.match_id
            where me.user_id = ?
            order by m.played_at desc limit 10
            """,
            (user_id,),
        )
        penalties = query_all(
            "select * from penalties where user_id = ? order by created_at desc limit 8",
            (user_id,),
        )
        trend = build_placement_trend(history)
        return render_template(
            "player.html",
            user=user,
            stats=player_stats,
            history=history,
            trend=trend,
            penalties=penalties,
        )

    @app.route("/export/season/<int:season_id>.csv")
    @role_required("super_admin")
    def export_season(season_id: int):
        rows = get_leaderboard(season_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["rank", "player", "points", "matches", "avg_place", "first_rate", "fourth_rate", "penalties"])
        for idx, row in enumerate(rows, start=1):
            writer.writerow([
                idx,
                row["display_name"],
                row["total_points"],
                row["matches"],
                row["avg_place"],
                row["first_rate"],
                row["fourth_rate"],
                row["penalty_points"],
            ])
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=season-{season_id}-leaderboard.csv"},
        )

    @app.teardown_appcontext
    def close_db(_: Exception | None = None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    return app


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        ensure_database_initialized()
        DATABASE.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


def ensure_database_initialized() -> None:
    if DATABASE.exists():
        return
    init_db()


def ensure_user_soft_delete_columns() -> None:
    db = get_db()
    columns = {row["name"] for row in db.execute("pragma table_info(users)").fetchall()}
    if "is_deleted" not in columns:
        db.execute("alter table users add column is_deleted integer not null default 0")
    if "deleted_at" not in columns:
        db.execute("alter table users add column deleted_at text")
    db.commit()


def ensure_announcements_table() -> None:
    db = get_db()
    db.execute(
        """
        create table if not exists announcements (
          id integer primary key autoincrement,
          title text not null,
          content text not null,
          author_id integer not null,
          created_at text not null,
          updated_at text not null,
          foreign key (author_id) references users(id)
        )
        """
    )
    db.commit()


def ensure_meetups_tables() -> None:
    db = get_db()
    db.execute(
        """
        create table if not exists meetups (
          id integer primary key autoincrement,
          meetup_at text not null,
          signup_deadline text not null,
          venue text not null default 'upc 8 Gillingham street, QLD4102',
          archived_at text,
          archived_by integer,
          created_by integer not null,
          created_at text not null,
          updated_at text not null,
          foreign key (created_by) references users(id)
        )
        """
    )
    columns = {row["name"] for row in db.execute("pragma table_info(meetups)").fetchall()}
    if "signup_deadline" not in columns:
        db.execute("alter table meetups add column signup_deadline text")
    if "venue" not in columns:
        db.execute(
            "alter table meetups add column venue text not null default 'upc 8 Gillingham street, QLD4102'"
        )
    if "archived_at" not in columns:
        db.execute("alter table meetups add column archived_at text")
    if "archived_by" not in columns:
        db.execute("alter table meetups add column archived_by integer")
    db.execute("update meetups set signup_deadline = meetup_at where signup_deadline is null")
    db.execute(
        "update meetups set venue = ? where venue is null or trim(venue) = ''",
        (DEFAULT_MEETUP_VENUE,),
    )
    db.execute(
        """
        create table if not exists meetup_signups (
          id integer primary key autoincrement,
          meetup_id integer not null,
          user_id integer not null,
          created_at text not null,
          unique (meetup_id, user_id),
          foreign key (meetup_id) references meetups(id),
          foreign key (user_id) references users(id)
        )
        """
    )
    db.commit()


def ensure_admin_password() -> None:
    db = get_db()
    db.execute(
        """
        create table if not exists app_migrations (
          name text primary key,
          applied_at text not null
        )
        """
    )
    applied = db.execute(
        "select 1 from app_migrations where name = ?",
        (ADMIN_PASSWORD_MIGRATION,),
    ).fetchone()
    if applied:
        db.commit()
        return

    admins = db.execute(
        "select id from users where role = 'super_admin' and is_deleted = 0"
    ).fetchall()
    if len(admins) != 1:
        db.commit()
        return

    db.execute(
        "update users set password_hash = ? where id = ?",
        (ADMIN_PASSWORD_HASH, admins[0]["id"]),
    )
    db.execute(
        "insert into app_migrations (name, applied_at) values (?, ?)",
        (ADMIN_PASSWORD_MIGRATION, now()),
    )
    db.commit()


def ensure_match_type_values() -> None:
    migration_name = "normalize_match_types_v1"
    db = get_db()
    applied = db.execute(
        "select 1 from app_migrations where name = ?",
        (migration_name,),
    ).fetchone()
    if applied:
        return
    db.execute(
        """
        update matches
        set table_name = case
          when lower(trim(table_name)) = 'meetup' then 'meetup'
          when lower(trim(table_name)) in ('private', 'private game') then 'private'
          when instr(table_name, '机打') > 0 or instr(table_name, '手打') > 0 then 'private'
          else table_name
        end
        """
    )
    db.execute(
        "insert into app_migrations (name, applied_at) values (?, ?)",
        (migration_name, now()),
    )
    db.commit()


def execute(sql: str, params: tuple = ()) -> None:
    db = get_db()
    db.execute(sql, params)
    db.commit()


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    return get_db().execute(sql, params).fetchone()


def query_all(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return get_db().execute(sql, params).fetchall()


def now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def current_match_time() -> str:
    return datetime.now(ZoneInfo("Australia/Brisbane")).strftime("%Y-%m-%d %H:%M:%S")


def today_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def get_locale() -> str:
    selected = session.get("locale")
    if selected in SUPPORTED_LOCALES:
        return selected
    best = request.accept_languages.best_match(SUPPORTED_LOCALES)
    return best if best in SUPPORTED_LOCALES else "zh"


def translate(key: str, **kwargs) -> str:
    locale = get_locale()
    text = TRANSLATIONS.get(locale, {}).get(key, TRANSLATIONS["zh"].get(key, key))
    return text.format(**kwargs) if kwargs else text


def normalize_match_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "meetup":
        return "meetup"
    return "private"


def match_type_label(value: str | None) -> str:
    if not value:
        return translate("home.unnamed_match")
    if value.strip().lower() == "meetup":
        return translate("match.type_meetup")
    if value.strip().lower() in {"private", "private game", "机打", "手打"}:
        return translate("match.type_private")
    return value


def normalize_datetime(value: str) -> str:
    if not value:
        return now()
    return value.replace("T", " ") + (":00" if len(value) == 16 else "")


def parse_local_datetime(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def brisbane_local_now() -> datetime:
    return datetime.now(ZoneInfo("Australia/Brisbane")).replace(tzinfo=None)


def meetup_status(meetup) -> str:
    if meetup["archived_at"]:
        return "archived"
    deadline = datetime.fromisoformat(meetup["signup_deadline"] or meetup["meetup_at"])
    return "closed" if brisbane_local_now() > deadline else "open"


def auto_archive_expired_meetups() -> None:
    cutoff = (brisbane_local_now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    db = get_db()
    db.execute(
        """
        update meetups
        set archived_at = ?, updated_at = ?
        where archived_at is null and meetup_at <= ?
        """,
        (now(), now(), cutoff),
    )
    db.commit()


def generate_temporary_password(length: int = 12) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_invite_code(role: str) -> str:
    prefix = "REF" if role == "referee" else "PLAY"
    alphabet = string.ascii_uppercase + string.digits
    while True:
        token = "".join(secrets.choice(alphabet) for _ in range(6))
        code = f"{prefix}-{token[:3]}-{token[3:]}"
        if not query_one("select id from invite_codes where code = ?", (code,)):
            return code


def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash(translate("flash.login_required"), "error")
            return redirect(url_for("login"))
        return view(**kwargs)
    return wrapped_view


def role_required(*roles: str):
    def decorator(view):
        @functools.wraps(view)
        def wrapped_view(**kwargs):
            if g.user is None:
                flash(translate("flash.login_required"), "error")
                return redirect(url_for("login"))
            if g.user["role"] not in roles:
                flash(translate("flash.permission_denied"), "error")
                return redirect(url_for("index"))
            return view(**kwargs)
        return wrapped_view
    return decorator


def current_season() -> sqlite3.Row | None:
    return query_one("select * from seasons where status = 'active' order by id desc limit 1")


def parse_rules_form(form) -> dict:
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


def parse_match_result_form(season, form) -> dict:
    rules = normalize_rules(json.loads(season["rules_json"]))
    start_total = int(rules["points"]["default_starting_points"]) * 4
    players = [int(form.get(f"player_{idx}") or 0) for idx in range(4)]
    scores = [int(form.get(f"score_{idx}") or 0) for idx in range(4)]
    penalty_values = [int(form.get(f"penalty_{idx}") or 0) for idx in range(4)]
    default_penalty_type = translate("match.default_penalty_type")
    penalty_types = [form.get(f"penalty_type_{idx}", default_penalty_type).strip() or default_penalty_type for idx in range(4)]
    penalty_reasons = [form.get(f"penalty_reason_{idx}", "").strip() for idx in range(4)]
    errors = []

    if any(player == 0 for player in players):
        errors.append(translate("validation.players_required"))
    if len(set(players)) != 4:
        errors.append(translate("validation.players_unique"))
    if sum(scores) != start_total:
        errors.append(translate("validation.score_total", total=start_total))
    for value, reason in zip(penalty_values, penalty_reasons):
        if value and not reason:
            errors.append(translate("validation.penalty_reason_required"))
            break
    if errors:
        return {"ok": False, "errors": errors}

    placements = calculate_placements(scores)
    rank_points = calculate_rank_points(scores, placements, rules, penalty_values)
    return {
        "ok": True,
        "rules": rules,
        "players": players,
        "scores": scores,
        "penalty_values": penalty_values,
        "penalty_types": penalty_types,
        "penalty_reasons": penalty_reasons,
        "placements": placements,
        "rank_points": rank_points,
    }


def create_match_from_form(season, form) -> dict:
    result = parse_match_result_form(season, form)
    if not result["ok"]:
        return result
    db = get_db()
    cur = db.execute(
        "insert into matches (season_id, referee_id, played_at, table_name, memo, created_at) values (?, ?, ?, ?, ?, ?)",
        (
            season["id"],
            g.user["id"],
            current_match_time(),
            normalize_match_type(form.get("table_name", "")),
            form.get("memo", "").strip(),
            now(),
        ),
    )
    match_id = cur.lastrowid
    insert_match_result_rows(db, match_id, season["id"], result, g.user["id"])
    db.commit()
    return {"ok": True, "match_id": match_id}


def update_match_from_result(match_id: int, match, form, result: dict) -> None:
    db = get_db()
    db.execute(
        """
        update matches
        set played_at = ?, table_name = ?, memo = ?
        where id = ?
        """,
        (
            normalize_datetime(form.get("played_at", "")),
            normalize_match_type(form.get("table_name", "")),
            form.get("memo", "").strip(),
            match_id,
        ),
    )
    db.execute("delete from penalties where match_id = ?", (match_id,))
    db.execute("delete from match_entries where match_id = ?", (match_id,))
    insert_match_result_rows(db, match_id, match["season_id"], result, g.user["id"])
    db.commit()


def insert_match_result_rows(db: sqlite3.Connection, match_id: int, season_id: int, result: dict, actor_id: int) -> None:
    for idx, user_id in enumerate(result["players"]):
        db.execute(
            """
            insert into match_entries (match_id, user_id, final_score, placement, rank_points, penalty_points)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                match_id,
                user_id,
                result["scores"][idx],
                result["placements"][idx],
                result["rank_points"][idx],
                result["penalty_values"][idx],
            ),
        )
        if result["penalty_values"][idx]:
            db.execute(
                """
                insert into penalties (match_id, season_id, user_id, penalty_type, points, reason, created_by, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    season_id,
                    user_id,
                    result["penalty_types"][idx],
                    result["penalty_values"][idx],
                    result["penalty_reasons"][idx],
                    actor_id,
                    now(),
                ),
            )


def calculate_placements(scores: list[int]) -> list[float]:
    placements = []
    sorted_scores = sorted(scores, reverse=True)
    for score in scores:
        indexes = [idx + 1 for idx, item in enumerate(sorted_scores) if item == score]
        placements.append(sum(indexes) / len(indexes))
    return placements


def calculate_rank_points(scores: list[int], placements: list[float], rules: dict, penalties: list[int]) -> list[float]:
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


def build_placement_trend(history: list[sqlite3.Row]) -> dict:
    ordered = list(reversed(history))
    if not ordered:
        return {"points": "", "nodes": []}
    left, right = 16, 96
    top, bottom = 14, 86
    span_x = right - left
    span_y = bottom - top
    nodes = []
    for idx, row in enumerate(ordered):
        x = (left + span_x / 2) if len(ordered) == 1 else left + (span_x * idx / (len(ordered) - 1))
        placement = float(row["placement"])
        y = top + ((placement - 1) / 3) * span_y
        nodes.append(
            {
                "x": round(x, 2),
                "y": round(y, 2),
                "placement": placement,
                "rank_points": row["rank_points"],
                "played_at": row["played_at"],
            }
        )
    return {
        "points": " ".join(f"{node['x']},{node['y']}" for node in nodes),
        "nodes": nodes,
    }


def get_leaderboard(season_id: int) -> list[dict]:
    rows = query_all(
        """
        select
            u.id as user_id,
            u.display_name,
            count(me.id) as matches,
            round(coalesce(sum(me.rank_points), 0), 1) as total_points,
            round(avg(me.placement), 2) as avg_place,
            round(avg(case when me.placement = 1 then 1.0 else 0 end) * 100, 1) as first_rate,
            round(avg(case when me.placement = 4 then 1.0 else 0 end) * 100, 1) as fourth_rate,
            coalesce(sum(me.penalty_points), 0) as penalty_points
        from users u
        join match_entries me on me.user_id = u.id
        join matches m on m.id = me.match_id
        where m.season_id = ?
        group by u.id, u.display_name
        order by total_points desc, avg_place asc, matches desc
        """,
        (season_id,),
    )
    return [dict(row) for row in rows]


def build_finals_status(season: sqlite3.Row, rows: list[dict], user: sqlite3.Row | None) -> dict:
    rules = normalize_rules(json.loads(season["rules_json"]))
    required_matches = int(rules["points"].get("final_required_matches", 8))
    if user is None:
        return {
            "logged_in": False,
            "required_matches": required_matches,
            "matches": 0,
            "remaining_matches": required_matches,
            "matches_met": False,
            "cup_status": translate("finals.login_to_view"),
            "championship_gap": None,
            "yakitori_gap": None,
        }

    user_row = next((row for row in rows if row["user_id"] == user["id"]), None)
    user_rank = next((idx for idx, row in enumerate(rows, start=1) if row["user_id"] == user["id"]), None)
    if user_row is None:
        normalized_name = user["display_name"].strip().lower()
        user_rank, user_row = next(
            (
                (idx, row)
                for idx, row in enumerate(rows, start=1)
                if row["display_name"].strip().lower() == normalized_name
            ),
            (None, None),
        )
    matches = int(user_row["matches"]) if user_row else 0
    points = float(user_row["total_points"]) if user_row else 0.0
    remaining_matches = max(required_matches - matches, 0)
    matches_met = remaining_matches == 0

    bottom_start_rank = max(len(rows) - 3, 1)
    is_top_four = user_rank is not None and user_rank <= 4
    is_bottom_four = user_rank is not None and user_rank >= bottom_start_rank and len(rows) >= 4
    championship_cutoff = float(rows[3]["total_points"]) if len(rows) >= 4 else None
    yakitori_cutoff = float(rows[bottom_start_rank - 1]["total_points"]) if len(rows) >= 4 else None

    if is_top_four:
        cup_status = translate("finals.championship_met")
        championship_gap = 0
        yakitori_gap = None
    elif is_bottom_four:
        cup_status = translate("finals.yakitori_met")
        championship_gap = None
        yakitori_gap = 0
    else:
        championship_gap = max(round((championship_cutoff or 0) - points, 1), 0) if championship_cutoff is not None else None
        yakitori_gap = max(round(points - (yakitori_cutoff or 0), 1), 0) if yakitori_cutoff is not None else None
        if championship_gap is None or yakitori_gap is None:
            cup_status = translate("finals.not_enough_data")
        else:
            cup_status = translate("finals.not_met")

    return {
        "logged_in": True,
        "required_matches": required_matches,
        "matches": matches,
        "remaining_matches": remaining_matches,
        "matches_met": matches_met,
        "rank": user_rank,
        "points": points,
        "cup_status": cup_status,
        "championship_gap": championship_gap,
        "yakitori_gap": yakitori_gap,
    }


def get_penalty_records(season_id: int) -> list[sqlite3.Row]:
    return query_all(
        """
        select
            p.*,
            u.display_name as player_name,
            m.played_at,
            m.table_name,
            r.display_name as referee_name
        from penalties p
        join users u on u.id = p.user_id
        join matches m on m.id = p.match_id
        left join users r on r.id = p.created_by
        where p.season_id = ?
        order by m.played_at desc, p.id desc
        """,
        (season_id,),
    )


def init_db() -> None:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE)
    with open(BASE_DIR / "schema.sql", encoding="utf-8") as f:
        db.executescript(f.read())
    db.row_factory = sqlite3.Row
    admin_id = db.execute(
        """
        insert into users (display_name, email, password_hash, role, created_at)
        values ('Admin', 'admin@example.com', ?, 'super_admin', ?)
        """,
        (ADMIN_PASSWORD_HASH, now()),
    ).lastrowid
    if SEED_DEMO_DATA:
        seed_demo_data(db, admin_id)
    db.commit()
    db.close()


def seed_demo_data(db: sqlite3.Connection, admin_id: int) -> None:
    season_1_rules = json.loads(json.dumps(DEFAULT_RULES))
    season_2_rules = json.loads(json.dumps(DEFAULT_RULES))
    season_3_rules = json.loads(json.dumps(DEFAULT_RULES))
    season_2_rules["points"]["uma_2nd"] = 5
    season_2_rules["points"]["uma_3rd"] = -15
    season_2_rules["points"]["uma_4th"] = -30
    season_2_rules["common"]["red_five"] = "4赤"
    season_2_rules["others"]["west_extension"] = True
    season_3_rules["points"]["default_starting_points"] = 30000
    season_3_rules["points"]["uma_1st"] = 20
    season_3_rules["points"]["uma_2nd"] = 5
    season_3_rules["points"]["uma_3rd"] = -15
    season_3_rules["points"]["uma_4th"] = -30
    season_3_rules["common"]["red_five"] = "4赤"

    season_1_id = db.execute(
        """
        insert into seasons (name, status, start_date, rules_json, version, created_at, updated_at)
        values ('Brisbane Riichi 2026 Autumn', 'archived', '2026-04-01', ?, 1, ?, ?)
        """,
        (json.dumps(season_1_rules, ensure_ascii=False), now(), now()),
    ).lastrowid
    season_2_id = db.execute(
        """
        insert into seasons (name, status, start_date, rules_json, version, created_at, updated_at)
        values ('Brisbane Riichi 2026 Winter', 'archived', '2026-07-01', ?, 2, ?, ?)
        """,
        (json.dumps(season_2_rules, ensure_ascii=False), now(), now()),
    ).lastrowid
    season_3_id = db.execute(
        """
        insert into seasons (name, status, start_date, rules_json, version, created_at, updated_at)
        values ('S11', 'active', '2026-08-21', ?, 3, ?, ?)
        """,
        (json.dumps(season_3_rules, ensure_ascii=False), now(), now()),
    ).lastrowid
    db.execute(
        "insert into rule_versions (season_id, rules_json, changed_by, changed_at) values (?, ?, ?, ?)",
        (season_2_id, json.dumps(season_2_rules, ensure_ascii=False), admin_id, now()),
    )
    db.execute(
        "insert into rule_versions (season_id, rules_json, changed_by, changed_at) values (?, ?, ?, ?)",
        (season_3_id, json.dumps(season_3_rules, ensure_ascii=False), admin_id, now()),
    )

    demo_users = [
        ("Mika Chen", "mika@example.com", "referee"),
        ("Daniel Wong", "daniel@example.com", "referee"),
        ("Wang.C", "wangc@example.com", "referee"),
        ("Rua", "3474189100@qq.com", "user"),
        ("Aiko Tan", "aiko@example.com", "user"),
        ("Kenji Sato", "kenji@example.com", "user"),
        ("Liam Brown", "liam@example.com", "user"),
        ("Sophie Lee", "sophie@example.com", "user"),
        ("Noah Smith", "noah@example.com", "user"),
        ("Yuki Mori", "yuki@example.com", "user"),
        ("Emma Davis", "emma@example.com", "user"),
        ("Haru Ito", "haru@example.com", "user"),
    ]
    user_ids = {}
    password_hash = generate_password_hash("demo1234", method="pbkdf2:sha256")
    for display_name, email, role in demo_users:
        user_ids[display_name] = db.execute(
            """
            insert into users (display_name, email, password_hash, role, created_at)
            values (?, ?, ?, ?, ?)
            """,
            (display_name, email, password_hash, role, now()),
        ).lastrowid

    demo_matches = [
        (
            season_1_id,
            season_1_rules,
            "2026-04-05 19:20:00",
            "Autumn A",
            "赛季揭幕桌",
            "Mika Chen",
            [("Aiko Tan", 38200), ("Kenji Sato", 26700), ("Liam Brown", 20400), ("Sophie Lee", 14700)],
            [],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-04-12 18:40:00",
            "Autumn B",
            "同分顺位演示",
            "Daniel Wong",
            [("Noah Smith", 31000), ("Yuki Mori", 31000), ("Emma Davis", 23000), ("Haru Ito", 15000)],
            [],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-04-19 19:10:00",
            "Autumn A",
            "含罚则",
            "Mika Chen",
            [("Sophie Lee", 41100), ("Aiko Tan", 28600), ("Haru Ito", 17200), ("Kenji Sato", 13100)],
            [{"player": "Kenji Sato", "points": 2, "type": "终局报分错误", "reason": "复核时发现漏记一本场"}],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-05-03 18:55:00",
            "Autumn C",
            "常规赛",
            "Daniel Wong",
            [("Liam Brown", 33500), ("Emma Davis", 29200), ("Yuki Mori", 22100), ("Noah Smith", 15200)],
            [],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-05-17 19:30:00",
            "Autumn B",
            "常规赛",
            "Mika Chen",
            [("Haru Ito", 36000), ("Aiko Tan", 28400), ("Noah Smith", 21600), ("Sophie Lee", 14000)],
            [],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-06-07 18:30:00",
            "Autumn Final",
            "秋季收官桌",
            "Daniel Wong",
            [("Emma Davis", 39000), ("Liam Brown", 25000), ("Kenji Sato", 23000), ("Yuki Mori", 13000)],
            [{"player": "Yuki Mori", "points": 1, "type": "迟到", "reason": "开赛迟到 12 分钟"}],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-07-06 19:00:00",
            "Winter A",
            "冬季赛第一轮",
            "Mika Chen",
            [("Aiko Tan", 45200), ("Noah Smith", 25100), ("Emma Davis", 18800), ("Liam Brown", 10900)],
            [],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-07-13 18:45:00",
            "Winter B",
            "冬季赛第二轮",
            "Daniel Wong",
            [("Kenji Sato", 33100), ("Sophie Lee", 30700), ("Yuki Mori", 21900), ("Haru Ito", 14300)],
            [{"player": "Haru Ito", "points": 1, "type": "误记分", "reason": "对局中少报 1000 点"}],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-07-20 19:15:00",
            "Winter A",
            "高打点桌",
            "Mika Chen",
            [("Emma Davis", 50600), ("Aiko Tan", 23800), ("Sophie Lee", 15100), ("Noah Smith", 10500)],
            [],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-07-27 19:05:00",
            "Winter C",
            "常规赛",
            "Daniel Wong",
            [("Liam Brown", 36400), ("Yuki Mori", 27700), ("Kenji Sato", 22800), ("Aiko Tan", 13100)],
            [],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-08-03 18:50:00",
            "Winter B",
            "含罚则",
            "Mika Chen",
            [("Sophie Lee", 34400), ("Haru Ito", 30600), ("Emma Davis", 20900), ("Liam Brown", 14100)],
            [{"player": "Liam Brown", "points": 2, "type": "违规操作导致重开", "reason": "牌山破坏后按赛季规则扣分"}],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-08-10 19:35:00",
            "Winter A",
            "常规赛",
            "Daniel Wong",
            [("Noah Smith", 31800), ("Kenji Sato", 31200), ("Yuki Mori", 23000), ("Aiko Tan", 14000)],
            [],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-08-17 19:05:00",
            "Winter Feature",
            "当前最近比赛",
            "Mika Chen",
            [("Yuki Mori", 37500), ("Sophie Lee", 26200), ("Aiko Tan", 22300), ("Emma Davis", 14000)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-21 15:18:00",
            "S11 手打",
            "S11 demo 01",
            "Wang.C",
            [("Rua", 35000), ("Daniel Wong", 34000), ("Kenji Sato", 34000), ("Noah Smith", 17000)],
            [{"player": "Rua", "points": 4, "type": "诈和", "reason": "诈和pt-4"}],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-22 19:00:00",
            "S11 机打",
            "S11 demo 02",
            "Mika Chen",
            [("Sophie Lee", 47200), ("Rua", 30600), ("Aiko Tan", 22600), ("Haru Ito", 19600)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-24 18:40:00",
            "S11 手打",
            "S11 demo 03",
            "Daniel Wong",
            [("Liam Brown", 41800), ("Yuki Mori", 33400), ("Rua", 25300), ("Emma Davis", 19500)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-26 19:20:00",
            "S11 机打",
            "S11 demo 04",
            "Wang.C",
            [("Rua", 50100), ("Noah Smith", 29200), ("Kenji Sato", 21100), ("Aiko Tan", 19600)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-28 19:05:00",
            "S11 手打",
            "S11 demo 05",
            "Mika Chen",
            [("Daniel Wong", 45200), ("Sophie Lee", 32700), ("Rua", 24800), ("Haru Ito", 17300)],
            [{"player": "Haru Ito", "points": 2, "type": "迟到", "reason": "迟到 15 分钟"}],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-30 18:50:00",
            "S11 机打",
            "S11 demo 06",
            "Daniel Wong",
            [("Yuki Mori", 38900), ("Emma Davis", 32500), ("Kenji Sato", 27800), ("Rua", 20800)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-01 19:15:00",
            "S11 手打",
            "S11 demo 07",
            "Wang.C",
            [("Rua", 41300), ("Liam Brown", 33400), ("Sophie Lee", 24700), ("Noah Smith", 20600)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-03 19:30:00",
            "S11 机打",
            "S11 demo 08",
            "Mika Chen",
            [("Aiko Tan", 36000), ("Rua", 35500), ("Daniel Wong", 27500), ("Yuki Mori", 21000)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-05 18:35:00",
            "S11 手打",
            "S11 demo 09",
            "Daniel Wong",
            [("Kenji Sato", 44800), ("Emma Davis", 31500), ("Rua", 23700), ("Liam Brown", 20000)],
            [{"player": "Rua", "points": 1, "type": "误记分", "reason": "复核后补扣 1pt"}],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-07 19:10:00",
            "S11 机打",
            "S11 demo 10",
            "Wang.C",
            [("Rua", 39800), ("Haru Ito", 34900), ("Noah Smith", 25000), ("Sophie Lee", 20300)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-09 18:45:00",
            "S11 手打",
            "S11 demo 11",
            "Mika Chen",
            [("Daniel Wong", 42100), ("Rua", 31800), ("Aiko Tan", 27200), ("Emma Davis", 18900)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-11 19:25:00",
            "S11 机打",
            "S11 demo 12",
            "Daniel Wong",
            [("Yuki Mori", 44200), ("Kenji Sato", 32600), ("Noah Smith", 23800), ("Rua", 19400)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-13 19:00:00",
            "S11 手打",
            "S11 demo 13",
            "Wang.C",
            [("Rua", 45800), ("Liam Brown", 30400), ("Haru Ito", 23800), ("Aiko Tan", 20000)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-15 18:55:00",
            "S11 机打",
            "S11 demo 14",
            "Mika Chen",
            [("Sophie Lee", 40600), ("Emma Davis", 35600), ("Rua", 24400), ("Kenji Sato", 19400)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-17 19:40:00",
            "S11 手打",
            "S11 demo 15",
            "Daniel Wong",
            [("Rua", 37000), ("Daniel Wong", 34400), ("Noah Smith", 28700), ("Yuki Mori", 19900)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-19 18:30:00",
            "S11 机打",
            "S11 demo 16",
            "Wang.C",
            [("Aiko Tan", 39300), ("Rua", 33100), ("Liam Brown", 26500), ("Haru Ito", 21100)],
            [{"player": "Liam Brown", "points": 2, "type": "违规操作", "reason": "错摸后按规则扣 2pt"}],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-21 19:05:00",
            "S11 手打",
            "S11 demo 17",
            "Mika Chen",
            [("Rua", 42100), ("Kenji Sato", 33300), ("Emma Davis", 24600), ("Sophie Lee", 20000)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-23 19:15:00",
            "S11 机打",
            "S11 demo 18",
            "Daniel Wong",
            [("Noah Smith", 38600), ("Daniel Wong", 34200), ("Rua", 28300), ("Aiko Tan", 18900)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-25 18:50:00",
            "S11 手打",
            "S11 demo 19",
            "Wang.C",
            [("Rua", 48600), ("Yuki Mori", 29600), ("Haru Ito", 22400), ("Liam Brown", 19400)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-27 19:30:00",
            "S11 机打",
            "S11 demo 20",
            "Mika Chen",
            [("Sophie Lee", 37200), ("Rua", 34900), ("Kenji Sato", 26700), ("Emma Davis", 21200)],
            [],
        ),
    ]

    for season_id, rules, played_at, table_name, memo, referee, entries, penalties in demo_matches:
        seed_match(db, season_id, rules, played_at, table_name, memo, user_ids[referee], user_ids, entries, penalties)


def seed_match(
    db: sqlite3.Connection,
    season_id: int,
    rules: dict,
    played_at: str,
    table_name: str,
    memo: str,
    referee_id: int,
    user_ids: dict[str, int],
    entries: list[tuple[str, int]],
    penalties: list[dict],
) -> None:
    scores = [score for _, score in entries]
    penalty_values_by_player = {item["player"]: item["points"] for item in penalties}
    penalty_values = [penalty_values_by_player.get(player, 0) for player, _ in entries]
    placements = calculate_placements(scores)
    rank_points = calculate_rank_points(scores, placements, rules, penalty_values)
    match_id = db.execute(
        "insert into matches (season_id, referee_id, played_at, table_name, memo, created_at) values (?, ?, ?, ?, ?, ?)",
        (season_id, referee_id, played_at, table_name, memo, played_at),
    ).lastrowid
    for idx, (player, score) in enumerate(entries):
        db.execute(
            """
            insert into match_entries (match_id, user_id, final_score, placement, rank_points, penalty_points)
            values (?, ?, ?, ?, ?, ?)
            """,
            (match_id, user_ids[player], score, placements[idx], rank_points[idx], penalty_values[idx]),
        )
    for item in penalties:
        db.execute(
            """
            insert into penalties (match_id, season_id, user_id, penalty_type, points, reason, created_by, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                match_id,
                season_id,
                user_ids[item["player"]],
                item["type"],
                item["points"],
                item["reason"],
                referee_id,
                played_at,
            ),
        )


app = create_app()
