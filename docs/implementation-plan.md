# 实施计划与需求追踪

任务书：根目录 `agentist-llm-project-taskbook.md`，共 3660 行，四部分均已阅读；重复正文逐段核对，完整验收 JSON 已解析核对。审计日期：2026-11-03。

## 初始仓库核对

- 分支：main；origin：`https://github.com/ThingsWorld/llm-service.git`。
- 初始提交：`049f423d14d2592f029725ea48fe7ef2c028227d`。
- 已跟踪文件只有 README；任务书及其 Windows Zone.Identifier 未跟踪。尚无 setup、工作流、服务或测试。
- 未发现适用的 AGENTS.md。当前 shell 默认 Python 3.14；本机已有 Python 3.12 环境，CPU 测试须选用兼容解释器。
- 当前无 gh CLI、Daytona 环境变量或 SSH Host 配置；不申请新 GPU，后续只连接用户申请的资源。

## 固定合同与证据边界

- 服务 `llm-lab/1.0`，管理 `credential-service/1`，评分 `llm-lab/5.0`，自动 95 + 人工 5。
- 服务与 Prefix：Qwen/Qwen2.5-7B-Instruct，revision `a09a35458c702b33eeacc393d103063234e8bc28`，BF16。
- KV 实验：Qwen/Qwen2.5-1.5B-Instruct，revision `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`，FP32，TF32 关闭。
- 验收快照 `daytona-4090-v5-confirmed-5e2971c9`：四组性能阈值已独立确认；没有本项目 GPU 数据时，本项目达标状态仍为未验证。
- 原始 acceptance SHA-256：`d5cd2fdc90056e710cf741ac1eec4c5b042ea3818d505e4a3975697f1df9241f`。64 位 seed 用 Python 整数解析，避免 JS 数值截断。
- CPU 18 项诊断、CPU 15 项独立黑盒、12 个业务自测场景、真实 GPU 部署门槛用途不同，分别报告；本地测试不写官方成绩。
- 文本存在版本遗留：启动次数一处 10 次、一处 3 次，且旧段落仍写 staging/待标定。实际配额及自动评测开放范围以本人平台当前状态为准，标为待确认；性能门槛按顶部生成区块与确认 JSON。
- 未执行、失败、null 阈值、未知 usage 均不写成通过。参考源码和参考结果不是本项目成绩。真实账本、凭据、模型与运行时不进 Git。

## 需求—模块—测试对应表

以下模块是计划交付路径；初始状态全部缺失。内部文件名若与任务书不同，在 README 映射。

| 需求 | 模块 | 验证与证据 | 执行环境 |
|---|---|---|---|
| 官方 CPU 软评测 | `.github/workflows/llm-soft.yml` | 固定 action SHA/工具哈希；18 项 pass/missing/invalid/blocked；artifact 与完整 SHA 关联 | GitHub 托管 CPU runner |
| 隔离安装、锁定版本、健康就绪、幂等与停止 | `setup.sh`, `scripts/native_setup.py`, `server/supervisor.py`, `requirements*.lock` | 从新目录启动、同配置 PID 不变、切换只停自有进程、失败有界；CPU 不安装 CUDA/权重 | CPU + Daytona |
| Bearer、模型、info、健康、错误与 request ID | `server/app.py`, `auth.py`, `config.py` | 未鉴权拒绝；字段/状态码；fixture 和 GPU 模式身份明确 | CPU + GPU |
| 真正 SSE 转发 | `server/backend.py`, `streaming.py` | 信号控制首段先于上游完成；分包/合包/UTF-8；finish/usage/DONE；截断不伪造成功 | CPU 真实 HTTP + GPU |
| 有界 FIFO、执行/排队超时、取消 | `server/admission.py`, `backend.py`, `metrics.py` | 满队列 429 + Retry-After；finally 释放；同 rid abort；恢复请求成功 | CPU + GPU |
| SGLang、连续批处理、配置对照 | `configs/baseline.yaml`, `optimized.yaml`, `server/supervisor.py` | 实际引擎版本、固定模型/精度、sampling_defaults=openai；C=1/4/8/16 两 profile | GPU |
| 多用户鉴权与 Key 生命周期 | `control_plane/storage.py`, `api.py`, `server/auth.py` | Alice/Bob 各两 key；HMAC 摘要/32 随机字节；轮换零宽限；撤销/到期/停用；7 个管理写路由隔离 | CPU + live |
| 不可变价格、精确计费与幂等 | `control_plane/storage.py`, `meter.py`, `configs/pricing.json` | 100/50 → 500 micro-USD；调价 4/8 → 800；20 次重试至多一推理；充值对账 | CPU fixture |
| 用户共享 RPM/并发/token/余额限制 | `control_plane/storage.py`, `meter.py` | 同租户多 key 不绕过；20 请求预占不透支；402/429；其他用户不受误扣 | CPU fixture |
| 崩溃恢复与取消账本 | `control_plane/meter.py`, `storage.py`, `migrations/` | 实际 SIGKILL 两窗口；未知 usage 调整审计与释放；最终 usage journal 后恰好一次结算；≤60s | CPU 真实进程 |
| 实验管理页面与审计 | `console/index.html`, `control_plane/api.py`, `scripts/seed_demo.py` | 真实 API 操作；凭据仅内存；一次性显示 key；幂等迁移；无鉴权只有壳 | CPU + 浏览器 |
| 工具 Agent 与父子账本 | `agent/`, `server/app.py`, `control_plane/meter.py` | 至少规划/最终两模型调用；lookup_order 白名单；父账零费、子账汇总；跨用户/幂等 | CPU 协议 + GPU 真模型 |
| KV Cache | `experiments/run.sh`, `kv_cache.py` | 12 行；128/512 × on/off × 3；32 token 固定回放；逐位置 logits ≤.001、top1=100%；显存与容量 | GPU |
| RadixAttention | `experiments/prefix_cache.py` | 96 行；on/off × shared/unique ×3×8；512 前缀、flush、输入 ID 和实际 cached_tokens | GPU 同服务模型 |
| FlashAttention | `experiments/flash_attention.py` | 18 行；math/flash ×128/512/1024×3；BF16 causal；误差≤.02；6 份 operators 与 trace | GPU 合成 Q/K/V |
| 服务性能与账本开销 | `benchmarks/`, `docs/performance.md` | 768 测量请求；独立 tokenizer；TTFT/TPOT/E2E p50/p95、有效吞吐、goodput、失败分母、图表；同负载开销对照 | GPU |
| 交付与复现 | `README.md`, `docs/`, `results/`, `.gitignore` | 源码—原始数据—完整 SHA 追溯；敏感数据排除；所有未验证项明确列出 | Git + 公开 clone |

## 分阶段实施与退出条件

1. **审计与安装 CPU 工作流**：下载并审阅官方 workflow，保留原始字节与哈希；提取任务书验收快照；完成本表。退出条件：文件和来源可审查，不声称 Actions 已运行。
2. **网关与 18 项软诊断**：以固定公开参考提交为底座，审查并实现 setup CPU 模式、协议、持久化、计费和权限。先本地运行公开 checker 修复，再提交 push，由 GitHub Actions 运行同一 workflow。真实结果按执行环境分别保存。
3. **管理服务与工程可靠性**：运行 1–11 场景、流式不缓冲/异常/取消、配额竞争、两崩溃窗口、幂等重启测试；页面操作连接真实 API。退出条件：失败已修复或明确记录限制；所有原始报告留存。
4. **Daytona 首次真实部署**：只用用户已申请资源；核实 RTX 4090、驱动、剩余时间与缓存；刷新公开工具并校验哈希；baseline/optimized setup、健康、幂等、配置切换、双用户 live 和 Agent/取消验证。
5. **性能与机制实验**：固定模型/负载/seed，两个 profile 完整矩阵；KV、Prefix、Attention 分别真实执行并核对证据矩阵/数值；报告连续批处理、缓存容量、后端和开销，解释负结果。
6. **交付复核**：补全 README、性能报告和原始结果；检查目录、泄漏、git 状态及完整 40 位 SHA；公开可 clone/pushed 证据；正式 GPU 评测仅在用户主动要求正式提交后发起。

每阶段在 `docs/test-records.md` 记原理、命令、环境、真实结果及后续限制。GPU 未就绪期间推进所有独立的 CPU 工作；不将资源缺失写成服务通过。

## 当前进度

- 阶段0完成：审计、来源、精确 acceptance 与官方工作流已落库。
- 阶段1完成过一次精确 SHA 的 GitHub 运行：18/18 软诊断、124/124 工程测试；后续改动重新验证。
- 阶段2：HTTP 管理场景、事务竞争、SSE信号测试、两个实际SIGKILL窗口通过本地测试；管理网页核心流程13项真实浏览器交互通过。真实GPU用量/部署门槛仍未验收。
- 阶段3–4：用户已在Daytona RTX4090练习机执行smoke、bench、experiments，本机已复核返回数据。双用户live/真实Agent/计费/轮换、20次取消与三机制矩阵检查通过；完整768请求中optimized四冻结目标组三组通过，long/C16正确率47/48失败，两profile short/C4也有内容错误，待定位修复及GPU复测。正式洁净快照重建仍由平台clone固定SHA后执行setup，不要求SSH别名。
- 自建公司RTX4090也可作为开发验证环境，来源标为self-managed；公司机器的操作系统/工具链兼容性及实际测试仍待确认。正式评分继续按平台Daytona合同执行。
- 阶段5：GPU原始记录、trace、复核脚本/JSON/CSV/图表已补齐；正式平台结果、内容错误修复、鉴权/账本开销对照及最终整体验收仍未完成。

当前GPU数据精确源码提交为 `1cbc12e510e2b8c7daa49ae6b8944e9baff99db3`，该SHA的GitHub软诊断与工程测试均success。早先精确源码的本地HTTP/真实浏览器/实际崩溃复测、各后续改动与真实GPU结果分别见测试记录，不将旧报告改标为新SHA。
