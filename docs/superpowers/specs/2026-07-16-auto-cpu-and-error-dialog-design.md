# fullpcr 自动 CPU 配额与完整错误弹窗设计

## 目标

本轮只完成两项运行可靠性改进：

1. 网站默认根据当前服务器进程实际可用的逻辑线程数，自动为 MFEprimer 索引和特异性分析分配 60% CPU 线程；高级分步工作流保留手动覆盖能力。
2. 一键五步分析或高级分步运行失败时，自动弹出一次完整错误窗口，展示实际命令、返回码、原始 stderr、原始 stdout 和后台 Python traceback；关闭后仍可通过按钮重新查看。

CLI 现有 `--cpu` 参数语义保持不变。文件上传、输入格式验证以及普通页面提示继续使用现有页内错误信息。

本轮明确不修复 MFEprimer 4.3.1 的 `.primerqc.bin` 索引和 23 列 Spec TSV 兼容问题。该问题发生时，新弹窗应完整展示错误，但不会自动解决错误。

## 已确认现状

- 网站当前通过 `wf_s3_cpu` 固定使用 4 个线程。
- CPU 参数只传递给 MFEprimer `index` 和 `spec`，其他四步没有可安全复用的同类线程参数。
- 一键分析的后台 outcome 已保存各步骤的 `command`、`returncode`、`stdout`、`stderr` 和 `message`。
- 一键分析失败时，快速分析区目前只显示概括信息，没有显示失败步骤的原始输出。
- 高级分步工作流已有 stdout/stderr expander，但没有统一弹窗。
- `mfeprimer_runner.py` 和 `obipcr_runner.py` 当前会把内部工具的非零退出 stderr 截断为 500 字符后写入 `error_message`。要满足“原始报错全部显示”，本轮必须移除这一截断，但不改变失败任务 TSV 的字段结构。
- 后台工作线程捕获未预期异常时当前只保存 `str(exc)`，没有保存完整 traceback。

## CPU 自动配额

### 可用线程检测

新增纯函数检测当前进程可用的逻辑线程数：

```python
def get_available_cpu_threads() -> int
```

检测顺序固定为：

1. 如果平台支持 `os.sched_getaffinity(0)`，使用 affinity 集合长度。这样 Linux 虚拟机、容器或受 CPU affinity 限制的服务不会使用宿主机不可用的线程。
2. affinity 不可用、返回空集合或抛出异常时，使用 `os.cpu_count()`。
3. 两种来源均不可用或值无效时，回退为 1。

返回值始终为大于等于 1 的整数。

### 60% 计算

新增纯函数：

```python
def calculate_auto_cpu_threads(available_threads: int) -> int
```

计算规则为：

```text
max(1, floor(available_threads × 0.60))
```

固定示例：

| 可用逻辑线程 | 自动线程数 |
|---:|---:|
| 1 | 1 |
| 4 | 2 |
| 8 | 4 |
| 12 | 7 |
| 16 | 9 |
| 32 | 19 |

不得使用四舍五入，因为已确认采用向下取整，避免超过 60%。

### 自动和手动解析

新增共享解析函数：

```python
def resolve_spec_cpu_threads(
    *,
    manual_enabled: bool,
    manual_threads: int | None,
    available_threads: int | None = None,
) -> int
```

- `manual_enabled=False`：返回自动线程数。
- `manual_enabled=True`：使用手动值，但必须限制在 `1..available_threads`。
- `available_threads=None`：函数内部调用 `get_available_cpu_threads()`。
- 手动值缺失或无法转换为有效整数时，回退自动线程数，不得生成 0 或负数。

一键分析计划和高级步骤 3 命令预览、真实执行都必须调用这一个函数，避免两条路径使用不同 CPU 值。

### GUI 状态和控件

新增持久状态：

```text
wf_s3_manual_cpu_enabled = False
wf_s3_cpu = 现有手动值字段
```

高级分步工作流的步骤 3 高级参数区域显示：

- 默认关闭的“手动指定 CPU 线程数”开关。
- 自动模式下显示只读说明：

```text
自动使用 9 个线程（当前进程可用 16 个逻辑线程的 60%）
```

- 手动模式下显示整数输入框，范围为 `1..available_threads`，步长为 1。
- 关闭手动模式后保留用户上次填写值，但命令使用自动计算值。
- 再次开启手动模式时恢复此前填写值。
- 页面切换、输入验证和高级工作流显隐切换不得清除这两个状态。

`wf_s3_cpu` 的既有持久化字段继续保留，避免破坏旧会话和现有状态同步接口；新增布尔字段决定它是手动生效值还是仅为待恢复值。

## 完整错误数据

### 错误详情结构

新增纯函数，从一步执行结果和可选后台错误构建统一结构：

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

返回结构至少包含：

```text
step_key
step_label
job_id
status
returncode
command
stderr
stdout
message
background_error
background_traceback
```

所有文本字段保留原始换行。空值转换为空字符串，不对 stderr、stdout 或 traceback 截断、翻译、去重或摘要。

一键分析使用 `outcome["failed_step"]` 找到对应的 `wf_sN_result`；如果 outcome 缺少步骤结果但任务状态含后台异常，仍生成可展示的错误详情。

### 原始工具错误不得截断

删除 `mfeprimer_runner.py` 和 `obipcr_runner.py` 中对非零退出 stderr 的 `[:500]` 截断。仍可使用 `strip()` 判断 stderr 是否为空，但保存和向 CLI 打印的错误正文必须包含完整 stderr。

此修改不改变：

- runner 返回字典的既有字段名；
- `qc_failed_jobs.tsv` 和 `failed_jobs.tsv` 的列结构；
- 成功、跳过和超时状态语义；
- stdout/stderr 日志文件位置。

如果工具输出非常长，弹窗和 TSV 可能包含较长文本，这是“原始报错全部显示”的预期行为。

### 后台 traceback

`pipeline_jobs.py` 捕获后台未预期异常时，同时保存：

```text
error = 后台分析任务异常摘要
traceback = traceback.format_exc() 的完整结果
```

状态 JSON 新增可选 `traceback` 字段。正常任务该字段为空字符串。读取旧状态文件时字段不存在必须兼容，不得视为状态损坏。

## 错误弹窗

### 单一组件

`gui_app.py` 新增一个统一的大尺寸 `st.dialog` 组件，一键分析和高级分步工作流共同调用。不得分别维护两套内容格式。

标题格式：

```text
分析失败：特异性分析
```

弹窗按固定顺序显示：

1. 步骤名称和状态；
2. 后台任务 ID（存在时）；
3. 返回码，缺失时显示“无”；
4. 实际执行命令；
5. 原始 stderr；
6. 原始 stdout；
7. 执行消息；
8. 后台异常摘要；
9. 后台完整 Python traceback。

命令、stderr、stdout 和 traceback 使用 `st.code(..., language=None)`。没有内容时显示明确的“（无内容）”，不能直接隐藏区块。弹窗不提供会修改任务状态的操作。

当前项目已经使用 `st.fragment`，因此继续以现有 Streamlit 运行环境为前提使用 `st.dialog`，不新增第三方 UI 依赖。

### 一键分析自动弹出

自动弹出标识使用稳定的任务 ID：

```text
last_auto_shown_error_job_id
```

终态任务满足以下条件时自动调用弹窗：

- `status` 为 `FAIL` 或 `TIMEOUT`；
- 当前 `job_id` 非空；
- 当前 `job_id` 不等于 `last_auto_shown_error_job_id`。

调用弹窗前先写入 `last_auto_shown_error_job_id`，避免 fragment 的 1 秒轮询、点击页面其他控件或关闭弹窗后再次自动出现。

相同项目重新运行会得到新 `job_id`，如果再次失败必须自动弹出一次。

任务终态区域始终保留“查看完整错误”按钮。手动点击不受 `last_auto_shown_error_job_id` 限制，可以反复打开。

只有一个弹窗可以在单次 Streamlit 脚本运行中打开。自动弹窗与手动按钮必须通过同一分支仲裁，同一次运行不得调用两次 dialog。

### 高级分步运行自动弹出

高级步骤按钮同步获得本次 `run_gui_command()` 结果后：

- `PASS`：保持现有成功展示，不弹窗。
- `FAIL`、`TIMEOUT` 或 `CANCELLED`：立即自动弹窗一次。

由于自动调用只位于按钮点击分支，普通 rerun 不会再次自动弹出。步骤结果下方保留“查看完整错误”按钮，允许再次查看。

原有 stdout/stderr expander可以保留，避免改变高级工作流现有信息结构；弹窗是统一的完整诊断入口。

### 文件输入错误

下列错误保持现状，不使用运行错误弹窗：

- 文件上传保存失败；
- 输入文件格式校验失败；
- 路径不存在或不安全；
- 用户尚未完成输入验证。

## 状态与数据流

```text
服务器 CPU/affinity
        ↓
共享 CPU 解析函数
        ↓
一键分析计划 / 高级步骤 3 命令
        ↓
run_gui_command 捕获完整 stdout/stderr
        ↓
后台 outcome 或高级步骤 session_state
        ↓
共享错误详情构建函数
        ↓
自动一次弹窗 + 可重复手动查看
```

CPU 计算只在构建命令时执行。任务启动后，不因页面 rerun 或服务器负载变化重写已经持久化在 plan 中的 `--cpu` 值。

## 错误处理

- affinity 查询抛出异常：回退 `os.cpu_count()`。
- CPU 数量来源无效：使用 1。
- 手动线程值超范围：安全限制到可用范围，同时控件本身也使用相同上下限。
- outcome 缺少失败步骤结果：弹窗仍显示后台 `error` 和 traceback，其他字段显示“无内容”。
- stderr 为空而 stdout 含错误：stdout 原样展示。
- 命令不是字符串列表：只进行安全字符串化展示，不执行 shell 拼接。
- 状态 JSON 来自旧版本且没有 traceback：按空字符串处理。
- 弹窗关闭、页面切换和 fragment 轮询不得修改任务状态、重新提交命令或清除已有错误详情。

## 测试与验收

### CPU 纯函数测试

- 可用线程为 1、4、8、12、16、32 时，自动值分别为 1、2、4、7、9、19。
- affinity 为 8、`os.cpu_count()` 为 32 时返回 8 个可用线程并自动使用 4。
- affinity 不可用或抛异常时回退 `os.cpu_count()`。
- 两个来源均无效时返回 1。
- 自动模式忽略已保存的手动值。
- 手动模式正确使用范围内的值。
- 手动值小于 1、超过可用线程或缺失时不产生非法线程数。

### 命令一致性测试

- 默认一键分析的 `qc-spec` 命令包含自动计算后的 `--cpu`。
- 高级步骤 3 命令预览与一键计划使用相同的 CPU 解析结果。
- 开启手动模式后两条路径都使用手动值。
- 关闭手动模式后恢复自动值，但保存的手动输入不丢失。
- CLI 直接使用 `--cpu` 的现有测试保持不变。

### 错误数据测试

- 错误详情保留多行命令、完整 stderr、完整 stdout 和 traceback。
- 超过 500 字符的 MFEprimer/obipcr stderr 不再被截断。
- 空字段规范化为空字符串。
- outcome 缺少步骤结果时仍能显示后台异常。
- 后台线程异常状态保存完整 traceback，旧状态文件仍可读取。

### Streamlit AppTest

- 一键分析失败后自动弹窗一次。
- 同一 `job_id` 的 fragment 轮询和普通 rerun 不重复自动弹窗。
- 新 `job_id` 失败后再次自动弹窗。
- 关闭后点击“查看完整错误”可以重新打开。
- 高级步骤 1 至 5 任一步失败都自动弹窗，并保留手动查看按钮。
- 弹窗包含步骤、返回码、命令、stderr、stdout 和 traceback 的对应标题及原始文本。
- PASS 任务不显示错误按钮且不弹窗。
- 文件上传和输入验证错误仍保持页内展示。

### 最终检查

必须实际执行：

```bash
pytest -q tests/test_gui_helpers.py -k "Cpu or ErrorDialog or FullPipeline"
pytest -q tests/test_pipeline_jobs.py
pytest -q tests/test_mfeprimer_runner.py tests/test_obipcr_runner.py
pytest -q
python3 -m compileall -q fullpcr
git diff --check
```

使用本地 HTTP 服务手工验证：

1. 自动模式命令预览显示当前服务器可用线程数的 60%。
2. 开启手动模式后命令预览立即使用手动值。
3. 制造一个可控失败，确认弹窗自动出现一次。
4. 关闭弹窗并等待多个轮询周期，确认不重新自动出现。
5. 点击“查看完整错误”，确认完整 traceback 和原始 stderr 可复制。

## 修改范围

预计只修改：

- `fullpcr/gui_helpers.py`
- `fullpcr/gui_app.py`
- `fullpcr/pipeline_jobs.py`
- `fullpcr/mfeprimer_runner.py`
- `fullpcr/obipcr_runner.py`
- `tests/test_gui_helpers.py`
- `tests/test_pipeline_jobs.py`
- `tests/test_mfeprimer_runner.py`
- `tests/test_obipcr_runner.py`

如果实现需要修改上述范围以外的 Python 模块、结果文件格式、CLI 参数语义或分析算法，必须停止并报告，不得自行扩大范围。

## 非目标

- 不修复或规避 MFEprimer 4.3.1 兼容问题。
- 不自动安装、升级或降级 MFEprimer/OBITools。
- 不给 obipcr 或不支持线程参数的步骤添加虚构 CPU 选项。
- 不根据实时 CPU 使用率动态改变已经启动任务的线程数。
- 不引入任务队列、数据库、日志服务或第三方弹窗组件。
- 不修改五步顺序、参数含义、分析算法和输出文件格式。
- 不提交、不推送、不修改 Git 历史。
