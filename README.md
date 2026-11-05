# LLM 服务工程

基于 SGLang 的模型网关与多用户实验账本。服务合同 `llm-lab/1.0`，管理合同 `credential-service/1`，任务书评分版本 `llm-lab/5.0`。

需求映射、初始仓库审计和分阶段计划见 [实施计划](docs/implementation-plan.md)；每阶段的真实命令、结果与限制见 [测试记录](docs/test-records.md)。源码底座和固定提交见 [SOURCES.md](SOURCES.md)。参考仓库成绩没有导入本项目。

CPU阶段已在GitHub通过18项软诊断与工程测试，最新源码本地139项；真实浏览器13项核心流程、两个实际SIGKILL恢复窗口通过。Daytona RTX4090练习自测已取得完整768请求矩阵、双用户真实Agent/计费/轮换、20次取消以及KV/Prefix/Attention数据；本机重算与三机制证据检查通过。optimized四个冻结目标组中三个通过，long/C16因正确率47/48低于99%未通过；short/C4也有一条输出错误。详见[GPU复核](results/gpu/daytona/review-20261105/README.md)。未发起正式GPU评测，不声明整体达标。

## CPU 开发与软评测

使用 Python 3.12（默认解释器不同可指定路径），不需要 GPU：

```bash
python3.12 -m venv .venv-test
.venv-test/bin/python -m pip install -r requirements.lock -r requirements-dev.lock
.venv-test/bin/python -m pytest -q
.venv-test/bin/python scripts/local_cpu.py --out results/cpu/my-run-01
```

`local_cpu.py` 为本地开发复现：用一次性凭据、临时 DATA_DIR、独立 CPU fixture 启动真实网关，依次运行公开 18 项 HTTP checker、管理 HTTP 自测、两个实际 SIGKILL 恢复窗口，最后停止自有进程。它不会运行仅允许在 GitHub runner 执行的官方 `soft_runner.py`，不会冒充 GitHub 环境或申请 GPU。与已有服务不能同时使用项目 `.runtime/`。

`.github/workflows/llm-soft.yml` 是任务书提供的官方 CPU 软诊断，push 与手动触发均固定完整 commit SHA，在 GitHub 托管 runner 执行，artifact 为 `llm-soft-report`。无须配置任何生产或平台 secrets。`cpu-tests.yml` 另外运行工程测试，两者都不产生官方分数。工作流需推到默认分支后手动入口才可用。

## 正式评测的 setup.sh 启动合同

正式评测由平台提供固定 Daytona Linux 基础快照、RTX 4090、驱动、Python、Git 与依赖/模型下载缓存；快照不包含本项目。评测系统 clone 整个仓库、切到指定完整 SHA，并以根目录 `setup.sh` 作为唯一服务启动入口：

```bash
export GIT_TERMINAL_PROMPT=0
git clone https://github.com/ThingsWorld/llm-service.git
cd llm-service
git checkout --detach <40-character-commit-sha>
bash setup.sh
```

平台同时注入任务书规定的 `HOST`、`PORT`、`API_KEY`、`MODEL_ID`、`MODEL_REVISION`、`BENCH_PROFILE`、`HF_HOME`，以及管理合同的 `ADMIN_API_KEY`、`KEY_HASH_SECRET`、`DATA_DIR`。正式流程直接读取这些变量，不要求预先创建 `.env`、配置 SSH 别名、手动安装 Python 包或另跑部署脚本。

`setup.sh` 内部调用 `scripts/native_setup.py`，从脚本目录工作，建立私有 `.venv`，安装锁定依赖并核对版本，检查实际 CUDA 运算，然后由 `server/supervisor.py` 启动 SGLang 和网关。SGLang 按指定模型/revision 使用 `HF_HOME` 缓存或下载；只有模型与引擎已就绪、`/healthz` 返回200，setup 才成功退出。安装或启动失败返回非零，保留日志。它不依赖 Docker daemon 或 systemd，不修改 GPU 驱动。

首次需要的本地编译头文件/工具也由 setup 检查；缺失时尝试通过现有 Ubuntu 源非交互安装，权限或安装失败则明确失败。默认路径自行安装声明的运行时；`SGLANG_PYTHON` 仅用于显式复用并校验已有运行时，不是必填的手工准备步骤。缓存命中与干净下载分开记录。GPU干净重建仍待实际验证，CPU编排测试不能证明GPU部署已通过。

setup 同配置重跑幂等，切换 profile 只停止自己拥有的进程组（验证 PID 启动时间），有界等待就绪；日志位于被忽略的 `.runtime/`。`--contract-test` 仅连接外部 `ENGINE_BASE_URL`，只安装 CPU 网关依赖，其他真实鉴权、账本、限流与恢复实现一致。实际监听 PID 为 `$DATA_DIR/gateway.pid`；`--stop` 不删除 DATA_DIR 或停止外部 fixture。

服务固定 `Qwen/Qwen2.5-7B-Instruct` revision `a09a35458c702b33eeacc393d103063234e8bc28`，BF16。baseline：running=1、KV=8192、Triton、prefix off、CUDA Graph off；optimized：running=32、KV=16384、FlashInfer、prefix on、CUDA Graph on。网关两组均 32 slots、64 queue，入引擎后由 SGLang 连续批处理，不在网关凑批。`/info` 报告实际 profile/config/version，CPU 模式明确 `mode=contract-test`，不能证明 GPU 已部署。

## 已申请练习机上的自测

练习机需要通过平台终端或 SSH 进入。SSH Host 别名只用于本机连接管理，不属于正式评测的交付要求。在练习机自行运行时，可把 `.env.example` 复制为被忽略的 `.env`，设置本服务的私密凭据、实际缓存和数据路径，再 `set -a; source .env; set +a` 导出环境；`KEY_HASH_SECRET` 与 `DATA_DIR` 重跑保持相同。服务启动仍执行 `bash setup.sh`。

`scripts/gpu_validate.sh` 是可选的练习自测编排，内部也通过 setup 启动服务；它不能取代上述正式入口。正式评测由平台在 setup 成功后运行自己的接口、性能、Agent和机制检查。

自建的公司RTX 4090服务器也可用于开发、自测和优化。当前安装路径面向Linux x86_64/Python 3.12，系统须有可用的NVIDIA驱动，并能访问或已缓存锁定依赖及指定模型。缺少编译头文件/工具时，自动补齐路径按Ubuntu源编写；其他Linux发行版需先核实已有工具链兼容性。`setup.sh` 本身不调用Daytona API。

公司服务器不会由评测平台自动注入变量：在该机私密配置 `.env` 中的三个服务凭据、DATA_DIR及实际HF_HOME，导出环境后运行同一个 `bash setup.sh`。可选自测明确标记来源：

```bash
set -a
source .env
set +a
bash setup.sh
LLM_TEST_ENVIRONMENT=self-managed bash scripts/gpu_validate.sh smoke
```

其他自测阶段同样设置 `LLM_TEST_ENVIRONMENT=self-managed`。Daytona练习机填 `daytona`；未指定则记录为 `unspecified`，不推断机器归属。自测结果保存到 `results/gpu/<环境>/<时间>-<阶段>/`，context.json记录实际GPU、代码SHA、模型及来源；机制manifest也保留该标签。公司机器结果属于真实GPU自测，可用于发现错误和比较优化，官方分数及Daytona固定快照的重建/性能验收仍由平台正式运行决定。

## 接口、鉴权与实验账本

- `/healthz` 公开；`/console` 只公开没有数据的登录壳。其余接口要求 Bearer。管理员凭据只用于 `/admin/*`；普通 key 可用 `/info`、`/metrics`、`/v1/models`、`/v1/chat/completions`、`/v1/usage`、`/agent/run`。
- 完整管理路由见 [任务书](agentist-llm-project-taskbook.md)。`/console` 连接真实 API，提供用户、余额/额度、key 创建/轮换/撤销、价格、账单和审计。凭据仅在页面内存，不用 cookie/localStorage，响应不缓存。新 key 仅返回一次，数据库保存 HMAC-SHA256 摘要。
- `API_KEY` 初始化普通 benchmark 用户，计费/限流不豁免。零宽限轮换在一个事务里撤销旧 key 并签发新 key；已获准请求按原 tenant/key 归属完成；新请求立即重新鉴权。用户跨 key 共享 RPM、并发、累计 token 与余额。
- 金额为整数 micro-USD（实验单价，非真实收款）：输入 2、输出 6 每 token，100 输入/50 输出费用为 500。按固定 tokenizer 的 chat-template 输入与 max_tokens 原子预占，可信引擎 usage 恰好结算一次，保存不可变价格版本；cached_tokens 单独保存，不免除输入费。
- `Idempotency-Key` 按租户/路由/请求体哈希去重；重复生成返回 409 与原 request_id，冲突体也 409。充值重复相同请求只入账一次。不能用 user_id、usage 或 cost 覆盖账单。
- 未取得可信完整 usage 的取消/崩溃账目保持 null，先待对账；恢复时已 journal 的 usage 结算一次，未知则以 credit_adjustment 审计释放预占并标 `adjusted_unknown`，不伪造 0 token。SQLite WAL/事务，单数据库只允许一个网关 worker。
- SSE 从上游逐事件转发，始终在内部请求 usage；完整 finish/usage/DONE 才成功。响应头发出后的错误为流内 error，不伪造 DONE；取消使用同 rid 传给引擎。SSE 事件数与间隔不是 token 数或精确 ITL。
- `/metrics` 的 active/queued 是当前网关值；counters 从进程启动起累计，重启归零。complete、failed、cancelled、timeout、stream_error、abort_acknowledged/failed 表示对应事件；账本持久化不随指标重置。取消确认不等于独立证明 GPU 计算已停止，须结合 GPU 实测。

公开管理 HTTP 自测只连接自己的服务，凭据从环境读取：

```bash
.venv-test/bin/python scripts/check_control_plane.py --base-url http://127.0.0.1:8000 --suite mock --out results/control-plane-mock.json
.venv/bin/python scripts/check_control_plane.py --base-url http://127.0.0.1:8000 --suite live --out results/control-plane-live.json
```

mock 需先运行隔离 contract 服务和受控 fixture（`local_cpu.py` 自动编排）；只做 HTTP，磁盘扫描和 SIGKILL 在外部测试中独立验证，skipped 明确列出。live 需已有真实 GPU 服务，验证双用户流式、非流式及真实 Agent 父子账本。Agent 通过同网关的内部推理通道执行规划→lookup_order 白名单→模型回答，父账零费用，两次子调用各自鉴权归属与计费。

## 模块与实验

`server/backend.py` 对应任务书 engine.py；`control_plane/storage.py` 集中实现 keys/billing/quotas/usage/storage，`meter.py` 做可信计数、恢复与数据库所有权，`api.py` 做管理入口；其余路径按 [需求对应表](docs/implementation-plan.md)。

`experiments/run.sh --case kv|prefix|attention --out results/<new-run>` 是固定入口；内部 `kv_cache.py`、`prefix_cache.py`、`flash_attention.py` 分别对应任务书 kv.py、prefix.py、attention.py。实验会显式停止自己的服务以独占 GPU；结束后重新运行 setup。KV 用固定 1.5B FP32，Prefix 用服务 7B BF16，Attention 只用合成张量。不得混写模型或精度，也不能把 PyTorch FlashAttention 与服务 FlashInfer 当成同一实现。

性能方法、冻结阈值与实际结果见 [docs/performance.md](docs/performance.md)。每次输出用新目录，保留失败行、原始数据和完整源码SHA；当前GPU数据对应 `1cbc12e510e2b8c7daa49ae6b8944e9baff99db3`，后续归档提交不会改写这个来源。正式 GPU 评测需用户主动提交已 push 的完整 40 位 SHA；push 只触发 CPU 工作流。

在已申请的练习GPU上设置好私密环境变量后，可选运行 `bash scripts/gpu_validate.sh smoke`（setup部署、幂等、live、取消）、`bench`（完整服务矩阵）、`experiments`（三个机制实验）。这些自测命令实际消耗已有 GPU 的运行时间，先核实平台剩余时间；正式评测不要求手动执行它们。KV 入口显式选择任务书的固定1.5B FP32实验模型，支持从已有7B服务环境直接调用；任意错误模型/revision仍在停止服务前拒绝。实验结束后显式 setup 恢复服务。

taskbook 指定的公开测量客户端使用 Transformers 4.51.3 / tokenizers 0.21.4，与 SGLang 的锁定运行时 4.57.1 分开安装，防止互相升级：

```bash
python3.12 -m venv .venv-benchmark
.venv-benchmark/bin/python -m pip install -r requirements-benchmark.lock
export BENCH_PYTHON="$PWD/.venv-benchmark/bin/python"
python3 scripts/fetch_public_tools.py --out .cache/my-new-public-tools
```

fetch 只下载和校验9份公开工具，不启动模型。`bench` 也会重新刷新到一个新目录并保存该批 manifest/acceptance。`python -m experiments.verify_evidence --case kv --directory results/<run>/kv --commit <完整SHA>` 检查本次文件矩阵、输入一致、数值门槛与机制字段；验证器不能证明自报 GPU 身份或产生官方成绩。

练习结果可打包取回本机后提交Git，无需在GPU服务器配置Git写权限。确认本机压缩包完整、所需结果已保存后，在远端项目目录执行 `bash setup.sh --stop`，再通过平台销毁练习服务器；退出SSH或只停止服务不会销毁实例。`.env`、私密账本和模型权重不属于结果包。
