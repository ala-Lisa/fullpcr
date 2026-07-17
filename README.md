# fullpcr

Batch in silico PCR analysis tool using OBITools4 `obipcr` + MFEprimer QC.

## 目标

用 Python 批量调用 `obipcr`，解析结果，统计覆盖率、非目标扩增和物种分辨率，结合 MFEprimer 热力学和特异性分析，生成统一引物评价报告。

不重写 OBITools4，不改动 OBITools4 源码。

## 依赖

- **Python** >= 3.10
- **OBITools4** — `obipcr` 必须在 PATH 中可用
- **MFEprimer** — `mfeprimer` v4.2.4 必须在 PATH 中可用，用于 thermo、dimer、hairpin、degen 和 spec

## 推荐部署（v0.1.0）

新 Linux/WSL 机器推荐使用 Conda/Mamba，并部署不可变标签 `v0.1.0`。完整命令、MFEprimer 官方二进制 SHA256、局域网访问、systemd、迁移、升级和回滚说明见 **[DEPLOYMENT.md](DEPLOYMENT.md)**。

已验证的参考环境：

| 组件 | 版本 |
|---|---:|
| fullpcr | 0.1.0 / `v0.1.0` |
| Python | 3.13.14 |
| OBITools4 | 4.4.46 |
| MFEprimer | 4.2.4 |
| Streamlit | 1.59.1 |
| pandas | 3.0.3 |

> MFEprimer 4.3.1 会改变索引及 Spec TSV 格式，当前 `v0.1.0` 不支持。不要因为环境指示为绿色就跳过实际版本检查和五步分析验收。

最短安装路径如下；MFEprimer 4.2.4 必须按部署手册下载并校验后再启动：

```bash
git clone https://github.com/ala-Lisa/fullpcr.git
cd fullpcr
git checkout v0.1.0

mamba create -n fullpcr -c conda-forge -c bioconda \
  python=3.13.14 obitools4=4.4.46 pip -y
conda activate fullpcr

# 按 DEPLOYMENT.md 安装并校验 MFEprimer 4.2.4
python -m pip install "streamlit==1.59.1" "pandas==3.0.3"
python -m pip install --no-deps .
```

本机启动：

```bash
mkdir -p "$HOME/fullpcr-data"
python -m fullpcr gui \
  --host 127.0.0.1 --port 8501 \
  --data-dir "$HOME/fullpcr-data"
```

可信局域网启动时，将 host 改为 `0.0.0.0`，同事通过 `http://<服务器真实-LAN-IP>:8501` 访问；不要把 `0.0.0.0` 当作浏览器地址。

部署完成后至少检查：

```bash
python --version
obipcr --version
mfeprimer version
curl -fsS http://127.0.0.1:8501/_stcore/health
```

health 返回 `ok` 只代表 Web 服务可用；仍须完成一次真实完整分析。开发安装可使用 `pip install -e ".[dev,gui]"`，不要与生产环境混用。

## 完整工作流

fullpcr 提供 7 个子命令：

| 步骤 | 子命令 | 功能 |
|------|--------|------|
| 1 | `qc-pre` | 导出引物 input FASTA、运行 MFEprimer thermo/dimer/hairpin |
| 2 | `qc-summary` | 解析 MFEprimer 原始输出，生成 `primer_qc_summary.tsv` |
| 3 | `qc-spec` | 数据库索引 + MFEprimer specificity 筛选 |
| 4 | `run` | 批量 obipcr in silico PCR |
| 5 | `summarize` | 汇总 obipcr 结果，生成统计文件 |
| 6 | `report` | 基于 obipcr 结果生成 Markdown 报告 |
| 7 | `final-report` | 整合 obipcr + QC + spec，生成统一引物评价 |

## 推荐运行顺序

以下命令假设 `example_data/` 目录包含 `primers.tsv`、`database.fasta`、`taxonomy.tsv`。

### 1. MFEprimer QC：热力学 / 二聚体 / 发夹

```bash
python3 -m fullpcr qc-pre \
  --primers example_data/primers.tsv \
  --outdir qc_results \
  --thermo --dimer --hairpin \
  --score 5 --mismatch 2 --dg -5.0 --tm 50.0
```

### 2. QC 汇总

```bash
python3 -m fullpcr qc-summary \
  --qc-dir qc_results
```

### 3. 数据库规范化 + MFEprimer 特异性筛选

```bash
python3 -m fullpcr qc-spec \
  --primers example_data/primers.tsv \
  --database example_data/database.fasta \
  --outdir qc_spec_results \
  --max-size 2000 --tm 30.0 --cpu 4
```

### 4. obipcr 批量 in silico PCR

```bash
python3 -m fullpcr run \
  --primers example_data/primers.tsv \
  --database qc_spec_results/index/database.fasta \
  --taxonomy example_data/taxonomy.tsv \
  --outdir obipcr_results \
  --mismatches 0,1,2 \
  --circular \
  --summarize \
  --report \
  --force
```

> **注意**：为了与 MFEprimer spec 在同一份规范化数据库上运行，建议 `--database` 使用 `qc-spec` 输出的 `index/` 中的数据库文件。

### 5. 引物评价最终报告

```bash
python3 -m fullpcr final-report \
  --obipcr-dir obipcr_results \
  --qc-dir qc_results \
  --spec-dir qc_spec_results \
  --outdir final_results
```

## CLI 参考

### qc-pre — MFEprimer 质控

```bash
python3 -m fullpcr qc-pre \
  --primers <path> \
  --outdir <path> \
  [--thermo] [--dimer] [--hairpin] \
  [--dry-run] [--resume] [--force] \
  [--score N] [--mismatch N] [--dg FLOAT] [--tm FLOAT] \
  [--timeout SECONDS] \
  [--degen] [--max-degenerate-variants N]
```

| 参数 | 必需 | 说明 |
|------|------|------|
| `--primers` | ✓ | primers.tsv 路径 |
| `--outdir` | ✓ | QC 输出目录 |
| `--thermo` | | 运行热力学分析 |
| `--dimer` | | 运行二聚体分析 |
| `--hairpin` | | 运行发夹结构分析 |
| `--dry-run` | | 仅打印计划不执行 |
| `--resume` | | 跳过已有输出文件 |
| `--force` | | 强制重新运行 |
| `--score` | | 二聚体/发夹比对分数阈值（默认 5） |
| `--mismatch` | | 二聚体允许错配数（默认 2） |
| `--dg` | | 二聚体/发夹自由能阈值 kcal/mol（默认 -5.0） |
| `--tm` | | 发夹熔解温度阈值（默认 50.0） |
| `--timeout` | | 每次 MFEprimer 调用的超时秒数 |
| `--degen` | | 展开简并引物 |
| `--max-degenerate-variants` | | 最大简并变体数（默认 256） |

### qc-summary — QC 结果汇总

```bash
python3 -m fullpcr qc-summary --qc-dir <path>
```

| 参数 | 必需 | 说明 |
|------|------|------|
| `--qc-dir` | ✓ | QC 结果目录（含 thermo/, dimer/, hairpin/） |

### qc-spec — MFEprimer 特异性筛选

```bash
python3 -m fullpcr qc-spec \
  --primers <path> \
  --database <path> \
  --outdir <path> \
  [--min-size N] [--max-size N] \
  [--tm FLOAT] [--max-tm FLOAT] \
  [--mismatch N] [--kvalue N] [--cpu N] \
  [--timeout SECONDS] \
  [--force] [--resume] [--dry-run]
```

| 参数 | 必需 | 说明 |
|------|------|------|
| `--primers` | ✓ | primers.tsv 路径 |
| `--database` | ✓ | FASTA 数据库路径 |
| `--outdir` | ✓ | 输出目录 |
| `--min-size` | | 最小 amplicon 长度 (bp) |
| `--max-size` | | 最大 amplicon 长度 (bp，默认 2000) |
| `--tm` | | 最小 Tm (°C，默认 30.0) |
| `--max-tm` | | 最大 Tm (°C，默认 100.0) |
| `--mismatch` | | k-mer 结合允许错配数 |
| `--kvalue` | | k-mer 大小（默认 9） |
| `--cpu` | | CPU 线程数（默认 4） |
| `--timeout` | | 每次 MFEprimer 调用的超时秒数 |
| `--force` | | 强制重新建索引和运行 |
| `--resume` | | 跳过已有输出 |
| `--dry-run` | | 仅打印命令不执行 |

### run — 执行 in silico PCR

```bash
python3 -m fullpcr run \
  --primers <path> \
  --database <path> \
  --outdir <path> \
  --mismatches <levels> \
  [--circular] \
  [--dry-run] \
  [--resume] \
  [--force] \
  [--jobs N] \
  [--timeout <seconds>] \
  [--summarize] \
  [--report] \
  [--taxonomy <path>]
```

| 参数 | 必需 | 说明 |
|------|------|------|
| `--primers` | ✓ | primers.tsv 路径 |
| `--database` | ✓ | FASTA 数据库路径（`.fasta`, `.fa`, `.fasta.gz`, `.fa.gz`） |
| `--outdir` | ✓ | 输出目录根路径 |
| `--mismatches` | ✓ | 逗号分隔的 mismatch 级别，如 `"0,1,2,3"` |
| `--circular` | | 使用环状 DNA 模式 |
| `--dry-run` | | 仅打印命令，不实际执行 |
| `--resume` | | 跳过已有 `obipcr_amplicons.fasta` + `amplicons.tsv` 的任务 |
| `--force` | | 与 `--resume` 一起使用时强制重跑 |
| `--jobs` | | 并行任务数（默认 1，当前仅支持串行） |
| `--timeout` | | 每个 obipcr 调用的超时秒数（默认无超时） |
| `--summarize` | | 执行后立即生成 summary 文件 |
| `--report` | | 执行后立即生成 report.md |
| `--taxonomy` | | taxonomy.tsv 路径（供 `--summarize` 和 `--report` 使用） |

### summarize — 独立生成 summary 文件

```bash
python3 -m fullpcr summarize \
  --indir <results_dir> \
  [--taxonomy <taxonomy.tsv>]
```

| 参数 | 必需 | 说明 |
|------|------|------|
| `--indir` | ✓ | 包含 `primer_id/mismatch_N/amplicons.tsv` 的结果目录 |
| `--taxonomy` | | taxonomy.tsv 路径（可选） |

### report — 独立生成报告

```bash
python3 -m fullpcr report --indir <results_dir>
```

| 参数 | 必需 | 说明 |
|------|------|------|
| `--indir` | ✓ | 包含 summary TSV 文件的结果目录 |

### final-report — 引物评价最终报告

```bash
python3 -m fullpcr final-report \
  --obipcr-dir <obipcr_results> \
  --qc-dir <qc_results> \
  --spec-dir <spec_results> \
  --outdir <output_dir>
```

| 参数 | 必需 | 说明 |
|------|------|------|
| `--obipcr-dir` | ✓ | obipcr 结果目录（含 `combined_summary.tsv`） |
| `--qc-dir` | ✓ | MFEprimer QC 目录（含 `primer_qc_summary.tsv`） |
| `--spec-dir` | ✓ | MFEprimer spec 目录（含 `spec/primer_spec.tsv` 和 `index/database_stats.tsv`） |
| `--outdir` | ✓ | 输出目录 |

## 输入文件格式

### primers.tsv

Tab 分隔，**必填字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `primer_id` | string | 引物对标识 |
| `forward` | string | 前向引物序列 |
| `reverse` | string | 反向引物序列 |
| `min_length` | int | 最小扩增长度 (bp) |
| `max_length` | int | 最大扩增长度 (bp) |

示例：

```text
primer_id	forward	reverse	min_length	max_length
COI_short	GGTCAACAAATCATAAAGATATTGG	TAAACTTCAGGGTGACCAAAAAATCA	100	400
16S_short	GACGAGAAGACCCTATGGAGC	CGCTGTTATCCCTAGGGTAACT	200	600
```

### taxonomy.tsv

Tab 分隔，**必填字段**：

| 字段 | 说明 |
|------|------|
| `taxid` | NCBI taxonomy ID（匹配主键） |
| `scientific_name` | 学名 |

推荐字段：`kingdom`, `phylum`, `class`, `order`, `family`, `genus`, `species`

示例：

```text
taxid	scientific_name	kingdom	phylum	class	order	family	genus	species
9606	Homo sapiens	Animalia	Chordata	Mammalia	Primates	Hominidae	Homo	Homo sapiens
9913	Bos taurus	Animalia	Chordata	Mammalia	Cetartiodactyla	Bovidae	Bos	Bos taurus
```

Taxonomy 合并规则：
- 以 `taxid` 为主键匹配
- 若 taxid 未匹配，fallback 到 `scientific_name`
- 若仍未匹配，fallback 到 `species`
- 完全未匹配的记录标记为 `taxonomy_status="missing"`，不会丢弃

## 输出文件

### 执行输出（per primer × mismatch）

```text
results/
  COI_short/
    mismatch_0/
      obipcr_amplicons.fasta   # obipcr 原始 FASTA 输出
      obipcr.stderr.log        # obipcr stderr 日志
      amplicons.tsv            # 解析后的结构化记录
    mismatch_1/
      ...
  failed_jobs.tsv              # 失败任务记录（始终有表头）
```

### Summary 文件（`--summarize` 或 `summarize` 子命令）

| 文件 | 内容 |
|------|------|
| `combined_summary.tsv` | 每个 primer × mismatch 的统计指标 |
| `coverage_by_taxon.tsv` | 按 kingdom→species 级别的分类覆盖统计 |
| `length_distribution.tsv` | 扩增片段长度分布 |
| `mismatch_distribution.tsv` | forward/reverse mismatch 分布 |
| `species_resolution.tsv` | 物种分辨率统计 |

### QC 输出（`qc-pre` + `qc-summary`）

| 文件 | 内容 |
|------|------|
| `primer_qc_summary.tsv` | 引物热力学、二聚体、发夹 QC 摘要 |

### Spec 输出（`qc-spec`）

| 文件 | 内容 |
|------|------|
| `index/database.fasta` | 规范化后的数据库文件 |
| `index/database_stats.tsv` | 数据库完整性统计 |
| `spec/primer_spec.tsv` | 引物对特异性筛选结果 |

### 最终评价报告（`final-report`）

| 文件 | 内容 |
|------|------|
| `primer_rank.tsv` | 引物综合排名（22 字段：obipcr 覆盖、QC 状态、spec 结果、综合评分） |
| `final_report.md` | Markdown 最终报告（11 章节：Overview、数据库完整性、排名、各源摘要、推荐/不推荐引物、已知限制） |

**`primer_rank.tsv` 字段说明**：

| 字段 | 来源 | 说明 |
|------|------|------|
| `primer_id` | | 引物对标识 |
| `best_mismatch` | obipcr | 最优 mismatch 级别 |
| `obipcr_amplicon_count` | obipcr | 扩增条数 |
| `obipcr_unique_species_count` | obipcr | 唯一物种数 |
| `obipcr_species_resolution_rate` | obipcr | 物种分辨率 |
| `mean_amplicon_length` | obipcr | 平均扩增长度 |
| `missing_taxonomy_count` | obipcr | 缺失 taxonomy 记录数 |
| `qc_status` | MFEprimer | QC 状态（PASS / WARN_* / FAIL_*） |
| `tm_difference` | MFEprimer | 正反向引物 Tm 差 |
| `dimer_count` | MFEprimer | 二聚体数 |
| `hairpin_count` | MFEprimer | 发夹结构数 |
| `degen_status` | MFEprimer | 简并状态 |
| `degen_variant_count` | MFEprimer | 简并变体数 |
| `spec_status` | MFEprimer | 特异性状态 |
| `spec_amplicon_count` | MFEprimer | spec 预测扩增数 |
| `spec_unique_reference_count` | MFEprimer | 匹配参考序列数 |
| `spec_unique_species_count` | MFEprimer | 匹配物种数 |
| `spec_reference_fraction` | MFEprimer | 参考序列覆盖率 |
| `final_score` | 综合 | 加权综合评分（0-1） |
| `final_status` | 综合 | 最终状态等级 |
| `recommendation` | 综合 | 推荐说明 |
| `reason` | 综合 | 关键发现说明 |

**评分权重**：obipcr 覆盖 (40%) + QC 健康 (30%) + spec 特异性 (30%)

**状态等级**：
- `RECOMMENDED` — 综合评分 ≥ 0.70，无警告
- `ACCEPTABLE_WITH_WARNINGS` — 评分 < 0.70 或存在 WARN_* 项
- `NOT_RECOMMENDED` — 评分 < 0.25 或存在致命缺陷
- `NEEDS_REVIEW` — 所有数据缺失，无法评价

### Report（`--report` 或 `report` 子命令）

| 文件 | 内容 |
|------|------|
| `report.md` | Markdown 报告：Run Summary、Primer Performance、Taxonomic Coverage、Length Distribution、Mismatch Distribution、Species Resolution、Failed Jobs、Known Limitations |

## 当前 example_data 验证结论

以下基于 `example_data/` 中 85 条线粒体基因组序列的测试结果。

### 最终排名

| Primer | Score | Status | 说明 |
|--------|-------|--------|------|
| **12S_long** | 0.9414 | ACCEPTABLE_WITH_WARNINGS | 高覆盖（83 条 amplicon、59 物种、分辨率 91.5%），Tm 差 8.09°C 需注意 |
| 16S_short | 0.682 | ACCEPTABLE_WITH_WARNINGS | obipcr 仅扩增 2 条（1 物种），但 MFEprimer spec 显示可扩增 85 条——两种算法结论不一致 |
| COI_short | 0.30 | NOT_RECOMMENDED | obipcr 和 spec 均无扩增 |
| COI_full | 0.30 | NOT_RECOMMENDED | obipcr 和 spec 均无扩增 |

### 关键发现

1. **12S_long 排名第一**：覆盖 59/61 物种（96.7%）、分辨率 91.5%、长度集中在 388-405 bp。唯一警告是正反向引物 Tm 差 8.09°C（>5°C 阈值），建议调整 PCR 条件。
2. **16S_short 作为备选**：MFEprimer spec 预测 85 条扩增，但 obipcr 实际仅扩增 2 条——两个算法在 16S 区域结论明显分歧，需要 wet-lab 验证。
3. **COI 引物不推荐**：在当前数据库和参数设定下无扩增。
4. **最终结果目录**：`final_results_normalized/`（基于规范化后的 85 条 FASTA 数据库，与 MFEprimer spec 运行在同一份数据上）。

## 测试

```bash
pytest -q
```

测试使用 mock obipcr，不依赖真实 OBITools4 环境。

## GUI usage

fullpcr provides a Streamlit-based graphical interface for the complete analysis workflow.

### Install GUI dependencies

```bash
pip install -e ".[gui]"
```

### Launch

**Method 1 — direct streamlit invocation:**

```bash
streamlit run fullpcr/gui_app.py
```

**Method 2 — fullpcr CLI subcommand:**

```bash
python -m fullpcr gui
```

Both methods are equivalent. Method 2 provides a clear error message with install instructions if streamlit is missing.

**Default behaviour:** binds to `127.0.0.1:8501` — only the local machine can access it.

#### Local-only access

```bash
python -m fullpcr gui
```

Open in browser: `http://127.0.0.1:8501`

#### LAN access (regular Linux / company server)

```bash
python -m fullpcr gui --host 0.0.0.0 --port 8501
```

Other devices on the same network access the GUI at:

```
http://<server-LAN-IP>:8501
```

Important notes:

- `0.0.0.0` is a **bind address** — it tells the server to accept connections on all interfaces. It is **not** a browser URL. Browsers must use the server's real LAN IP.
- The client device must have network connectivity to the server (same subnet, no AP/client isolation).
- The server's operating system or company firewall must allow inbound TCP on the chosen port.
- Do **not** configure router port forwarding to expose this service to the public internet.

#### WSL (Windows Subsystem for Linux)

WSL networking behaviour depends on the WSL version and mode:

| Mode | Windows browser | Other WiFi devices |
|------|-----------------|-------------------|
| WSL2 default NAT | Try `http://localhost:8501` | Usually **not** reachable directly |
| WSL2 mirrored mode | `http://localhost:8501` | May be reachable via host LAN IP |
| WSL1 | `http://localhost:8501` | May be reachable via host LAN IP |

Check your WSL networking mode:

```bash
grep -i microsoft /proc/version    # confirms WSL
hostname -I                         # WSL NAT IP (e.g. 172.x) vs LAN IP
```

If you need external device access under WSL2 NAT mode, see Microsoft's official documentation:

<https://learn.microsoft.com/en-us/windows/wsl/networking>

Mirrored mode or a Windows `netsh interface portproxy` rule may be required. Any portproxy configuration must follow company security policy and is outside the scope of this tool.

#### Security

The current Streamlit GUI does **not** have built-in login authentication or TLS encryption:

- Only use on a trusted internal network (company LAN or home WiFi).
- Do **not** expose the GUI to the public internet via router port forwarding.
- Do **not** bind to `0.0.0.0` on a machine directly connected to a public network.
- For production or cross-network deployment, place the service behind a **reverse proxy** (e.g. nginx, Caddy) with HTTPS and identity authentication. This will be covered in a later deployment phase.

#### Troubleshooting connectivity

Check the server's IP addresses:

```bash
hostname -I
ip -4 addr
```

Verify Streamlit is listening on the expected interface:

```bash
ss -ltnp | grep 8501
# Expected: 0.0.0.0:8501 (or 127.0.0.1:8501 for local-only)
```

Test the server locally:

```bash
curl http://127.0.0.1:8501/_stcore/health
# Expected: ok
```

Common issues:

- **Firewall**: Linux `ufw`/`firewalld`, Windows Defender Firewall, or corporate firewall may block the port.
- **AP/client isolation**: Some WiFi access points prevent wireless clients from communicating with each other.
- **WSL NAT**: Other devices on the same WiFi generally cannot reach WSL2's internal NAT IP. Use mirrored mode, portproxy, or run on a native Linux server.

### GUI pages

| Page | Function |
|------|----------|
| **分析工作台** (Analysis Workbench) | Merged page: validate input files, configure analysis parameters, preset selection, run the 5-step pipeline (qc-pre → qc-summary → qc-spec → obipcr → final-report) across tabs |
| **结果总览** (Results Overview) | Browse primer_rank.tsv, view final_score bar charts, inspect QC & spec status tables |
| **报告与下载** (Reports & Downloads) | View final_report.md and obipcr report.md as rendered Markdown, download reports |

The header bar includes an **environment popover** (🟢/🔴 indicator) showing Python, fullpcr, obipcr, and MFEprimer availability. It caches results for 60 seconds — click "重新检查环境" to force-refresh.

### Recommended GUI workflow

1. Click the environment popover in the header to verify all external dependencies are available
2. **分析工作台** — validate input file formats, apply a primer preset, preview commands in dry-run mode, then execute each step in order
3. **结果总览** — review primer rankings, scores, and status breakdowns
4. **报告与下载** — read the final evaluation report and obipcr report, download as needed

## 迁移到 Linux / 公司内部服务器（venv 可选方案）

以下步骤适用于将 fullpcr 部署到一台干净的 Linux 服务器（如 Ubuntu 22.04/24.04、CentOS Stream 9、Rocky Linux 9）。

新部署优先使用 [DEPLOYMENT.md](DEPLOYMENT.md) 中的固定版本 Conda/Mamba 方案。本节保留 `venv + systemd` 作为公司服务器的可选方案。

### 环境要求

- **Python** >= 3.10，且必须能够创建带 pip 的虚拟环境（`python3 -m venv` 需包含 ensurepip 模块）。
  - Debian/Ubuntu 系统可能需要管理员预先安装 `python3-venv` 软件包。
  - 其他发行版请使用对应的 Python 虚拟环境支持包，确保 `python3 -m venv` 可正常创建含 pip 的环境。
- **obipcr** 和 **mfeprimer** 已安装并在 PATH 中可用
- 运行用户对数据目录有读写权限

### 部署步骤

```bash
# 1. 创建虚拟环境
python3 -m venv fullpcr-venv
source fullpcr-venv/bin/activate

# 2. 以非 editable 方式安装 fullpcr（包含 GUI 可选依赖）
cd fullpcr
pip install ".[gui]"

# 3. 创建数据目录（必须对运行用户可写）
mkdir -p /srv/fullpcr/data

# 4. 启动 GUI
python -m fullpcr gui \
  --host 0.0.0.0 \
  --port 8501 \
  --data-dir /srv/fullpcr/data
```

### 参数说明

- `--host 0.0.0.0` — 允许内网其他设备访问。仅在可信内网中使用。
- `--port 8501` — Streamlit 默认端口，按需修改。
- `--data-dir /srv/fullpcr/data` — 保存上传文件和每次分析运行结果的持久化目录。目录不存在时自动创建。

### 迁移数据目录

新旧服务器的数据目录绝对路径可以不同。迁移步骤：

1. 在运行 fullpcr GUI 的终端按 **Ctrl+C** 停止服务。
2. 等待启动命令结束并返回 shell 提示符，确认服务已经退出。
3. 将整个数据目录复制到新服务器：

```bash
rsync -av /srv/fullpcr/data/ new-server:/new/path/fullpcr/data/
```

4. 复制完成后，将新服务器的启动参数或环境变量更新为新路径：
   - CLI 参数：`--data-dir /new/path/fullpcr/data`
   - 或环境变量：`FULLPCR_DATA_DIR=/new/path/fullpcr/data`
5. 确认新目录归实际运行用户所有或至少可读写。
6. 启动新服务。
7. 迁移后验证历史 run 目录和文件完整性（参考下方验收清单）。

> 如果公司服务器使用自己的服务管理平台，请使用公司批准的方式停机和启动。

### 网络安全警告

- 当前版本**无内置登录认证和 TLS 加密**。
- 仅在可信内网中绑定 `0.0.0.0`。
- 如需跨网段访问，应在反向代理（nginx、Caddy）后绑定 `127.0.0.1`，由反向代理提供 HTTPS 和身份认证。
- **禁止**直接暴露到公网或配置路由器端口转发。

## 使用 systemd 后台运行（可选）

手工启动（`python -m fullpcr gui`）仍然有效，systemd 方式适合让服务在后台长期运行、失败后自动重启、开机自启。

以下命令必须在目标 Linux 服务器上由管理员执行，不要在当前开发机器上运行。

### 1. 创建 fullpcr 系统用户

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin fullpcr
```

### 2. 安装项目到 /opt/fullpcr

`/path/to/fullpcr` 是管理员提前上传或克隆到服务器的源码目录。

```bash
# 创建 root 管理的安装目录
sudo install -d -o root -g root -m 0755 /opt/fullpcr

# 创建虚拟环境，从源码目录进行非 editable 安装
sudo python3 -m venv /opt/fullpcr/.venv
sudo /opt/fullpcr/.venv/bin/pip install "/path/to/fullpcr[gui]"
```

### 3. 创建数据目录

```bash
sudo mkdir -p /srv/fullpcr/data
sudo chown fullpcr:fullpcr /srv/fullpcr/data
```

### 4. 配置环境变量

```bash
sudo mkdir -p /etc/fullpcr
sudo cp /path/to/fullpcr/deploy/systemd/fullpcr.env.example /etc/fullpcr/fullpcr.env
sudo chown root:fullpcr /etc/fullpcr/fullpcr.env
sudo chmod 640 /etc/fullpcr/fullpcr.env
```

编辑 `/etc/fullpcr/fullpcr.env`，按实际安装位置调整：

- `FULLPCR_HOST` — 默认 `127.0.0.1`，适合在反向代理后运行。仅在可信内网直连时改为 `0.0.0.0`。
- `PATH` — 确认 `.venv/bin` 路径正确，并包含 `obipcr` 和 `mfeprimer` 所在目录。

### 5. 安装并启用服务

```bash
sudo cp /path/to/fullpcr/deploy/systemd/fullpcr.service /etc/systemd/system/fullpcr.service
sudo systemctl daemon-reload
sudo systemctl enable --now fullpcr
```

### 6. 日常管理

```bash
sudo systemctl status fullpcr          # 查看运行状态
sudo journalctl -u fullpcr -f          # 实时日志
sudo systemctl stop fullpcr            # 停止服务
sudo systemctl restart fullpcr         # 修改 env 后重启生效
```

### 重要安全提示

- 当前服务**没有登录认证和 TLS 加密**。
- 默认 `127.0.0.1` 仅本机可访问，适合在反向代理后运行。
- 仅在可信内网且无反向代理时改为 `0.0.0.0`。
- **禁止**直接暴露到公网。
- `obipcr` 和 `mfeprimer` 必须能被 `fullpcr` 服务用户通过 `PATH` 找到。

### 部署后验收清单

部署完成后，按以下步骤验证环境：

**1. 运行环境检查**

```bash
python -c "import fullpcr; print(fullpcr.__file__)"
streamlit version
command -v obipcr && obipcr --version
command -v mfeprimer && mfeprimer version
```

**2. 数据目录**

- 路径存在且为目录。
- 运行用户可读写。
- `FULLPCR_DATA_DIR` 或 `--data-dir` 指向正确路径。

**3. HTTP 检查**

```bash
# 健康检查
curl http://127.0.0.1:<port>/_stcore/health
# 预期输出: ok

# 首页
curl -o /dev/null -w "%{http_code}" http://127.0.0.1:<port>/
# 预期输出: 200
```

**4. 安全检查**

- 默认绑定 `127.0.0.1`（非 `0.0.0.0`）。
- 仅在可信内网直连且无反向代理时使用 `0.0.0.0`。
- 未暴露到公网。
- 当前版本无内置认证和 TLS，禁止公网直连。

**5. 外部工具可用性**

| 工具 | 验收 |
|------|------|
| obipcr | 已在 PATH 且可执行 |
| mfeprimer | 已在 PATH 且可执行 |

> **重要**：health 检查返回 `ok` 只证明 Web 服务正常。只有 obipcr 和 mfeprimer 均可用并完成一次真实完整的五步分析后，才能确认完整分析环境可用。

## 已知限制

1. **In silico PCR 不能替代真实 PCR**。生物样本中的引物表现可能因 DNA 质量、抑制剂、退火条件等而不同。最终引物选择需要 wet-lab PCR 和测序验证。
2. **obipcr 与 MFEprimer 使用不同算法**。MFEprimer 基于 k-mer 索引和打分模型，obipcr 基于字符串匹配。两者结果可能不完全一致（如 16S_short 在 MFEprimer spec 中预测 85 条扩增，但 obipcr 实际仅扩增 2 条）。
3. **数据库完整性直接影响结论**。参考数据库的物种覆盖范围决定了覆盖率和特异性估计的上限——数据库缺失某个类群，则该类群永远不会被任何引物"覆盖"。
4. **Taxonomy 完整性影响物种统计**。缺失分类信息的序列可能导致物种分辨率被低估。
5. **Metabarcoding 引物扩增多个物种不是非特异性**。通用引物的设计目标就是跨物种扩增，这不应被标记为"非特异性结合"。
6. **并行执行未实现**：`--jobs` 参数已预留，但当前仅支持串行执行。
7. **中断恢复**：`--resume` 依赖完整的输出文件对，部分完成的 job 不会自动恢复。
8. **失败重试**：失败任务不会自动重试，需手动使用 `--force` 重跑。
9. **obipcr 依赖**：需要 OBITools4 独立安装，fullpcr 不自带 obipcr。
10. **MFEprimer 依赖**：qc-pre、qc-summary、qc-spec 需要 MFEprimer 独立安装。
