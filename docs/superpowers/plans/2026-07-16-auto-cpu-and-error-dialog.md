# 自动 CPU 配额与完整错误弹窗实施计划

> **执行方式：** 使用 `codex-claude-bridge`，Claude Code 负责实施与运行测试，Codex 只读审查实际 diff、测试结果和仓库状态。不得使用子代理，不得 commit、push、merge 或修改 Git 历史。

**目标：** 网站默认为 MFEprimer 使用当前进程可用逻辑线程的 60%，高级分步工作流允许手动覆盖；一键分析和高级分步运行失败时自动弹出一次完整原始错误，并可手动重新查看。

**架构：** CPU 检测、自动计算、手动覆盖解析和错误详情组装都放在 `gui_helpers.py` 的纯函数中。`gui_app.py` 只负责状态控件、统一 `st.dialog` 渲染与防重复弹窗。`pipeline_jobs.py` 增加后台 traceback 持久化；MFEprimer/obipcr runner 取消500字符错误截断。

**技术栈：** Python 3.10+、Streamlit、pytest、Streamlit AppTest。

## 全局约束

- 只修改本计划列出的源文件和测试文件。
- 不修复或规避 MFEprimer 4.3.1 的 `.primerqc.bin` 和23列 Spec TSV兼容问题。
- 不改变 CLI `--cpu` 的现有语义或默认值。
- 不改变五步顺序、分析算法、结果文件列结构和日志文件位置。
- 不给 obipcr 或其他不支持线程参数的步骤添加 CPU 选项。
- 不新增第三方依赖。
- 不删除或弱化既有测试、断言和错误检查。
- 不提交、不推送、不修改 Git 历史。
- 预先存在且必须保留的工作区文件：
  - `docs/superpowers/specs/2026-07-16-auto-cpu-and-error-dialog-design.md`
  - `docs/superpowers/plans/2026-07-16-auto-cpu-and-error-dialog.md`
- 如果需要修改计划之外的文件或发现与既有修改冲突，停止并返回 `NEEDS_INPUT`。

---

### 任务一：CPU 自动配额纯函数与持久状态

**文件：**

- 修改：`fullpcr/gui_helpers.py`
- 修改：`tests/test_gui_helpers.py`

**接口：**

```python
def get_available_cpu_threads() -> int

def calculate_auto_cpu_threads(available_threads: int) -> int

def resolve_spec_cpu_threads(
    *,
    manual_enabled: bool,
    manual_threads: int | None,
    available_threads: int | None = None,
) -> int
```

**实施步骤：**

1. 在 `tests/test_gui_helpers.py` 新增纯函数失败测试：
   - `calculate_auto_cpu_threads(1,4,8,12,16,32)` 分别为 `1,2,4,7,9,19`。
   - affinity 为8而 `os.cpu_count()` 为32时，可用线程为8。
   - affinity 缺失、空集合、抛出 `OSError` 时回退 `os.cpu_count()`。
   - 两种来源都为 `None` 或非法值时回退1。
   - 自动模式忽略手动值。
   - 手动模式使用范围内值；0钳制到1；超过可用值钳制到上限；`None` 回退自动值。
2. 运行新增测试，确认因函数不存在而失败。
3. 在 `gui_helpers.py` 实现三个函数。60%必须使用向下取整，不能 `round()`。
4. 在 `_CANONICAL_DEFAULTS` 增加：

```python
"wf_s3_manual_cpu_enabled": False,
```

   保留 `wf_s3_cpu` 既有字段和既有默认值，作为手动输入的持久值。
5. 更新状态持久化测试，确认新增布尔状态在页面切换、验证输入和高级工作流显隐切换后不丢失。
6. 运行：

```bash
pytest -q tests/test_gui_helpers.py -k "CpuThreads or WorkflowSyncState"
```

   完成条件：新增测试全部通过，既有状态测试不回归。

---

### 任务二：一键计划和高级步骤共用 CPU 解析

**文件：**

- 修改：`fullpcr/gui_app.py`
- 修改：`tests/test_gui_helpers.py`

**接口依赖：**

- 使用任务一的 `get_available_cpu_threads()` 和 `resolve_spec_cpu_threads()`。
- `_build_pipeline_plan_from_state()` 继续返回现有五步 plan 结构。

**实施步骤：**

1. 新增失败测试：
   - mock可用线程16，默认一键 plan 的步骤3命令包含 `--cpu 9`。
   - 手动开关开启、手动值6时包含 `--cpu 6`。
   - 手动值20而可用线程16时命令使用16。
   - 关闭手动开关后命令恢复9，但 session state 中手动值仍为此前填写值。
   - 高级步骤3命令预览与一键 plan 的 `--cpu` 完全一致。
2. 运行新增测试并确认失败。
3. `_build_pipeline_plan_from_state()` 读取：

```text
wf_s3_manual_cpu_enabled
wf_s3_cpu
```

   使用共享解析函数得到最终 `cpu` 后再调用 `build_qc_spec_command()`。
4. 在高级步骤3的“高级参数”区域：
   - 增加“手动指定 CPU 线程数”开关；
   - 自动模式显示“自动使用 N 个线程（当前进程可用 M 个逻辑线程的60%）”；
   - 手动模式显示整数输入，`min_value=1`、`max_value=M`、`step=1`；
   - 不得删除 `max_tm`、`kvalue` 或 `force` 现有控件。
5. 高级步骤3命令预览和真实执行使用同一个已解析 CPU 值。
6. 运行：

```bash
pytest -q tests/test_gui_helpers.py -k "CpuThreads or SpecCustomParams or FullPipeline"
```

   完成条件：自动与手动两条路径命令一致，CLI测试无需修改。

---

### 任务三：保留完整原始错误和后台 traceback

**文件：**

- 修改：`fullpcr/gui_helpers.py`
- 修改：`fullpcr/pipeline_jobs.py`
- 修改：`fullpcr/mfeprimer_runner.py`
- 修改：`fullpcr/obipcr_runner.py`
- 修改：`tests/test_gui_helpers.py`
- 修改：`tests/test_pipeline_jobs.py`
- 修改：`tests/test_mfeprimer_runner.py`
- 修改：`tests/test_obipcr_runner.py`

**新增接口：**

```python
def build_execution_error_details(
    *,
    step_key: str,
    step_label: str,
    result: dict | None,
    job_id: str | None = None,
    background_error: str = "",
    background_traceback: str = "",
) -> dict
```

**实施步骤：**

1. 为错误详情函数新增失败测试，精确检查：
   - `step_key`、`step_label`、`job_id`、`status`、`returncode`；
   - 命令保留为可安全展示的数据；
   - 多行 stderr/stdout/traceback 完整保留；
   - 缺失结果时字段为空字符串而不抛异常。
2. 为两个 runner 新增超过500字符 stderr 的回归测试，要求返回的 `error_message` 包含首尾标记且长度不被截断。
3. 为后台任务新增测试：runner 抛异常后，终态为 `FAIL`，`error` 有摘要，新增 `traceback` 字段包含异常类型、异常文字和调用栈；旧状态 JSON 无该字段仍可读取。
4. 运行上述测试，确认当前实现失败。
5. 实现 `build_execution_error_details()`，不得截断、翻译或清洗原始文本；空值规范化为空字符串。
6. 删除 `mfeprimer_runner.py` 和 `obipcr_runner.py` 中 stderr 的 `[:500]` 截断。保持返回字段和 TSV 列结构不变。
7. `pipeline_jobs.py`：
   - `import traceback`；
   - 新任务初始状态写入 `"traceback": ""`；
   - `_run_job()` 未预期异常分支写入 `traceback.format_exc()`；
   - PASS及普通步骤失败保持 `traceback=""`；
   - 旧状态缺字段时按空字符串使用，不升级 schema、不判损坏。
8. 运行：

```bash
pytest -q tests/test_pipeline_jobs.py
pytest -q tests/test_mfeprimer_runner.py tests/test_obipcr_runner.py
pytest -q tests/test_gui_helpers.py -k "ExecutionErrorDetails"
```

   完成条件：错误正文和后台 traceback 都完整保存，既有返回契约不变。

---

### 任务四：统一错误对话框和一键分析防重复自动弹出

**文件：**

- 修改：`fullpcr/gui_app.py`
- 修改：`tests/test_gui_helpers.py`

**接口依赖：**

- 使用任务三的 `build_execution_error_details()`。
- 继续使用现有 `full_pipeline_result`、`wf_sN_result`、后台 `job_id/error/traceback`。

**实施步骤：**

1. 新增统一对话框渲染函数，使用：

```python
@st.dialog("分析失败", width="large")
```

   函数接收错误详情，并按以下固定标题渲染：
   - 失败步骤与状态
   - 后台任务ID
   - 返回码
   - 实际执行命令
   - 原始 stderr
   - 原始 stdout
   - 执行消息
   - 后台异常
   - 后台 Python traceback

   命令、stderr、stdout和traceback使用 `st.code(..., language=None)`；空内容显示“（无内容）”。
2. 新增一键分析错误详情提取辅助逻辑：
   - 依据 `outcome["failed_step"]` 映射到 `wf_sN_result`；
   - outcome缺少结果时仍使用后台 `error` 和 `traceback`；
   - `FAIL` 和 `TIMEOUT` 自动弹窗；`PASS` 不弹窗；
   - `CANCELLED` 只保留现有警告，不自动作为错误弹窗。
3. 新增 session state：

```text
last_auto_shown_error_job_id
```

   自动弹出前先写入当前 `job_id`。同一job的fragment轮询、页面交互、关闭弹窗和普通rerun不得再次自动调用；新job失败可以再次自动调用。
4. 终态失败区保留“查看完整错误”按钮，允许反复手动打开。单次脚本运行中自动与手动逻辑只能调用一次 dialog。
5. 新增 AppTest 或对话框调用边界测试，至少覆盖：
   - 首次失败触发自动打开；
   - 同一 `job_id` rerun不再自动打开；
   - 新 `job_id` 再次触发；
   - 手动按钮可以重新打开；
   - PASS不显示错误按钮；
   - 完整原始文字传入统一对话框。
6. 运行：

```bash
pytest -q tests/test_gui_helpers.py -k "ErrorDialog or FullPipelineUi or PersistentPipeline"
```

   如果当前 Streamlit AppTest 不暴露 dialog元素，可测试纯详情构建、弹窗调用判定和session state防重复边界；不得为测试而改用非模态伪弹窗。

---

### 任务五：高级五步运行接入同一错误对话框

**文件：**

- 修改：`fullpcr/gui_app.py`
- 修改：`tests/test_gui_helpers.py`

**实施步骤：**

1. 为 `_render_step_result()` 或其调用边界增加测试：
   - 高级步骤结果为 `FAIL`、`TIMEOUT` 时显示“查看完整错误”按钮；
   - `PASS` 时不显示；
   - 按钮调用与一键分析相同的统一对话框；
   - 原有stdout/stderr expander继续存在。
2. 每个高级步骤真实运行按钮在本次调用返回 `FAIL` 或 `TIMEOUT` 后立即请求自动打开一次对话框。
3. 自动打开只发生在按钮点击的这次运行；后续普通rerun只保留手动查看按钮。
4. 步骤1至5不得复制五套弹窗正文。使用统一结果处理函数或单一状态键传递待显示错误。
5. `CANCELLED` 若高级同步运行路径没有该入口，保持现状；若收到该状态，显示既有终止信息和手动查看按钮，不自动作为失败弹窗。
6. 运行：

```bash
pytest -q tests/test_gui_helpers.py -k "ErrorDialog or StepResultDisplay"
```

   完成条件：一键和高级分步使用同一对话框，普通rerun不重复自动弹出。

---

### 任务六：全量验证和范围审计

**允许操作：** 只读检查和测试；仅为修复本计划引入的失败修改已允许文件。

1. 运行定向测试：

```bash
pytest -q tests/test_gui_helpers.py -k "Cpu or ErrorDialog or FullPipeline"
pytest -q tests/test_pipeline_jobs.py
pytest -q tests/test_mfeprimer_runner.py tests/test_obipcr_runner.py
```

2. 运行完整检查：

```bash
pytest -q
python3 -m compileall -q fullpcr
git diff --check
```

3. 检查实际 diff 和范围：

```bash
git status --short
git diff --stat
git diff -- fullpcr/gui_helpers.py fullpcr/gui_app.py fullpcr/pipeline_jobs.py \
  fullpcr/mfeprimer_runner.py fullpcr/obipcr_runner.py \
  tests/test_gui_helpers.py tests/test_pipeline_jobs.py \
  tests/test_mfeprimer_runner.py tests/test_obipcr_runner.py
```

4. 报告：
   - 每条命令的真实退出状态和测试数量；
   - CPU自动/手动测试证据；
   - 一键和高级错误弹窗测试证据；
   - 完整stderr和traceback不截断证据；
   - `git status --short`；
   - 未执行或受环境限制的检查；
   - MFEprimer 4.3.1仍属于已知非目标。

## 完成条件

- 所有定向测试、全量测试、compileall和diff检查实际通过。
- 默认CPU值严格等于可用逻辑线程数60%的向下取整，至少1。
- 手动覆盖范围不超过当前进程可用线程数。
- 一键与高级步骤命令使用相同CPU解析结果。
- 一键分析失败对每个job自动弹窗一次，并能手动再次查看。
- 高级步骤失败在本次执行后自动弹窗一次，普通rerun不重复。
- 命令、返回码、完整stderr、完整stdout和完整traceback可在统一弹窗查看。
- 未修改MFEprimer 4.3.1兼容逻辑、CLI语义、分析算法或输出格式。
- 无范围外修改、无commit、无push、无Git历史变化。
