# Demo Data Reference

运行 `flask --app app init-db` 会重建 `instance/mahjong.db`，并写入以下演示数据。

## 登录账号

所有 demo 用户密码均为 `demo1234`。

| 角色 | 名称 | 邮箱 | 密码 |
| --- | --- | --- | --- |
| 超级管理员 | Admin | admin@example.com | admin1234 |
| 裁判 | Mika Chen | mika@example.com | demo1234 |
| 裁判 | Daniel Wong | daniel@example.com | demo1234 |
| 裁判 | Wang.C | wangc@example.com | demo1234 |
| 普通用户 | Rua | 3474189100@qq.com | demo1234 |
| 普通用户 | Aiko Tan | aiko@example.com | demo1234 |
| 普通用户 | Kenji Sato | kenji@example.com | demo1234 |
| 普通用户 | Liam Brown | liam@example.com | demo1234 |
| 普通用户 | Sophie Lee | sophie@example.com | demo1234 |
| 普通用户 | Noah Smith | noah@example.com | demo1234 |
| 普通用户 | Yuki Mori | yuki@example.com | demo1234 |
| 普通用户 | Emma Davis | emma@example.com | demo1234 |
| 普通用户 | Haru Ito | haru@example.com | demo1234 |

## 邀请码

| 邀请码 | 角色 |
| --- | --- |
| REF-2026 | 裁判 |
| PLAY-2026 | 普通用户 |

## 赛季

| 赛季 | 状态 | 开始日期 | 说明 |
| --- | --- | --- | --- |
| Brisbane Riichi 2026 Autumn | archived | 2026-04-01 | 使用默认规则 |
| Brisbane Riichi 2026 Winter | archived | 2026-07-01 | 4 赤、开启西入，顺位马点调整为 20 / 5 / -15 / -30 |
| S11 | active | 2026-08-21 | 30000 起始分、30000 原点，4 赤，顺位马点 20 / 5 / -15 / -30，包含 20 场 demo |

## 比赛结果

### Brisbane Riichi 2026 Autumn

| 日期 | 牌桌 | 玩家与点数 | 罚则 |
| --- | --- | --- | --- |
| 2026-04-05 | Autumn A | Aiko 38200, Kenji 26700, Liam 20400, Sophie 14700 | 无 |
| 2026-04-12 | Autumn B | Noah 31000, Yuki 31000, Emma 23000, Haru 15000 | 无 |
| 2026-04-19 | Autumn A | Sophie 41100, Aiko 28600, Haru 17200, Kenji 13100 | Kenji -2：终局报分错误 |
| 2026-05-03 | Autumn C | Liam 33500, Emma 29200, Yuki 22100, Noah 15200 | 无 |
| 2026-05-17 | Autumn B | Haru 36000, Aiko 28400, Noah 21600, Sophie 14000 | 无 |
| 2026-06-07 | Autumn Final | Emma 39000, Liam 25000, Kenji 23000, Yuki 13000 | Yuki -1：迟到 |

### Brisbane Riichi 2026 Winter

| 日期 | 牌桌 | 玩家与点数 | 罚则 |
| --- | --- | --- | --- |
| 2026-07-06 | Winter A | Aiko 45200, Noah 25100, Emma 18800, Liam 10900 | 无 |
| 2026-07-13 | Winter B | Kenji 33100, Sophie 30700, Yuki 21900, Haru 14300 | Haru -1：误记分 |
| 2026-07-20 | Winter A | Emma 50600, Aiko 23800, Sophie 15100, Noah 10500 | 无 |
| 2026-07-27 | Winter C | Liam 36400, Yuki 27700, Kenji 22800, Aiko 13100 | 无 |
| 2026-08-03 | Winter B | Sophie 34400, Haru 30600, Emma 20900, Liam 14100 | Liam -2：违规操作导致重开 |
| 2026-08-10 | Winter A | Noah 31800, Kenji 31200, Yuki 23000, Aiko 14000 | 无 |
| 2026-08-17 | Winter Feature | Yuki 37500, Sophie 26200, Aiko 22300, Emma 14000 | 无 |

### S11

| 日期 | 牌桌 | 玩家与点数 | 罚则 |
| --- | --- | --- | --- |
| 2026-08-21 | S11 手打 | Rua 35000, Daniel 34000, Kenji 34000, Noah 17000 | Rua -4：诈和 |
| 2026-08-22 | S11 机打 | Sophie 47200, Rua 30600, Aiko 22600, Haru 19600 | 无 |
| 2026-08-24 | S11 手打 | Liam 41800, Yuki 33400, Rua 25300, Emma 19500 | 无 |
| 2026-08-26 | S11 机打 | Rua 50100, Noah 29200, Kenji 21100, Aiko 19600 | 无 |
| 2026-08-28 | S11 手打 | Daniel 45200, Sophie 32700, Rua 24800, Haru 17300 | Haru -2：迟到 |
| 2026-08-30 | S11 机打 | Yuki 38900, Emma 32500, Kenji 27800, Rua 20800 | 无 |
| 2026-09-01 | S11 手打 | Rua 41300, Liam 33400, Sophie 24700, Noah 20600 | 无 |
| 2026-09-03 | S11 机打 | Aiko 36000, Rua 35500, Daniel 27500, Yuki 21000 | 无 |
| 2026-09-05 | S11 手打 | Kenji 44800, Emma 31500, Rua 23700, Liam 20000 | Rua -1：误记分 |
| 2026-09-07 | S11 机打 | Rua 39800, Haru 34900, Noah 25000, Sophie 20300 | 无 |
| 2026-09-09 | S11 手打 | Daniel 42100, Rua 31800, Aiko 27200, Emma 18900 | 无 |
| 2026-09-11 | S11 机打 | Yuki 44200, Kenji 32600, Noah 23800, Rua 19400 | 无 |
| 2026-09-13 | S11 手打 | Rua 45800, Liam 30400, Haru 23800, Aiko 20000 | 无 |
| 2026-09-15 | S11 机打 | Sophie 40600, Emma 35600, Rua 24400, Kenji 19400 | 无 |
| 2026-09-17 | S11 手打 | Rua 37000, Daniel 34400, Noah 28700, Yuki 19900 | 无 |
| 2026-09-19 | S11 机打 | Aiko 39300, Rua 33100, Liam 26500, Haru 21100 | Liam -2：违规操作 |
| 2026-09-21 | S11 手打 | Rua 42100, Kenji 33300, Emma 24600, Sophie 20000 | 无 |
| 2026-09-23 | S11 机打 | Noah 38600, Daniel 34200, Rua 28300, Aiko 18900 | 无 |
| 2026-09-25 | S11 手打 | Rua 48600, Yuki 29600, Haru 22400, Liam 19400 | 无 |
| 2026-09-27 | S11 机打 | Sophie 37200, Rua 34900, Kenji 26700, Emma 21200 | 无 |

Autumn / Winter 每场四家点数总和均为 `100000`，S11 每场四家点数总和均为 `120000`，可用于验证比赛录入的强校验逻辑。
