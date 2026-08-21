# Demo Data Reference

运行 `flask --app app init-db` 会重建 `instance/mahjong.db`，并写入以下演示数据。

## 登录账号

所有 demo 用户密码均为 `demo1234`。

| 角色 | 名称 | 邮箱 | 密码 |
| --- | --- | --- | --- |
| 超级管理员 | Admin | admin@example.com | admin1234 |
| 裁判 | Mika Chen | mika@example.com | demo1234 |
| 裁判 | Daniel Wong | daniel@example.com | demo1234 |
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
| Brisbane Riichi 2026 Winter | active | 2026-07-01 | 4 赤、开启西入，顺位马点调整为 20 / 5 / -15 / -30 |

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

每场四家点数总和均为 `100000`，可用于验证比赛录入的强校验逻辑。
