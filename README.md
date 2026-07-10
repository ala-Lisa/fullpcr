# fullpcr

Batch in silico PCR analysis tool using OBITools4 `obipcr` + MFEprimer QC.

## 目标

用 Python 批量调用 `obipcr`，解析结果，统计覆盖率、非目标扩增和物种分辨率，结合 MFEprimer 热力学和特异性分析，生成统一引物评价报告。

不重写 OBITools4，不改动 OBITools4 源码。

## 依赖

- **Python** >= 3.10
- **OBITools4** — `obipcr` 必须在 PATH 中可用
- **MFEprimer** — `mfeprimer` v4.2.4 或兼容版本必须在 PATH 中可用，用于 thermo、dimer、hairpin、degen 和 spec

### 安装 OBITools4

```bash
mamba create -n obitools4 -c conda-forge -c bioconda obitools4 -y
conda activate obitools4
obipcr --help
```

### 安装 MFEprimer

```bash
# 安装后验证
mfeprimer -h
mfeprimer version
```

### 安装 fullpcr

```bash
cd fullpcr
pip install -e ".[dev]"
```

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
