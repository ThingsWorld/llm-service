# LLM 服务工程

基于 SGLang 的模型网关与多用户实验账本。服务合同 `llm-lab/1.0`，管理合同 `credential-service/1`，任务书评分版本 `llm-lab/5.0`。

需求映射、初始仓库审计和分阶段计划见 [实施计划](docs/implementation-plan.md)；每阶段的真实命令、结果与限制见 [测试记录](docs/test-records.md)。源码底座和固定提交见 [SOURCES.md](SOURCES.md)。参考仓库成绩没有导入本项目。

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

## Daytona 一键部署

仅连接本人已申请的 GPU；本项目代码不申请机器。使用私密环境文件或 shell 设置凭据，不把临时 SSH 命令或 key 放进 Git。可先复制 `.env.example` 到被忽略的 `.env`，替换三个凭据占位值，并在终端导出变量。`KEY_HASH_SECRET` 重启必须保持相同。

```bash
set -a
source .env
set +a
bash setup.sh
BENCH_PROFILE=optimized bash setup.sh
curl --fail http://127.0.0.1:8000/healthz
bash setup.sh --stop
```

GPU 前提为 Linux x86_64、Python 3.12、RTX 4090 驱动和编译工具。setup 不使用 Docker/systemd，不安装宿主驱动；默认建立私有 `.venv` 并按完整 native lock 安装，检查真实 CUDA 运算后启动指定 revision 的 SGLang。缓存命中与干净下载分开记录。`SGLANG_PYTHON` 可显式选择已有固定版本运行时，必须记录该区别。

setup 同配置重跑幂等，切换 profile 只停止自己拥有的进程组（验证 PID 启动时间），有界等待就绪；日志位于被忽略的 `.runtime/`。`--contract-test` 仅连接外部 `ENGINE_BASE_URL`，只安装 CPU 网关依赖，其他真实鉴权、账本、限流与恢复实现一致。实际监听 PID 为 `$DATA_DIR/gateway.pid`；`--stop` 不删除 DATA_DIR 或停止外部 fixture。

服务固定 `Qwen/Qwen2.5-7B-Instruct` revision `a09a35458c702b33eeacc393d103063234e8bc28`，BF16。baseline：running=1、KV=8192、Triton、prefix off、CUDA Graph off；optimized：running=32、KV=16384、FlashInfer、prefix on、CUDA Graph on。网关两组均 32 slots、64 queue，入引擎后由 SGLang 连续批处理，不在网关凑批。`/info` 报告实际 profile/config/version，CPU 模式明确 `mode=contract-test`，不能证明 GPU 已部署。

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

性能方法、冻结阈值与未验证项见 [docs/performance.md](docs/performance.md)。当前本仓库没有真实 GPU 性能/机制实验结果，不声明达标。每次输出用新目录，保留失败行、原始数据和完整 SHA。正式 GPU 评测需用户主动提交已 push 的完整 40 位 SHA；push 只触发 CPU 工作流。
