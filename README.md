# Brisbane Riichi Mahjong Portal

一个面向布里斯班立直麻将社群的 Flask MVP，覆盖第一阶段核心流程：

- 注册 / 登录 / 邀请码
- 超级管理员、裁判、普通用户权限
- 赛季规则管理与复制
- 比赛录入、强校验、顺位和同分马点自动计算
- 罚则记录并计入结果
- 排行榜、玩家个人页
- 留言板：分享近期和到的大牌，支持点赞、评论与发布者编辑
- 赛季 CSV 导出

## 留言板

留言板是左侧边栏的独立页面（`/board`），用于让用户上传自己近期和到的大牌，
其他用户可以点赞与评论。规则与实现要点：

- 每页显示 10 份留言，多出的留言通过上一页 / 下一页翻页。
- 留言以磨砂卡片呈现：左上角是头像与名称，中间是固定 4:3 图片区域，
  列表页右下角是发布用的加号按钮（`/board/new`）。
- 每人每天（按布里斯班日期）最多发布 2 条；发布者可以随时编辑或删除自己的留言。
- 上传图片会在服务端重新编码为 JPEG（剥离 EXIF/GPS 等元数据）：
  仅接受 JPG / PNG / WebP / GIF，最短边至少 240px；超过 6MB 的原图会自动压缩，
  落盘文件一定小于 6MB（实际压缩上限 2MB），超过 25MB 才会拒绝。
- 图片只保留 30 天，到期后由 `board_service.cleanup_expired_posts()` 连同数据库记录
  一起物理删除；留言板每次访问都会顺带清理，也可以交给定时任务执行：

```bash
flask --app app board-cleanup
```

- **删除即真删除**：作者或超管删除留言时，帖子行、评论、点赞记录与图片文件会
  立刻从数据库和磁盘移除，不做软删除；只有 `board_deletions` 表里保留一条
  不含任何内容的审计记录（编号 / 作者 / 操作者 / 时间），180 天后自动清理。
  管理员删除他人内容会记为 `*_by_admin`，方便社团内部追溯。
- 超管可以进入“留言板管理”（`/admin/board`）集中删除不合规的留言与评论，
  页面顶部会显示图库当前占用与上限。
- 图片存放在数据库同级的 `board_uploads/` 目录；部署时该目录必须与
  `DATABASE_PATH` 一样位于持久化磁盘内，否则重新部署后图片会丢失。

### 磁盘占用控制（Render 1GB Disk）

- 单张图片压缩后最大边 1280px、体积小于 2MB（正常手机照片约 150–400KB）。
- 图库容量上限由 `BOARD_STORAGE_BUDGET_MB` 控制，默认 300MB；达到上限后会拒绝
  新留言而不是把磁盘写满。需要放宽时在 Render 环境变量里调整，例如
  `BOARD_STORAGE_BUDGET_MB=600`。
- 每次打开留言板都会清理过期留言与“没有任何留言引用”的孤儿图片；
  建议再用定时任务每天执行一次下面的命令，脚本会顺带 `VACUUM` 收缩数据库文件：

```bash
flask --app app board-cleanup
```

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app init-db
flask --app app run --debug --port 5050
```

默认会创建 SQLite 数据库 `instance/mahjong.db`。也可以通过 `DATABASE_PATH` 指定数据库文件：

```bash
DATABASE_PATH=/tmp/mahjong.db flask --app app run --debug
```

数据库首次创建时会初始化：

- 超级管理员账号：`admin@example.com`（密码不在公开文档中保存）

默认不会初始化赛季、玩家、裁判或邀请码。请使用超级管理员登录后创建赛季与邀请码。

`flask --app app init-db` 只允许创建不存在的数据库，避免误删现有数据。确需重建本地数据库时，请先备份，再显式运行 `flask --app app init-db --force`；不要在 Render 的持久化数据库上使用 `--force`。

默认不会导入 demo 数据。如果需要本地演示数据，可在初始化前设置：

```bash
SEED_DEMO_DATA=true flask --app app init-db
```

demo 数据会额外初始化：

- 裁判用户：`wangc@example.com` / `demo1234`
- 三个 demo 赛季、一批裁判/玩家、跨赛季比赛和罚则记录，其中 S11 赛季包含 20 场比赛记录

完整演示数据账号与比赛清单见 [DEMO_DATA.md](DEMO_DATA.md)。

## 代码结构与回归

`app.py` 只负责创建 Flask 应用、注册请求钩子和装配各路由模块。主要代码按职责放在 `brml/`：

- `routes/`：社区活动、内容公告、留言板、账号后台、赛季和比赛路由
- `db.py` / `migrations.py`：数据库连接、初始化和旧数据库兼容迁移
- `match_service.py` / `meetup_service.py` / `board_service.py`：会写入数据的业务流程
- `scoring.py` / `analytics.py`：积分计算与只读统计
- `rules.py` / `i18n.py`：赛季规则结构和中英文文案
- `seed.py`：可选演示数据

修改业务逻辑后运行回归测试：

```bash
python -m unittest discover -s tests -v
```

测试覆盖全新数据库、演示数据、公开页面、管理员页面、路由端点名、语言会话、同分顺位、UMA、罚分和决赛资格。重构基线提交为 `8579c53`，此后的职责拆分均为独立提交；需要撤销某阶段时优先使用 `git revert <提交哈希>`，保留完整回溯历史。

## 部署提示

当前版本使用 SQLite。部署到 Render 时必须挂载 Persistent Disk，并将 `DATABASE_PATH` 指向 Disk 内的文件，否则 Render 重启或重新部署后会丢失本地写入的数据。

项目已包含 Render 部署所需文件：

- `requirements.txt`：包含 Flask、Werkzeug、Gunicorn
- `Procfile`：`web: gunicorn app:app`
- `render.yaml`：声明 Python Web Service、1GB Disk、`DATABASE_PATH=/var/data/mahjong.db`，并设置 `SEED_DEMO_DATA=false`
- `.python-version`：指定 Python 3.11.9

应用启动时会检查 `DATABASE_PATH` 指向的数据库是否存在；如果不存在，会自动创建表结构和超级管理员账号。Render 默认不会导入 demo 数据。

## Render 部署教程

### 方式一：使用 Blueprint

1. 确认 GitHub 仓库已经包含最新代码，尤其是 `render.yaml`。
2. 打开 Render Dashboard，选择 `New` → `Blueprint`。
3. 连接 GitHub 仓库 `majhong-web`。
4. Render 会读取 `render.yaml` 并创建 Web Service、Persistent Disk 和环境变量。
5. 确认配置：
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   - Disk Mount Path: `/var/data`
   - `DATABASE_PATH`: `/var/data/mahjong.db`
   - `SEED_DEMO_DATA`: `false`
   - `SECRET_KEY`: 自动生成
6. 创建后等待 Build 和 Deploy 完成。
7. 打开 Render 提供的 `onrender.com` 地址。
8. 首次访问会自动初始化数据库，可使用管理员账号 `admin@example.com` 登录。

### 方式二：手动创建 Web Service

1. Render Dashboard 选择 `New` → `Web Service`。
2. 连接 GitHub 仓库 `majhong-web`。
3. 填写：
   - Runtime: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
4. 选择付费实例类型，因为 Persistent Disk 不能挂载到免费 Web Service。
5. 在 Advanced / Disks 中新增 Disk：
   - Name: `mahjong-data`
   - Mount Path: `/var/data`
   - Size: `1 GB`
6. 添加环境变量：
   - `DATABASE_PATH=/var/data/mahjong.db`
   - `SEED_DEMO_DATA=false`
   - `SECRET_KEY=` 随机长字符串
7. 创建服务并等待部署完成。

### 上线后检查

1. 登录超级管理员账号并立刻修改默认密码。
2. 进入“赛季规则”，确认当前赛季、起始分、原点、决赛场次等配置正确。
3. 录入一场测试比赛，刷新页面后确认排行榜更新。
4. 在 Render Dashboard 手动 Redeploy 一次，确认数据仍保留。若数据保留，说明 Disk 配置正确。

### 注意事项

- Render 的普通文件系统是临时的，只有 `/var/data` 这类 Disk 挂载路径下的数据会保留。
- Persistent Disk 不能在 Build Command 或 Pre-Deploy Command 中访问，所以本项目采用“应用首次启动自动初始化数据库”的方式。
- 使用 Disk 的 Web Service 不能水平扩展到多个实例；SQLite 适合当前社团 MVP。若未来多人高并发录入或需要更强备份恢复，建议迁移到 Render Postgres。
