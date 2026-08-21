# Brisbane Riichi Mahjong Portal

一个面向布里斯班立直麻将社群的 Flask MVP，覆盖第一阶段核心流程：

- 注册 / 登录 / 邀请码
- 超级管理员、裁判、普通用户权限
- 赛季规则管理与复制
- 比赛录入、强校验、顺位和同分马点自动计算
- 罚则记录并计入结果
- 排行榜、玩家个人页
- 赛季 CSV 导出

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app init-db
flask --app app run --debug
```

默认会创建 SQLite 数据库 `instance/mahjong.db`，并初始化：

- 超级管理员：`admin@example.com` / `admin1234`
- 裁判邀请码：`REF-2026`
- 普通用户邀请码：`PLAY-2026`
- 两个 demo 赛季、一批裁判/玩家、跨赛季比赛和罚则记录

完整演示数据账号与比赛清单见 [DEMO_DATA.md](DEMO_DATA.md)。

## 部署提示

当前版本默认使用 SQLite，适合本地开发和 Render 原型部署。之后迁移 MySQL 时，可将 `db.py` 风格的数据访问替换为 MySQL 连接层，路由与模板可继续沿用。
