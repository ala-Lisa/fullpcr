# fullpcr 部署手册（v0.1.0）

本文用于在新的 Linux 服务器或 WSL 环境中复现经过验证的 fullpcr 运行环境。推荐使用 Conda/Mamba；`venv + systemd` 作为公司服务器的可选长期运行方式。

## 1. 支持范围与前置条件

- Linux x86_64 或 Linux aarch64/arm64；WSL2 可用于本机或内网测试。
- 已安装 Git、`curl`、`gzip`、`sha256sum` 和 Conda/Mamba（推荐 Miniforge）。
- 服务器能访问 GitHub、conda-forge 和 Bioconda，或已配置公司批准的镜像。
- 运行用户对持久化数据目录有读写权限。
- 本版本没有内置登录认证和 TLS；只能在可信内网使用，禁止直接暴露到公网。

## 2. 已验证版本矩阵

以下是 `v0.1.0` 的参考环境，不代表任意更高版本都兼容：

| 组件 | 已验证版本 | 要求 |
|---|---:|---|
| fullpcr | 0.1.0 / Git tag `v0.1.0` | 部署不可变标签，不直接部署持续变化的分支 |
| Python | 3.13.14 | 推荐精确版本；项目元数据最低要求仍为 Python 3.10 |
| OBITools4 | 4.4.46 | 推荐通过 Bioconda 固定版本安装 |
| MFEprimer | 4.2.4 | 当前索引和 TSV 解析契约要求精确版本 |
| Streamlit | 1.59.1 | 参考 GUI 版本 |
| pandas | 3.0.3 | 参考数据处理版本 |

> **不要在 `v0.1.0` 使用 MFEprimer 4.3.1。** 4.3.1 会生成 `.primerqc.bin`，并在 Spec TSV 中增加字段；当前版本尚未适配这些格式变化。环境显示正常只代表程序可执行，不代表五步分析兼容。

## 3. 推荐安装：Conda/Mamba

### 3.1 获取固定版本源码

```bash
git clone https://github.com/ala-Lisa/fullpcr.git
cd fullpcr
git checkout v0.1.0
git status --short
```

`git status --short` 应无输出。公司使用内部 Git 镜像时可以替换 clone URL，但必须检出同一个 `v0.1.0` 标签。

### 3.2 创建环境并安装 OBITools4

使用 Mamba：

```bash
mamba create -n fullpcr \
  -c conda-forge -c bioconda \
  python=3.13.14 obitools4=4.4.46 pip -y
conda activate fullpcr
```

只有 Conda 时，将第一条命令中的 `mamba` 换成 `conda`。

### 3.3 安装并校验 MFEprimer 4.2.4

下面的命令根据 CPU 架构选择官方二进制，并在安装前校验 SHA256：

```bash
case "$(uname -m)" in
  x86_64)
    MFE_ASSET="mfeprimer-4.2.4-linux-amd64.gz"
    MFE_SHA256="533ea292958ecb0d638dc4c34f664f6e8314e1e12dca2e323b3d6ae0f69968c0"
    ;;
  aarch64|arm64)
    MFE_ASSET="mfeprimer-4.2.4-linux-arm64.gz"
    MFE_SHA256="b4c7f42b1241869e98aa954215bf06e097d4e0f9dc84a47c8e2d21e27bd87517"
    ;;
  *)
    echo "不支持的 CPU 架构: $(uname -m)" >&2
    exit 1
    ;;
esac

curl -fL \
  "https://github.com/quwubin/MFEprimer-3.0/releases/download/v4.2.4/${MFE_ASSET}" \
  -o "/tmp/${MFE_ASSET}"
echo "${MFE_SHA256}  /tmp/${MFE_ASSET}" | sha256sum -c -
gzip -dc "/tmp/${MFE_ASSET}" > "${CONDA_PREFIX}/bin/mfeprimer"
chmod 0755 "${CONDA_PREFIX}/bin/mfeprimer"
mfeprimer version
```

最后一条命令必须显示 `mfeprimer v4.2.4`。如果校验失败，不要继续安装；删除下载文件并检查镜像或网络来源。

### 3.4 安装 Python 组件和 fullpcr

在仓库根目录执行：

```bash
python -m pip install "streamlit==1.59.1" "pandas==3.0.3"
python -m pip install --no-deps .
```

生产部署使用非 editable 安装。开发人员如需修改源码，可在独立开发环境使用 `pip install -e ".[dev,gui]"`，不要与生产服务环境混用。

### 3.5 环境验收

```bash
which python
python --version
python -c 'from importlib.metadata import version; print("fullpcr", version("fullpcr")); print("streamlit", version("streamlit")); print("pandas", version("pandas"))'
which obipcr
obipcr --version
which mfeprimer
mfeprimer version
```

应分别看到 Python 3.13.14、fullpcr 0.1.0、Streamlit 1.59.1、pandas 3.0.3、OBITools 4.4.46 和 MFEprimer 4.2.4。`which` 输出应指向同一个 `fullpcr` Conda 环境。

## 4. 数据目录与启动

### 4.1 本机访问

```bash
mkdir -p "$HOME/fullpcr-data"
python -m fullpcr gui \
  --host 127.0.0.1 \
  --port 8501 \
  --data-dir "$HOME/fullpcr-data"
```

浏览器打开 <http://127.0.0.1:8501>。

### 4.2 可信局域网访问

```bash
python -m fullpcr gui \
  --host 0.0.0.0 \
  --port 8501 \
  --data-dir "$HOME/fullpcr-data"
```

同一局域网的电脑访问 `http://<服务器真实 LAN IP>:8501`。`0.0.0.0` 只是监听地址，不是浏览器 URL。还需要在服务器防火墙中允许 TCP 8501，并确认 WiFi 没有 AP/client isolation。WSL2 NAT 下，局域网设备通常不能直接访问 WSL 内部的 172.x 地址；应使用 Windows 主机 LAN IP，并按公司策略配置 mirrored networking 或端口转发。

也可使用环境变量固定数据目录：

```bash
export FULLPCR_DATA_DIR="$HOME/fullpcr-data"
python -m fullpcr gui --host 127.0.0.1 --port 8501
```

每次启动必须指向同一持久化目录，否则历史项目看起来会“消失”。

## 5. 三层验收

### 5.1 环境验收

先执行第 3.5 节的所有版本命令。GUI 的“环境正常”只证明依赖可以找到，不能替代版本核对。

### 5.2 Web 验收

服务启动后，在另一终端执行：

```bash
curl -fsS http://127.0.0.1:8501/_stcore/health
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8501/
```

预期分别输出 `ok` 和 `200`。

### 5.3 完整分析验收

使用小型、已知有效的 `primers.tsv`、FASTA 数据库和 `taxonomy.tsv` 完成一次真实五步分析。必须同时确认：

1. 基础质控、质控汇总、特异性分析、obipcr 和最终报告全部成功；
2. “结果总览”能加载排名；
3. “报告与下载”能加载中文报告并生成所选结果 ZIP；
4. 数据目录中存在本次 run 及 `final_results/final_report.md`。

Web health 成功但特异性分析失败时，优先检查 `which mfeprimer`、`mfeprimer version` 和 GUI 原始报错弹窗。

## 6. 输入文件最小格式

- `primers.tsv`：制表符分隔，字段为 `primer_id`、`forward`、`reverse`、`min_length`、`max_length`；GUI 直接填写时会自动生成。
- 参考数据库：`.fasta` 或 `.fa`；本地上传还接受 `.fasta.gz`/`.fa.gz` 并自动解压。FASTA 记录 ID 必须唯一。
- `taxonomy.tsv`：必须包含 `taxid`；推荐同时提供 `scientific_name kingdom phylum class order family genus species`（制表符分隔），以获得完整的分类与物种分辨率统计。数据库序列的 taxid 或名称应能与该表匹配。

输入格式不正确时先使用 GUI 的“保存并验证输入文件”，不要直接运行完整分析。

## 7. venv 与 systemd（可选）

仓库提供：

- `deploy/systemd/fullpcr.service`
- `deploy/systemd/fullpcr.env.example`

venv 仅安装 Python 应用；`obipcr` 和 `mfeprimer` 仍需独立安装并出现在服务用户的 `PATH` 中。详细的 venv/systemd 安装步骤保留在 [README](README.md#使用-systemd-后台运行可选)。

Conda 环境用于 systemd 时，不要在 unit 中依赖交互式 `conda activate`。应让 `/etc/fullpcr/fullpcr.env` 的 `PATH` 以实际环境的 `bin` 开头，例如：

```ini
PATH=/opt/conda/envs/fullpcr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/bin
FULLPCR_DATA_DIR=/srv/fullpcr/data
```

同时保证：

- `fullpcr` 服务用户能读取 Conda 环境和源码工作目录；
- 能写 `/srv/fullpcr/data`；
- `sudo -u fullpcr env PATH=... obipcr --version` 和 `mfeprimer version` 均成功；
- 修改 env 后执行 `sudo systemctl restart fullpcr`。

systemd 显示 active 仍不等于分析环境已验收，必须再完成第 5 节。

## 8. 数据迁移、升级与回滚

### 8.1 迁移数据

1. 停止 GUI，等待启动命令返回 shell 提示符。
2. 复制完整数据目录；新旧服务器绝对路径可以不同：

```bash
rsync -av /old/path/fullpcr-data/ new-server:/new/path/fullpcr-data/
```

3. 在新服务器用 `--data-dir /new/path/fullpcr-data` 或 `FULLPCR_DATA_DIR=/new/path/fullpcr-data` 启动。
4. 核对目录所有权、历史项目数量和下载文件。

### 8.2 升级

升级前备份数据目录，并为新版本创建新环境，不要原地覆盖已验证环境：

```bash
git fetch --tags
git checkout <new-release-tag>
```

然后按新版本部署手册重新创建环境并完成三层验收。只有验收通过后才切换长期服务。

### 8.3 回滚

停止新服务，重新启用保留的 `v0.1.0` 环境和源码，并继续指向原持久化数据目录。不要删除失败升级产生的 run，先保留用于诊断。

## 9. 常见故障

### 环境显示正常，但 Spec 失败

```bash
which python
which mfeprimer
mfeprimer version
python -c 'from importlib.metadata import version; print(version("fullpcr"))'
```

确认不是 MFEprimer 4.3.1，且 fullpcr 与 MFEprimer 来自预期环境。复制 GUI 原始报错，检查其中的命令、return code、stdout 和 stderr。

### 服务在终端可用，systemd 不可用

检查服务用户、工作目录和 PATH：

```bash
sudo systemctl status fullpcr
sudo journalctl -u fullpcr -n 200 --no-pager
sudo -u fullpcr /usr/bin/env which python obipcr mfeprimer
```

### 历史项目不见了

核对本次启动的 `--data-dir` 或 `FULLPCR_DATA_DIR` 是否与上次一致，并检查运行用户权限。不要在多个服务实例之间共享同一 run 目录进行同时写入。

### 局域网打不开

依次检查监听地址、真实 LAN IP、防火墙、WSL 网络模式和 WiFi 隔离：

```bash
ss -ltnp | grep 8501
hostname -I
curl -fsS http://127.0.0.1:8501/_stcore/health
```

### 任务长时间运行

大数据库的 Spec 和 obipcr 可能耗时较长。GUI 会持续记录进度和运行时间；先观察 CPU、内存和原始错误信息，不要因页面 rerun 重复提交同一任务。确认卡死后再使用 UI 的终止功能。

## 10. 安全边界

- 当前版本没有登录认证和 TLS 加密。
- 只允许在可信内网中使用 `0.0.0.0`。
- 禁止路由器端口转发或直接公网暴露。
- 跨网络部署应绑定 `127.0.0.1`，并由公司批准的反向代理提供 HTTPS、身份认证和访问控制。
- 数据目录可能包含用户上传的序列和分析结果；应按公司数据分级、备份和访问控制策略管理。
