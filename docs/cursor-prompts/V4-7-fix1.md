# V4-7-fix1 修订提示词：test_set_hr.py 两个 e2e 用例缺 fuse_workout 调用

> 你是本仓库的资深后端工程师。本提示词是唯一任务来源：只按本提示词写代码，**不跑任何验收命令（pytest 一律不跑）**，**不执行任何 git 命令**。
> 红线：禁整文件重写（外科式最小修改）；所有写出的文件必须无 BOM；不得修改 `.env` 系列文件；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 审核发现的问题（审核方亲手跑 pytest 实测，唯一问题）

`backend/tests/test_set_hr.py` 两个用例失败，同一根因——**构造了训记与佳明活动却从未调用
`fuse_workout` 建立 Workout 行**，随后按外键对查询 Workout 得到 None：

```
FAILED tests/test_set_hr.py::test_compute_workout_set_hr_end_to_end_idempotent
FAILED tests/test_set_hr.py::test_compute_workout_set_hr_no_exercise_sets_returns_empty_no_row
# 均死于：assert workout is not None（workout 查询结果为 None）
```

服务层实现本身无缺陷：同文件的 `test_compute_workout_set_hr_xunji_only_no_garmin_returns_empty`
（第 425-430 行）与 5 个 API 用例都正确使用了 `fuse_workout` 并全部通过；执行器自己的
冒烟脚本也是显式 fuse 后才成功。

## 文件预算（共 1 个，不得越界）

1. 改 `backend/tests/test_set_hr.py`（仅两处，外科式）

## 修订内容（两处改法完全一致）

### 1. `test_compute_workout_set_hr_end_to_end_idempotent`（约第 351-362 行）

把：

```python
    from app.models import Workout
    workout = session.query(Workout).filter_by(
        xunji_train_id=train.id, garmin_activity_id=activity.id
    ).first()
    assert workout is not None
```

改为：

```python
    workout = fuse_workout(session, DAY, xunji=train, garmin=activity,
                           match_status="auto_matched")
```

（`fuse_workout` 已在该文件顶部导入，与第 428 行用法一致；后续 `s2.get(Workout, workout.id)`
处的 `from app.models import Workout` 需保留——若因本次改动导致 Workout 仅在那一处使用，
请确保该处仍有局部导入或改用文件级导入，不得产生 NameError。）

### 2. `test_compute_workout_set_hr_no_exercise_sets_returns_empty_no_row`（约第 403-417 行）

同样把查询替换为：

```python
    workout = fuse_workout(session, DAY, xunji=train, garmin=activity,
                           match_status="auto_matched")
```

（该用例后续的 `WorkoutSetHr` 引用保留；若 `Workout` 的局部 import 因此变成未使用，可一并
清理该 import 行，但不得动其他行。）

## 不许动的东西

- 服务层 `app/services/set_hr.py`、API、迁移、模型——全部不许动（审核已确认实现正确）。
- 其余 18 个通过的用例一律不许动。

## 自报告要求

1. 两处改动的最终代码片段；Workout import 处理方式说明。
2. 确认：未跑 pytest、未执行 git、文件无 BOM、未碰 .env、未动预算外文件。
