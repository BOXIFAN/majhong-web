drop table if exists penalties;
drop table if exists match_entries;
drop table if exists matches;
drop table if exists meetup_signups;
drop table if exists meetups;
drop table if exists announcements;
drop table if exists app_migrations;
drop table if exists rule_versions;
drop table if exists seasons;
drop table if exists invite_codes;
drop table if exists users;

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

create table announcements (
  id integer primary key autoincrement,
  title text not null,
  content text not null,
  author_id integer not null,
  created_at text not null,
  updated_at text not null,
  foreign key (author_id) references users(id)
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
