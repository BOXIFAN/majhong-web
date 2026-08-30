-- 警告：此文件供 `flask init-db` 创建全新数据库，会先删除全部业务表。
-- 线上旧数据库的兼容升级由 app.py 中幂等的 ensure_* 函数负责。
-- 日期时间统一保存为 `YYYY-MM-DD HH:MM:SS` 文本；应用连接会启用 SQLite 外键约束。

-- 删除顺序与外键依赖相反，便于未来启用 PRAGMA foreign_keys 后仍可重建。
drop table if exists penalties;
drop table if exists match_entries;
drop table if exists matches;
drop table if exists meetup_signups;
drop table if exists meetups;
drop table if exists announcements;
drop table if exists transactions;
drop table if exists app_migrations;
drop table if exists rule_versions;
drop table if exists seasons;
drop table if exists invite_codes;
drop table if exists users;

-- 身份、登录与一次性迁移记录
create table users (
  id integer primary key autoincrement,
  display_name text not null,
  email text not null unique,
  password_hash text not null,
  role text not null check (role in ('super_admin', 'referee', 'user')),
  created_at text not null,
  is_deleted integer not null default 0,
  deleted_at text
);

-- 社群内容与活动报名
create table announcements (
  id integer primary key autoincrement,
  title text not null,
  content text not null,
  author_id integer not null,
  created_at text not null,
  updated_at text not null,
  foreign key (author_id) references users(id)
);

-- 俱乐部记账：收入与支出。金额以元存储（real），软删除用于防误删与审计。
create table transactions (
  id integer primary key autoincrement,
  kind text not null check (kind in ('income', 'expense')),
  category text not null,
  description text not null,
  amount real not null check (amount > 0),
  user_id integer,
  recorded_by integer not null,
  occurred_at text not null,
  recorded_at text not null,
  deleted_at text,
  foreign key (user_id) references users(id),
  foreign key (recorded_by) references users(id)
);

create table meetups (
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
);

create table meetup_signups (
  id integer primary key autoincrement,
  meetup_id integer not null,
  user_id integer not null,
  created_at text not null,
  unique (meetup_id, user_id),
  foreign key (meetup_id) references meetups(id),
  foreign key (user_id) references users(id)
);

create table app_migrations (
  name text primary key,
  applied_at text not null
);

-- 邀请码通过 used_by/used_at 保留使用审计，不会在使用后删除。
create table invite_codes (
  id integer primary key autoincrement,
  code text not null unique,
  role text not null check (role in ('referee', 'user')),
  created_by integer,
  used_by integer,
  created_at text not null,
  used_at text,
  foreign key (created_by) references users(id),
  foreign key (used_by) references users(id)
);

-- 赛季规则以 JSON 快照保存；rule_versions 记录每次管理端保存后的版本链。
create table seasons (
  id integer primary key autoincrement,
  name text not null,
  status text not null check (status in ('draft', 'active', 'archived')),
  start_date text not null,
  rules_json text not null,
  version integer not null default 1,
  created_at text not null,
  updated_at text not null
);

create table rule_versions (
  id integer primary key autoincrement,
  season_id integer not null,
  rules_json text not null,
  changed_by integer not null,
  changed_at text not null,
  foreign key (season_id) references seasons(id),
  foreign key (changed_by) references users(id)
);

-- 比赛主记录与四位玩家的结算明细。placement 用 real 支持并列时的 1.5/2.5/3.5。
create table matches (
  id integer primary key autoincrement,
  season_id integer not null,
  referee_id integer,
  played_at text not null,
  table_name text,
  memo text,
  created_at text not null,
  foreign key (season_id) references seasons(id),
  foreign key (referee_id) references users(id)
);

create table match_entries (
  id integer primary key autoincrement,
  match_id integer not null,
  user_id integer not null,
  final_score integer not null,
  placement real not null,
  rank_points real not null,
  penalty_points integer not null default 0,
  foreign key (match_id) references matches(id),
  foreign key (user_id) references users(id)
);

-- 罚则独立存档便于审计，同时 penalty_points 会写入 match_entries 并计入 rank_points。
create table penalties (
  id integer primary key autoincrement,
  match_id integer not null,
  season_id integer not null,
  user_id integer not null,
  penalty_type text not null,
  points integer not null,
  reason text not null,
  created_by integer not null,
  created_at text not null,
  foreign key (match_id) references matches(id),
  foreign key (season_id) references seasons(id),
  foreign key (user_id) references users(id),
  foreign key (created_by) references users(id)
);
