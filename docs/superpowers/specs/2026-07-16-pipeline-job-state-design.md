# fullpcr 一键分析任务互斥与稳定进度设计

## 目标

修复一键分析的三个关联问题：

1. 同一项目的完整分析正在运行时，任何重复点击或同服务器上的其他页面会话都不能再次提交同一项目。
2. Streamlit 因点击控件、切换页面或普通 rerun 重新执行页面脚本时，必须恢复同一个后台任务的真实进度，不能把进度条重置成一次新任务。
3. 外部命令超时时必须终止该命令及其全部子孙进程，不能遗留 MFEprimer 或 obipcr 进程。

任务成功、失败或超时结束后解除互斥，允许用户重新运行。分析算法、参数、五步顺序和结果目录保持不变。

## 已确认根因

- `fullpcr.gui_app._render_quick_analysis()` 只在按钮事件对应的单次脚本运行中创建 `st.progress` 和占位消息；进度没有独立于页面运行周期持久化。
- 一键运行按钮的 `disabled` 条件只包含输入验证和外部依赖状态，没有项目级“运行中”互斥状态。
- `fullpcr.gui_helpers.run_gui_command()` 使用 `subprocess.run(..., timeout=...)`。当 GUI 外层命令与内部工具使用相同超时值时，外层 Python 包装进程可能先被终止，而包装进程启动的 MFEprimer 仍继续运行。

## 方案概述

采用进程内后台线程执行任务，并在项目输出目录中使用原子状态文件和锁文件保存任务事实。Streamlit 页面只负责提交、读取和展示状态；普通 rerun 不负责继续或重启任务。

每个项目最多有一个运行中的任务。项目身份使用规范化后的 `project_output_root`，不得使用页面临时组件或显示名称作为互斥键。

不新增第三方依赖，不引入 Redis、Celery 或数据库。

## 组件边界

### 1. `fullpcr/pipeline_jobs.py`

新增一个只负责完整分析后台任务生命周期的模块，提供以下接口：

```python
def start_pipeline_job(project_root: str, plan: list[dict]) -> dict
def get_pipeline_job(project_root: str) -> dict | None
```

`start_pipeline_job()` 原子占用项目锁。成功时启动一个 daemon 线程并返回当前任务状态；如果同一项目已经有 `RUNNING` 任务，则返回现有状态且 `started=False`，不能启动第二个线程。

线程调用现有 `run_full_pipeline()`，通过 `on_progress` 回调更新状态。任务结束后写入最终 outcome、解除运行锁，但保留状态文件供页面和结果页面恢复。

模块内存注册表用于保存当前服务进程中的线程引用；磁盘锁和状态文件用于跨 Streamlit 会话识别同一项目。所有注册表访问使用 `threading.Lock`。

### 2. 项目状态文件

项目根目录下新增内部目录：

```text
<project_root>/.fullpcr_jobs/
├── pipeline.lock
└── pipeline_state.json
```

状态文件至少包含：

```json
{
  "schema_version": 1,
  "job_id": "uuid",
  "project_root": "/absolute/project/root",
  "status": "RUNNING",
  "current_step": "s3",
  "current_label": "特异性分析",
  "phase": "running",
  "completed_steps": ["s1", "s2"],
  "progress_current": 2,
  "progress_total": 5,
  "outcome": null,
  "started_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "finished_at": null,
  "owner_pid": 12345
}
```

`status` 只允许 `RUNNING`、`PASS`、`FAIL`、`TIMEOUT`。状态文件使用同目录临时文件加 `os.replace()` 原子更新。状态文件和锁文件不得进入结果 ZIP；现有归档逻辑需要排除 `.fullpcr_jobs`。

锁通过排他创建获得。读取到锁时，先检查当前进程内是否存在活跃线程；若锁的 `owner_pid` 已不存在或当前任务线程已经结束，则将其标记为失败并清理陈旧锁，避免服务器异常重启后永久禁用按钮。

### 3. `fullpcr.gui_helpers.run_gui_command()`

将外部命令执行改为显式 `subprocess.Popen(..., start_new_session=True)`，仍保持参数为 `list[str]`、`shell=False`、捕获文本 stdout/stderr。

超时时：

1. 对进程组发送 `SIGTERM`。
2. 等待短暂宽限期。
3. 尚未退出时发送 `SIGKILL`。
4. 回收进程并返回原有 `TIMEOUT` 结构。

这样 GUI 启动的 Python 包装命令及其 MFEprimer/obipcr 后代会作为一个进程组整体结束。

### 4. `fullpcr.gui_app._render_quick_analysis()`

页面每次渲染都根据 `project_output_root` 调用 `get_pipeline_job()`：

- `RUNNING`：按钮文字显示“分析正在运行”，按钮禁用；按持久状态显示进度条和“正在进行：<步骤>”。
- `PASS`、`FAIL`、`TIMEOUT`：显示最终状态和已保存结果；按钮恢复可用。
- 无任务：显示正常的“一键运行完整分析”按钮。

按钮点击时调用 `start_pipeline_job()`，不再在页面脚本中同步运行五步命令。即使两个提交请求几乎同时到达，也只有成功取得锁的请求启动线程；另一个请求显示“该项目的分析已在运行”。

运行状态区域使用固定容器渲染同一个状态记录。rerun 只重新读取记录，不把进度重置为 0，也不生成新的 `job_id`。页面可使用 Streamlit 定时 fragment 轮询状态；如果当前 Streamlit 版本或测试环境不支持自动 fragment，则保持手动 rerun 可恢复状态，但不能影响任务本身。

任务成功后，将 outcome 中的 `wf_s1_result` 至 `wf_s5_result` 和 `full_pipeline_result` 同步回当前会话，保持结果总览与下载功能现有契约。其他会话可从状态文件中的 outcome 恢复这些结果。

## 状态转换

```text
无任务 --提交成功--> RUNNING
RUNNING --所有步骤通过--> PASS
RUNNING --步骤失败--> FAIL
RUNNING --步骤超时--> TIMEOUT
RUNNING --后台未捕获异常--> FAIL
PASS/FAIL/TIMEOUT --用户重新提交--> RUNNING（新 job_id）
RUNNING --重复提交--> RUNNING（拒绝，不创建任务）
```

每个步骤开始时更新 `current_step/current_label/phase`；步骤结束时先保存步骤结果，再更新完成比例。进度语义为“已完成步骤数 / 5”，正在执行第 3 步时进度保持 2/5，并明确显示第 3 步名称，避免将开始执行误画成完成。

## 错误处理

- 无法创建项目内部状态目录或锁文件：不启动后台任务，页面显示具体中文错误。
- 任务线程抛出未预期异常：写入 `FAIL` 状态和安全的错误摘要，释放锁；不得让按钮永久禁用。
- 状态 JSON 损坏：将损坏文件原地改名保留，返回带 `state_error` 的结构化 `FAIL` 状态；本次请求不得启动任务，用户下一次明确点击可以重新提交。
- 进程组超时终止失败：返回 `TIMEOUT`，消息中注明仍需人工检查，并记录 PID/命令；不得把它标记为成功。
- 页面离开、浏览器刷新和 Streamlit rerun：不取消后台线程，不修改 `job_id`，不释放锁。

## 测试与验收

### 纯函数和任务管理测试

- 两个并发 `start_pipeline_job()` 调用只让 runner 执行一次。
- `RUNNING` 状态包含正确步骤、2/5 等进度，普通读取不改变 `job_id`。
- PASS、FAIL、TIMEOUT 都释放锁并保留最终 outcome。
- 结束后重新提交会创建新的 `job_id`。
- 后台异常不会留下永久锁。
- 状态文件原子写入且 `.fullpcr_jobs` 不进入结果 ZIP。

### 进程清理测试

- 启动一个会再启动子进程的测试命令，触发短 timeout；验证父进程和子进程均退出。
- PASS、非零退出码、缺少可执行文件和普通 OSError 保持现有返回契约。
- 命令继续使用 `list[str]` 且 `shell=False`。

### Streamlit AppTest

- 任务为 `RUNNING` 时按钮禁用且文字为“分析正在运行”。
- 连续两次提交只产生一个任务。
- 注入第 3 步运行状态，普通 rerun 后进度和步骤名称保持不变。
- PASS/FAIL/TIMEOUT 后按钮恢复可用，并显示相应结果。
- dry-run 仍只生成计划，不创建锁或后台任务。

### 最终检查

执行相关定向测试、`pytest -q`、`python3 -m compileall -q fullpcr` 和 `git diff --check`。使用真实浏览器验证：点击一键运行后切换 expander、参数控件或页面，再返回时仍显示同一个任务和真实当前步骤；运行中按钮不可重复提交。

## 范围限制

- 不修改五步分析算法、CLI 参数含义、结果文件格式或结果页面信息架构。
- 不引入外部任务队列、数据库或新的第三方依赖。
- 不提交、不推送、不修改 Git 历史。
- 不清理或回退工作区中与本任务无关的既有修改。
