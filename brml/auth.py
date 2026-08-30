"""账号相关随机凭据与路由访问控制。"""

from __future__ import annotations

import functools
import secrets
import string

from flask import flash, g, redirect, url_for

from brml.db import query_one
from brml.i18n import translate

def generate_temporary_password(length: int = 12) -> str:
    """生成避开易混淆字符的临时密码。"""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_invite_code(role: str) -> str:
    """生成带角色前缀的邀请码，并在数据库中确保唯一。"""
    prefix = "REF" if role == "referee" else "PLAY"
    alphabet = string.ascii_uppercase + string.digits
    while True:
        token = "".join(secrets.choice(alphabet) for _ in range(6))
        code = f"{prefix}-{token[:3]}-{token[3:]}"
        if not query_one("select id from invite_codes where code = ?", (code,)):
            return code


def login_required(view):
    """要求会话中存在未删除用户。"""
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash(translate("flash.login_required"), "error")
            return redirect(url_for("login"))
        return view(**kwargs)
    return wrapped_view


def role_required(*roles: str):
    """限制路由角色；未登录和权限不足使用不同提示。"""
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


