"""预设头像集合与自定义上传头像逻辑。为空表示使用姓名首字母。"""

from __future__ import annotations

from pathlib import Path

from brml.config import DATABASE


AVATARS: list[tuple[str, str, str]] = [
    ("dragon", "🀄", "#c0392b"),
    ("cat", "🐱", "#e67e22"),
    ("fox", "🦊", "#d35400"),
    ("panda", "🐼", "#2c3e50"),
    ("tiger", "🐯", "#e67e22"),
    ("rabbit", "🐰", "#e91e63"),
    ("penguin", "🐧", "#1f4e79"),
    ("frog", "🐸", "#1e8449"),
    ("koala", "🐨", "#6c5ce7"),
    ("paw", "🐾", "#8e44ad"),
    ("flower", "🌸", "#c2185b"),
    ("star", "⭐", "#b7950b"),
]

_BY_KEY = {key: (key, emoji, bg) for key, emoji, bg in AVATARS}


def avatar_dir() -> Path:
    """头像文件存放目录：与数据库同级（Render 上位于持久化磁盘 /var/data）。"""
    directory = DATABASE.parent / "avatars"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def is_valid_avatar_key(key: str) -> bool:
    """校验是否为合法的预设头像键。"""
    return key in _BY_KEY


def save_uploaded_avatar(user_id: int, uploaded) -> str:
    """压缩并保存上传头像，返回 ``ok`` / ``missing`` / ``type_invalid`` / ``invalid``。"""
    from PIL import Image

    if not uploaded or not uploaded.filename:
        return "missing"
    ext = uploaded.filename.rsplit(".", 1)[-1].lower() if "." in uploaded.filename else ""
    if ext not in {"jpg", "jpeg", "png", "webp", "gif"}:
        return "type_invalid"
    try:
        image = Image.open(uploaded.stream)
        image.thumbnail((512, 512))
        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        out = avatar_dir() / f"{user_id}.jpg"
        quality = 88
        image.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
        while out.stat().st_size > 1024 * 1024 and quality > 40:
            quality -= 12
            image.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    except Exception:
        return "invalid"
    from brml.db import execute

    execute(
        "update users set avatar = 'upload', avatar_upload = ? where id = ?",
        (f"{user_id}.jpg", user_id),
    )
    return "ok"


def avatar_meta(item: dict | None) -> dict | None:
    """根据用户行返回渲染所需信息：``preset`` / ``upload`` / ``initial``。"""
    if not item:
        return {"kind": "initial", "letter": "?"}
    item = dict(item)  # 兼容 sqlite3.Row
    avatar = item.get("avatar") or ""
    if avatar == "upload" and item.get("avatar_upload"):
        return {"kind": "upload", "src": item["avatar_upload"]}
    found = _BY_KEY.get(avatar)
    if found:
        _, emoji, bg = found
        return {"kind": "preset", "emoji": emoji, "bg": bg}
    return {"kind": "initial", "letter": (item.get("display_name") or "?")[:1]}
