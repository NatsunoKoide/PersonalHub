# 0012 测试必须真正隔离数据家（复盘误删真实库事故）

日期：2026-10-24
状态：已采纳（v1.5.1 修复）

## 事故

`tests/test_api.py::test_moving_data_home_keeps_writing_to_the_new_place` 为了测
「搬家顺序」分支，刻意 `delenv("PERSONALHUB_HOME")` 以走「指针 / 默认位置」解析路径，
却**只把 `LOCALAPPDATA` 重定向到临时目录**。但 `default_data_home()` 读的是
**`APPDATA` 不是 `LOCALAPPDATA`**——于是 `data_home()` 在测试里落回了用户真实的
`%APPDATA%\PersonalHub`，`move_data_home` 的 `old_db.unlink()` 就把**真的数据库
删了**（Python 的 `unlink` 不走回收站，不可恢复）。

每台开发机/CI 每跑一次全量 pytest，这个测试就删一次真实用户数据。证据：`Temp\
pytest-of-*\test_moving_data_home_*0\new-home\data.db` 每轮一个；用户原本录入的
任务/习惯/记账/饮食/身体记录全部随被删的真库永久丢失，仅 10-23 备份里残留一条
孤立 task「写测试」（且那个备份只有 migration 1，缺后续表，无法作为恢复点）。

## 根因

测试作者误以为「重定向 LOCALAPPDATA = 重定向数据家」，没核对 `paths.data_home`
的解析顺序（环境变量 `PERSONALHUB_HOME` → 指针 `LOCALAPPDATA` 下的 location.json →
默认 `APPDATA`）。autouse 夹具 `isolate_data_home` 虽设了 `PERSONALHUB_HOME=tmp`，
但本测试主动 `delenv` 把它摘掉，等于自己撤掉了隔离保护，又没有补上 `APPDATA` 的
重定向。

## 决策

1. **修复测试**：同时把 `APPDATA` 也重定向到临时目录并 `mkdir`，让默认位置也落在
   临时区；并在测试末尾加守卫断言——真实数据家 `Roaming\PersonalHub\data.db` 的
   `mtime` 前后必须一致，否则测试直接红。已验证：单独跑该测试，真实库 mtime 不变。
2. **硬规则（写入 GLOSSARY/本项目记忆）**：任何测试若要测「无 PERSONALHUB_HOME」的
   解析分支，**必须同时重定向 APPDATA**（默认位置真正落在哪），不能只动
   LOCALAPPDATA；更稳妥的是全程保留 `PERSONALHUB_HOME=tmp` 不摘掉。
3. **回归守护**：该测试现在既测搬家顺序，也测「绝不碰真实数据家」，双重保险。

## 影响

- 文件：tests/test_api.py（修复 + 守卫）、.workbuddy/memory（事故复盘）、
  GLOSSARY（数据家解析顺序术语）。
- 教训泛化：凡涉及路径重定向的测试，边界要以「被重定向的变量真的影响了目标解析」
  为准，不能想当然。
