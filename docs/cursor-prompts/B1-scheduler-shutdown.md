# B1 切片修复提示词：FastAPI lifespan 关闭 APScheduler

> 你是本仓库的资深后端工程师（FastAPI + APScheduler）。本提示词是唯一任务来源：**只修一个具体 bug**，不跑任何验收命令（pytest 一律不跑），不执行任何 git 命令。
> 红线：禁整文件重写（外科式最小修改）；不得修改 `.env` / `.env.*` / `.env.example` / `.env.production.example`；不得删除任何既有文件；不得改动本提示词文件预算之外的任何文件。

## 必读上下文

修复前请先阅读：
- `PRD.md` §7（非功能需求：scheduler 与 FastAPI 生命周期协调）
- `docs/TECH_DEBT.md` §4.2 Sprint 2 MVP 评审（US-1 AC1 定时拉取实现位置）
- `backend/app/main.py` 全文（59 行）

## 问题描述（已读源码核实，可直接采信）

`backend/app/main.py:27-37` 的 FastAPI lifespan 启动了 `BackgroundScheduler`，但 `yield` 后**没有任何 `scheduler.shutdown()` 调用**：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    from app.config import validate_production_settings
    validate_production_settings()
    if os.getenv("SCHEDULER_ENABLED", "1") == "1":
        from app.scheduler import create_scheduler
        _scheduler = create_scheduler()
        _scheduler.start()
    yield
    # ← 缺少 finally + _scheduler.shutdown(wait=False)
```

### 实际后果

- APScheduler `BackgroundScheduler` 启动后线程常驻
- 进程 reload（uvicorn `--reload` / Docker 滚动 / K8s 滚动重启）时：
  - 旧 worker 进程的 scheduler 没显式停 → 关闭期间可能还在触发任务
  - 新 worker 启动时再 `add_job` 同 ID → APScheduler `ConflictingIdError`
- 正常 SIGTERM 下进程退出时 APScheduler 会自己清理，但**仍属于资源泄漏**

### 已核实的相关事实

- `_scheduler` 是模块级全局变量（`main.py:24`），lifespan 内赋值
- 当前 `lifespan` 函数没有 try/finally 结构（裸 `yield`）
- `_scheduler` 类型：`apscheduler.schedulers.background.BackgroundScheduler`
- APScheduler 官方推荐做法是 lifespan exit 时 `scheduler.shutdown(wait=False)`
  （`wait=False` 让正在跑的任务不阻塞 shutdown，常用于 web 服务）

## 修复方案（仅此一个）

把 `yield` 包在 `try` 里，`finally` 里检查 `_scheduler is not None` 后调用 `shutdown(wait=False)`：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    from app.config import validate_production_settings
    validate_production_settings()
    scheduler = None
    if os.getenv("SCHEDULER_ENABLED", "1") == "1":
        from app.scheduler import create_scheduler
        scheduler = create_scheduler()
        scheduler.start()
        _scheduler = scheduler
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
```

### 修复要点

1. **使用本地变量 `scheduler`** 而不是直接 `_scheduler.shutdown()`——避免 finally 内访问模块级全局的边角场景（如 lifespan 未启动成功就抛异常），更明确
2. **`_scheduler = scheduler` 仍保留**——其他模块可能需要通过模块级变量访问（如 debug 场景）
3. **`wait=False`**——不等正在跑的任务完成，符合 web 服务惯例
4. **不调用 `_scheduler` 在 finally**——避免测试场景下 `SCHEDULER_ENABLED=0` 时全局变量被覆盖为 None 时出错

## 文件预算（共 1 个，不得越界）

改 1：
1. `backend/app/main.py`（仅 lifespan 函数体，约 +6/-2 行）

测试 0：
- 本 bug 修复**不需要新增测试**（lifespan shutdown 是 APScheduler 自带机制，单测 mock 困难；CI 已通过现有 `test_scheduler.py` 验证 job 注册）

不要修改：
- ❌ `backend/app/scheduler.py`（保持原样）
- ❌ 任何 alembic 迁移
- ❌ 任何 test 文件
- ❌ 任何 .env 系列
- ❌ `frontend/` 下任何文件

## 自报告要求（交付时必须给出）

1. **改动文件清单**：`backend/app/main.py`（注明行号 +diff 摘要）
2. **设计取舍**：如有任何偏离本提示词之处（如换 wait=True、改用 signal 处理、改模块级变量等），必须显式列出并说明理由
3. **确认清单**：
   - 未跑 pytest
   - 未执行 git 命令
   - 未修改 .env 系列
   - 文件无 BOM
   - 未越界修改其他文件
4. **语法自检**：交付前用 `python -c "import ast; ast.parse(open('backend/app/main.py').read())"` 验证 Python 语法（**只验证，不跑 uvicorn**）