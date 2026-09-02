# V4-3-fix1 修订提示词：修 test_alembic.py 相对回退被新链头顶破

> 你是本仓库的资深后端工程师。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest/alembic 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写；文件必须无 BOM；不得修改 `.env*`；不得删除任何既有文件；只改本提示词指定文件。

## 问题（审核方亲手跑 pytest 实测：1 failed / 859 passed / 6 skipped，覆盖率 93.26% 达标）

唯一失败：`backend/tests/test_alembic.py::test_workout_soft_delete_columns_roundtrip`

```
command.downgrade(cfg, "-1")   # 第 62 行
assert "deleted_at" not in {c["name"] for c in insp.get_columns("workout")}   # 失败
```

## 根因（已定位，实读确认）

该测试用**相对回退** `downgrade(cfg, "-1")`：写测试时链头是 `f5a6b7c8d9e0`（软删除迁移），
-1 恰好回滚它。V4-3 新增迁移 `a6b7c8d9e0f1` 成为新链头后，-1 只回滚 V4-3，
软删除列还在 → 断言失败。**业务代码与迁移文件均无问题，纯测试维护性修复。**
同文件其他往返测试（82 行、114 行）早已用显式 revision 回退，风格对齐即可。

## 修订内容（文件预算：仅改 backend/tests/test_alembic.py，共 1 个文件）

1. 第 62 行 `command.downgrade(cfg, "-1")` 改为 `command.downgrade(cfg, "e4f5a6b7c8d9")`
   （即显式回退到软删除迁移之前的版本，语义与未来新链头解耦），
   注释说明「回退到 f5a6b7c8d9e0 之前」。
2. 第 10-24 行 `EXPECTED_TABLES` 集合加入 `"skinfold_record"`（保持按字母序插入）。
3. 文件末尾追加一个新往返测试 `test_skinfold_and_settings_profile_roundtrip`：
   - upgrade head 后断言：`skinfold_record` 表存在；`settings` 表列含 `gender` 与 `birth_date`；
     `skinfold_record` 列含 {id, date, method, sites_json, density, bodyfat_result, note, created_at, updated_at}；
   - `command.downgrade(cfg, "f5a6b7c8d9e0")` 后断言：`skinfold_record` 表不存在，
     settings 列不含 gender/birth_date；
   - 再 `command.upgrade(cfg, "head")` 断言表与列恢复。
   写法风格完全对齐同文件既有往返测试。

不改其他任何文件。

## 交付纪律

完成后输出简短交付报告：改动行号与内容、确认未触碰其他文件、红线确认（无 BOM/未跑 pytest/未跑 git）。
