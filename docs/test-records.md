# 分阶段测试记录

所有记录均为本项目实际运行；本地 CPU 自测不是官方成绩。参考 GPU 结果没有复制到 results。

## 阶段 0：审计与工作流安装

原理：固定源码、合同和测量环境，先区分接口诊断、模型 fixture 与真实推理，避免混用证据。

- 初始 SHA：`049f423d14d2592f029725ea48fe7ef2c028227d`，只有 README，工作区任务书未跟踪。
- 官方 workflow SHA-256：`6b0a537c5af8b85af76e4ac0622ba0c4649883844997244966e8db97c1ba043d`，已审阅 GitHub 托管 CPU runner、固定 Actions commit 和三份工具 hash，不需要平台 secrets。
- 任务书 acceptance 原始 JSON 精确提取，SHA-256：`d5cd2fdc90056e710cf741ac1eec4c5b042ea3818d505e4a3975697f1df9241f`。V5 四组阈值已确认，不是本项目实测。
- 公开源码底座固定 `9961c0503c2eb3fa702794ef9281dd88f96d9456`，原始文件 hash 在 source-import.json；没有复制参考 results。

## 阶段 1–2：CPU 实现与诊断

环境：本地 Linux/WSL、Python 3.12.15，私有 `.venv-test`，锁定 CPU 依赖。模型为受控 fixture，不使用 GPU。原理：SQLite BEGIN IMMEDIATE 原子预占、不可变价格版本与恰好一次结算；HMAC 摘要与普通/管理员权限分离；SSE 上下游都流式读取，finally 释放网关槽位并以相同 rid abort。

首次 `python -m pytest -q --junitxml=results/cpu/initial.xml`：**121 passed / 2 failed**，7.54 秒。两处失败是原参考测试假定 acceptance 仍未标定，实际新任务书已发布 confirmed 配置；已改为验证测量合同一致与独立确认凭据，没有放宽性能断言。初始失败原样保留。

首次 `.venv-test/bin/python scripts/local_cpu.py --out results/cpu/local-01`：

- [公开 HTTP 诊断](../results/cpu/local-01/interfaces.json)：**18 pass，0 missing / invalid / blocked**。执行位置明确为 local_cpu_developer_reproduction，非 GitHub Actions 运行。
- [HTTP 管理自测](../results/cpu/local-01/control-plane.json)：**10 项通过，2 项 skipped**；场景 10 的实际崩溃在独立恢复报告，场景 12 等待 GPU。不是 15 项平台私有黑盒或官方分数。
- [真实进程恢复](../results/cpu/local-01/recovery.json)：确认 gateway.pid 拥有监听 socket 后 SIGKILL。未知 usage 窗口 **2.454 秒**恢复，adjusted_unknown / cost=null；最终 usage 已 journal 的窗口 **2.249 秒**恢复、精确结算 **500 micro-USD**。重跑 setup PID 不变、无二次扣费，后续请求成功。
- 这些开发记录的基准 HEAD 仍是初始 SHA，报告标注 working_tree_dirty=true 与源码文件摘要，不能将初始提交本身说成已包含实现。提交后的精确 SHA 验证另行记录。

补充信号控制测试与相关测试：**29 passed**，1.56 秒。真实 HTTP 首段在 engine finish Event 释放前已到客户端，覆盖中文 UTF-8 拆包/事件合并。20 请求余额竞争使用明确 Event 阻止首请求结算，先断言 19 个 402 与唯一 680 预占，再释放信号；不依赖 sleep 猜测原子性。

提交前完整工程测试：**124 passed**，7.86 秒，见 [engineering-01.xml](../results/cpu/engineering-01.xml)；`pip check` 无依赖冲突，`bash -n setup.sh experiments/run.sh` 通过。原始测试为 123 项，新增真实 HTTP 信号测试 1 项；初始两处旧配置断言已修复。首次 staging 后 whitespace 检查提示任务书 Markdown 硬换行及原始失败 XML 的尾空格：保留原始内容，用 .gitattributes 明确这两类证据的 whitespace 规则；另移除 .gitignore 多余末尾空行，后续 `git diff --check` 通过。当前 GitHub 登录已验证为仓库管理员 ThingsWorld，仓库公开、默认分支 main，认证后的 dry-run push 成功。

## GitHub 独立 CPU 运行

已推送并在公开 main 上运行：`6520e9a07c9dac8701c5bb9cc928840c75c0c8a8`。

- [官方软诊断运行 41577429848](https://github.com/ThingsWorld/llm-service/actions/runs/41577429848)：success，**18/18**。原始 [report.json](../results/actions/41577429848/report.json) 与 summary 已下载；official_score=false，gpu_used=false。
- [工程测试运行 41577429533](https://github.com/ThingsWorld/llm-service/actions/runs/41577429533)：success，**124/124**，9.840 秒；[原始 JUnit](../results/actions/41577429533/engineering.xml)。

这两个结果只覆盖上述 SHA，后续代码修改须对应新的运行。官方 CPU 工作流本身没有被修改；没有手工更改报告中的通过字段。

## GPU 前的代码核对（尚无 GPU 实测）

补齐按 key/model/UTC 日期的用量分组与租户内过滤、未知用量/取消计数、真实 live 中的七个管理写路由隔离与轮换审计。KV/Attention 的退出判定现在同时要求硬性最大绝对误差（以及 KV 的 top1），不能仅用带相对容差的 allclose 替代。Prefix 的错误计入原96行，不再增加破坏矩阵的第97行；冷/不同前缀的 cached_tokens 也须 <512。独立 Prefix 没有冻结专用 SLO，goodput=null、待确认，不再硬填200/1500ms。

新增当前矩阵的证据验证器，覆盖缺行、重复、非有限值、输入不一致、误差、容量公式及符号链接等拒绝路径。合成 verifier 测试只证明校验器行为，不作为真实 GPU 实验结果。清理未使用的历史 A10 绘图、576 请求验收及 Docker 探针路径。GPU 取消探针现在跳过空 role/content、在首个非空内容后断流，并验证本次 abort 计数增量。

完整本地测试第二轮 **134 passed / 8.66秒**（[engineering-02.xml](../results/cpu/engineering-02.xml)）；移除2个历史 Docker 专用测试并新增取消探针回归后，第三轮 **133 passed / 8.43秒**（[engineering-03.xml](../results/cpu/engineering-03.xml)）。测试数量变化有明确代码原因，不是隐藏失败。

`scripts/fetch_public_tools.py` 已实际下载全部9份公开客户端并逐文件核对清单 SHA-256；当前 acceptance 与任务书原始 hash 完全一致，见 [tool-preflight.json](../results/tool-preflight.json)。这一步不加载模型、不申请 GPU。

## 待执行与待确认

- 后续提交仍需新的 GitHub Actions 结果；旧运行不能当成新 SHA 通过。
- 管理页面真实浏览器全部交互：待执行；当前 HTML 与 HTTP API 测试不等于完整页面验收。
- Daytona 的 SSH Host、可用时间、RTX 4090 身份：待用户资源就绪后核实，不申请新 GPU。
- SGLang native 干净安装、切换、live 计费/轮换/Agent、GPU 取消、768 请求性能、三项机制实验：未执行。
- 平台 15 项正式 credentials 黑盒与对应 live 门槛、正式 GPU 评测：未执行；平台 staging/配额遗留矛盾待平台当前状态确认。
- Gateway 开销对照、GPU 显存峰值、p50/p95/吞吐/goodput：无本项目真实 GPU 数据，不宣称达标。
