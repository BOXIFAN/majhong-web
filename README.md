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

默认会创建 SQLite 数据库 `instance/mahjong.db`。也可以通过 `DATABASE_PATH` 指定数据库文件：

```bash
DATABASE_PATH=/tmp/mahjong.db flask --app app run --debug
```

数据库首次创建时会初始化：

- 超级管理员账号：`admin@example.com`（密码不在公开文档中保存）

默认不会初始化赛季、玩家、裁判或邀请码。请使用超级管理员登录后创建赛季与邀请码。

默认不会导入 demo 数据。如果需要本地演示数据，可在初始化前设置：

```bash
SEED_DEMO_DATA=true flask --app app init-db
```

demo 数据会额外初始化：

- 裁判用户：`wangc@example.com` / `demo1234`
- 三个 demo 赛季、一批裁判/玩家、跨赛季比赛和罚则记录，其中 S11 赛季包含 20 场比赛记录

完整演示数据账号与比赛清单见 [DEMO_DATA.md](DEMO_DATA.md)。

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
