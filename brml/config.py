"""应用路径、环境开关和部署相关默认值。"""

from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

# DATABASE_PATH 允许托管环境把 SQLite 文件放到持久化磁盘；本地默认使用 instance/。
DATABASE = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "instance" / "mahjong.db"))
SEED_DEMO_DATA = os.environ.get("SEED_DEMO_DATA", "false").lower() in {"1", "true", "yes", "on"}

# 这两个常量对应一次性数据迁移。更换默认管理员密码时必须同时更换迁移名称，
# 否则已执行过旧迁移的数据库不会再次更新。
ADMIN_PASSWORD_HASH = "pbkdf2:sha256:600000$OE6JuNaR26tucuw6$c7c3987d9ac3d9e86f2fab2c689c8b49dab963e674f571e8d32d78bf5aaf8c80"
ADMIN_PASSWORD_MIGRATION = "set-admin-password-2026-08-24"

DEFAULT_MEETUP_VENUE = "upc 8 Gillingham street, QLD4102"

# 网站版本，用于首页显示；改版时同步更新即可。
SITE_VERSION = "v1.1"
