# 俱乐部记账系统 · 设计与开发时间节点记录

> 目的：在动手开发前先冻结方案、权限边界、数据模型、图表方案与回滚点，
> 避免"灾难性后续"（意外覆盖已有业务、误删数据、样式跑偏、权限越权）。
> 本次只在本地 5050 端口查看，**不推送 GitHub**。

## 0. 结论摘要

- 新增一个面向所有成员的**只读**「财务 / 账本」页面，展示俱乐部当前收入与支出、
  占比扇形图、以及收支公式。
- 新增一个**仅超级管理员可见**的「后台记账」页面：录入收入/支出、关联注册会员、
  查看会员收入统计、编辑与（软）删除记录。
- 非管理员一律只读，不能写入。
- 图表采用纯 CSS `conic-gradient` 扇形图（无 CDN/JS 依赖，离线可用，风格与现网一致）。

## 1. 角色与权限

| 角色 | 财务/账本页 `/finance` | 后台记账 `/admin/finance*` |
| --- | --- | --- |
| 访客（未登录） | 只读 | 不可见 |
| 普通用户 `user` | 只读 | 不可见 |
| 裁判 `referee` | 只读 | 不可见 |
| 超级管理员 `super_admin` | 只读 | 可读写 |

后台路由统一使用现有 `@role_required("super_admin")`，与邀请码、用户管理一致。

## 2. 数据模型：`transactions`（收支记录）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer PK | 自增主键 |
| `kind` | text | `income` / `expense` |
| `category` | text | 分类；收入：会员费/活动费/赞助/其他；支出：场地/奖品/器材/餐饮/其他 |
| `description` | text | 摘要 |
| `amount` | real | 金额（元，保留两位） |
| `user_id` | integer nullable → users.id | 关联的注册会员（仅收入可关联，用于会员收入统计） |
| `recorded_by` | integer → users.id | 录入管理员 |
| `occurred_at` | text | 发生日期 |
| `recorded_at` | text | 录入时间 |
| `deleted_at` | text nullable | 软删除时间；NULL 表示有效 |

说明：
- 金额用 `real` 存储，录入时校验为正数且最多两位小数，展示时统一格式化。
- 采用**软删除**（`deleted_at`），删除可恢复、可审计，避免"灾难性误删"。
- 通过幂等迁移 `ensure_transactions_table()` 兼容已有数据库，无需重建库。

## 3. 统计口径与公式

- 总收入 `income_total` = 所有 `kind='income'` 且未删除的金额之和。
- 总支出 `expense_total` = 所有 `kind='expense'` 且未删除的金额之和。
- 净结余 `net` = 总收入 − 总支出。
- 支出占收入比例 `spend_ratio` = 总支出 / 总收入（总收入为 0 时不计算，显示 `N/A`）。
- 结余率 `net_ratio` = 净结余 / 总收入。
- 分类占比 = 该分类金额 / 该方向总收入（用于扇形图与百分比）。

公式展示（告诉所有人收支关系）：

```
净结余 = 总收入 − 总支出
支出占用率 = 总支出 ÷ 总收入
结余率 = 净结余 ÷ 总收入
```

## 4. 路由清单

| 方法 | 路径 | 权限 | 用途 |
| --- | --- | --- | --- |
| GET | `/finance` | 所有人 | 只读收支总览（汇总/扇形图/公式/流水） |
| GET | `/admin/finance` | 超管 | 管理页（录入表单/流水管理/会员收入统计） |
| POST | `/admin/finance/create` | 超管 | 新建收入/支出 |
| POST | `/admin/finance/<id>/update` | 超管 | 编辑记录 |
| POST | `/admin/finance/<id>/delete` | 超管 | 软删除记录 |

## 5. 前端与图表方案

- 复用 `base.html` 结构、`panel`/`page-head`/`section-head`/`badge`/`table-wrap`/`.form`/
  `.button` 等既有组件与设计 token（`--brand`/`--accent`/`--good`/`--bad`）。
- 扇形图：CSS `conic-gradient` 生成圆环扇形，中心显示净结余，图例列出分类与百分比。
- 配色：收入用 `--good`（绿）系，支出用 `--accent`（橙）/`--bad`（红）系，
  分类内部用一组可区分的深浅色阶。
- 中英文全部走 `brml/i18n.py` 的 `TRANSLATIONS`。

## 6. 开发时间节点

| 节点 | 内容 | 状态 |
| --- | --- | --- |
| **T0** | 架构盘点、方案冻结、本时间节点记录 | ✅ 已完成 |
| **T1** | 数据模型：`schema.sql` + `migrations.py` + 注册迁移 | ✅ 已完成 |
| **T2** | 后端：统计逻辑 `brml/finance.py` + 路由 `brml/routes/finance.py` + app.py 注册 | ✅ 已完成 |
| **T3** | 前端：`finance.html` / `admin_finance.html` / `finance_form.html` + 导航 + 样式 + 文案 | ✅ 已完成 |
| **T4** | 本地 5050 回归验证（权限、增删改、图表、中英文、样式） | ✅ 已完成 |
| **T5** | 提交本地 git，**不推送** GitHub | ⏳（不推送） |

## 9. 交付摘要（T4 后）

- 新增 `transactions` 表（软删除）+ 幂等迁移，不影响既有业务表。
- 新增公开只读页 `/finance`：汇总卡、收入/支出扇形图（CSS conic-gradient）、
  分类百分比图例、三条收支公式、最近流水。
- 新增超管后台 `/admin/finance*`：录入收入/支出（含摘要、日期、金额、关联会员）、
  会员收入统计、编辑与软删除。
- 权限：访客与普通用户只读；`referee`、`user` 访问后台会被拒并重定向；仅超管可写。
- 中英文文案齐备；导航加入“账本 / 财务”与超管“后台记账”。
- 回归测试 12 项全部通过；功能用 Flask test client + 临时库验证。

## 10. Render 持久化确认

记账数据存放在与主业务相同的 SQLite 数据库 `DATABASE_PATH`（Render 上为 `/var/data/mahjong.db`，
由 render.yaml 的 `disk` 挂载到 `/var/data`）。`transactions` 表由启动时的幂等迁移
`ensure_transactions_table()` 自动创建，无需单独迁移命令；因此记账记录会随 Render 持久化盘保存，
重启/重新部署不丢失。其余部署注意点（`SEED_DEMO_DATA=false` 等）沿用 README 既有说明。

## 7. 风险与回滚

- 风险：新增迁移可能影响既有请求 → 迁移保持幂等、只新增表，不改动现有表结构。
- 风险：样式跑偏 → 只追加新的 `finance-*` 类，尽量复用现网 token。
- 风险：误删数据 → 使用软删除；数据库为 `instance/mahjong.db`，改动前无需重建。
- 回滚：每个 T1–T4 完成后做一次本地 git commit，可 `git revert` 到任一节点。

## 8. 不做的事

- 不推送 GitHub。
- 不引入外部 CDN/图表库。
- 不改动现有比赛、赛季、公告、活动等业务表与页面。
- 不做多俱乐部/多账本隔离（当前为单俱乐部）。
