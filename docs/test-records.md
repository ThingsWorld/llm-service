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

补充核对：公开测量客户端独立安装到 `.venv-benchmark`，Transformers 4.51.3/tokenizers 0.21.4/httpx 0.28.1/jinja2 3.1.6 与实际24包闭包已冻结；pip check 及公开 CLI --help 通过，见 [benchmark-client.json](../results/benchmark-client.json)。没有运行模型推理。KV 入口已验证可直接从固定7B服务环境选择任务书的1.5B原理模型，错误/交叉 revision 仍拒绝；相关入口测试7/7通过。

最新完整本地工程测试 **133 passed / 8.66秒**，见 [engineering-04.xml](../results/cpu/engineering-04.xml)。随后针对 Agent 的清理修正补充回归：正常完成子调用不再误发 abort、污染取消确认计数；失败/超时仍传播取消。

### 真实浏览器与第二次 HTTP/崩溃自测

`PLAYWRIGHT_MODULE=<本地安装目录> .venv-test/bin/python scripts/local_cpu.py --console --out results/cpu/local-02` 实际运行：公开诊断18/18、管理HTTP10项通过（2项单独跳过）、两个SIGKILL窗口通过，以及 [管理页13项真实Chromium交互全部通过](../results/cpu/local-02/console.json)。覆盖无凭据壳、管理员连接、用户创建、共享配额、一次性key/掩码列表、轮换、撤销、余额调整、调价版本、真实账单、停用、审计、退出清理。

浏览器为 Playwright 1.56.1 / Chromium 141.0.7390.37。此本机Ubuntu26环境使用官方Ubuntu24构建的兼容浏览器，额外3个库仅下载解包到被忽略的缓存，通过该进程 LD_LIBRARY_PATH 加载；没有修改系统包、GPU环境或网关依赖。该记录只证明本次浏览器/环境的功能路径，不代表全部浏览器兼容性或页面性能。

[第二次真实恢复报告](../results/cpu/local-02/recovery.json)：未知usage **2.114秒**恢复，费用仍null；journalled usage **2.300秒**恢复、500 micro-USD恰好一次。均核实监听PID、实际SIGKILL、预占释放与重跑幂等。记录的 HEAD 为 `fbecae6a7c7bd05f241b01be8f382a92ded388b8`、source_working_tree_dirty=true，属于开发复测，不冒充该精确提交未经修改的实测。

第二个已push提交 `fbecae6a7c7bd05f241b01be8f382a92ded388b8` 的 GitHub [软诊断41578962624](https://github.com/ThingsWorld/llm-service/actions/runs/41578962624) 与 [工程测试41578962601](https://github.com/ThingsWorld/llm-service/actions/runs/41578962601) 均为success；后续修改继续对应新运行。

## 已提交源码的精确复测

源码提交：`62f3e025b140b5a826d8b9ae9c731a559fc0607c`，已push。该版本所有源码在复测时无未提交修改，报告 `source_working_tree_dirty=false`；生成结果文件造成的整个工作区 dirty 不等于源码变化。

- [GitHub软诊断41580002389](https://github.com/ThingsWorld/llm-service/actions/runs/41580002389)：success，18/18；[原始报告](../results/actions/41580002389/report.json)。
- [GitHub工程测试41580002390](https://github.com/ThingsWorld/llm-service/actions/runs/41580002390)：success，133/133，10.625秒；[原始JUnit](../results/actions/41580002390/engineering.xml)。
- `.venv-test/bin/python scripts/local_cpu.py --console --out results/cpu/local-03`（使用上述已安装的浏览器模块与本地库环境）：[接口18/18](../results/cpu/local-03/interfaces.json)、[HTTP管理10项通过](../results/cpu/local-03/control-plane.json)、[浏览器13/13](../results/cpu/local-03/console.json)。HTTP自测的场景10由外部恢复报告覆盖，场景12仍等待真实GPU，没有把skipped写成passed。
- [两次SIGKILL恢复](../results/cpu/local-03/recovery.json)：未知usage窗口 **1.855秒**释放预占并保留null费用；可信usage已journal窗口 **2.249秒**恰好结算500 micro-USD。两窗口均验证监听socket归属、幂等PID和余额、后续可恢复服务。

后续记录提交只增加脱敏报告和文档时，源码证据仍明确绑定上述提交，不改写报告的 commit。当前阶段没有启动、申请或正式提交任何Daytona GPU运行；GPU性能与全部机制实测仍未完成。

## 待执行与待确认

- 后续提交仍需新的 GitHub Actions 结果；旧运行不能当成新 SHA 通过。
- 管理页面核心交互已在本地真实浏览器验证；全部浏览器/代理链路兼容性与真实GPU页面用量仍待验证。
- 练习机连接、可用时间、RTX 4090身份：如执行练习验证则在已有资源上核实。正式评测由平台clone指定SHA并执行setup，不以本机SSH配置为前置条件。
- SGLang native 干净安装、切换、live 计费/轮换/Agent、GPU 取消、768 请求性能、三项机制实验：未执行。
- 平台 15 项正式 credentials 黑盒与对应 live 门槛、正式 GPU 评测：未执行；平台 staging/配额遗留矛盾待平台当前状态确认。
- Gateway 开销对照、GPU 显存峰值、p50/p95/吞吐/goodput：无本项目真实 GPU 数据，不宣称达标。

## 2026-11-05：核对正式 setup 启动合同

按用户指出的任务书合同修正文档：平台准备固定Daytona基础快照并注入环境变量，clone整个仓库、checkout完整SHA后直接执行 `bash setup.sh`。本机SSH别名、`.env`手工配置及 `scripts/gpu_validate.sh` 均不属于正式评测前置条件；它们只用于可选的练习机连接和自测。README已将两个流程明确分开。

核对实现调用链：`setup.sh → scripts/native_setup.py → server.supervisor → SGLang + HTTP网关`。默认native路径安装完整锁定依赖、读取平台模型/revision与HF_HOME、检查CUDA并等待健康；CPU contract模式单独选择。启动入口及服务代码本次未作功能修改。

新增两个默认native启动编排回归用例：不提供SGLANG_PYTHON、不调用gpu_validate，验证完整依赖安装与自有supervisor启动；就绪超时则清理自有进程并报错。测试拦截了依赖安装、CUDA、进程和健康检查，不使用真实GPU，不能证明干净GPU重建已通过。

- `.venv-test/bin/python -m pytest -q tests/test_native_setup.py`：**21 passed / 0.10秒**。
- `.venv-test/bin/python -m pytest -q --junitxml=results/cpu/setup-contract-20261105/engineering.xml`：**135 passed / 8.54秒**；[原始JUnit](../results/cpu/setup-contract-20261105/engineering.xml)。
- `bash -n setup.sh experiments/run.sh scripts/gpu_validate.sh`、`git diff --check`：通过。
- 本次测试基于 `b9c9fb55fe73ad5db945d430d3cda5826f5e2859` 的开发工作区（仅文档和测试修改），不改写先前提交的报告与SHA。真实GPU安装、模型就绪、预算和性能结果仍待实测。

## 2026-11-05：支持自建RTX 4090服务器的自测来源标记

用户询问能否在公司自建4090上测试。核对核心setup没有Daytona API依赖，仍按Linux/Python3.12/固定模型与锁定栈启动；公司的系统、驱动、空闲显存与可达性尚待实际检查。本次没有连接公司机器或产生GPU实测结果。

将可选GPU自测的输出目录从固定 `results/daytona/` 改为 `results/gpu/<环境>/<时间>-<阶段>/`。`LLM_TEST_ENVIRONMENT=self-managed` 标记自建机，`daytona` 标记Daytona练习机，未指定时为 `unspecified`。新增context.json记录环境标签、GPU、完整SHA、模型和 official_score=false；三项机制manifest也记录标签。正式评测的根setup入口不变，自建机结果不能代替平台Daytona正式重建与评分。

- 新增自测来源回归：self-managed/daytona/未指定三种标签、无效标签拒绝，以及输出不含三种服务凭据；**4 passed / 0.22秒**。
- 全量CPU测试：**139 passed / 8.31秒**，见 [原始JUnit](../results/cpu/self-managed-context-20261105/engineering.xml)。
- `bash -n setup.sh experiments/run.sh scripts/gpu_validate.sh`、`git diff --check`：通过。
- 新测试使用临时目录与合成shell替身验证元数据行为，不启动GPU、模型或真实公司服务；测试结果不表示公司GPU环境已兼容或性能已达标。

## 2026-11-05：Daytona练习GPU返回数据与本机复核

用户在Daytona执行 `bash setup.sh`、`bash scripts/gpu_validate.sh smoke`、`bench`、`experiments`，再将结果压缩包取回本机。三阶段context与机制manifest的完整源码SHA均为 `1cbc12e510e2b8c7daa49ae6b8944e9baff99db3`；RTX4090/24564MiB、驱动580.178.04，机制环境torch2.9.1/Transformers4.57.1/SGLang0.5.9/CUDA12.8。不是公司机器数据，也不是正式评测。

本机gzip完整性检查通过，tar共125个原始文件/4,763,915字节，无链接和越界路径，凭据模式扫描无命中；压缩包SHA-256为 `ba85ff01b6e14cb28d0ad1a3044ab670ceec64d4468701cc85877bfc541da407`。[原始阶段目录与复核说明](../results/gpu/daytona/review-20261105/README.md)，原始文件逐项hash见review.json。六份profiler trace随归档提交保留，未因默认ignore而丢弃。

- GPU live双租户真实Agent/流式/非流式/用量/费用/轮换/管理隔离HTTP断言通过；其他CPU隔离场景标为skipped，并非在此重复完成正式15项黑盒。
- 取消20次：网关abort确认增量20、SGLang aborted计数20，末尾running/queue均0；独立显存回收时延未测。
- 本机执行 `.venv-benchmark/bin/python results/gpu/daytona/review-20261105/review.py`：输入按seed重新生成、独立tokenizer重计输出、16组汇总重算均一致；768测量请求与96预热分别保存，全部失败保留。返回0表示完整性通过，不表示性能通过。
- baseline：384请求、331完成、330正确，53个明确SSE超时；optimized：384请求全部完成、382正确。short/C4相同输入在两个profile均将91173写成9173；optimized long/C16最后一条units将74写成82。long/C16质量47/48低于99%，四个冻结目标组仅三组通过。未把错误重分类为容量失败，未放宽门槛。
- 对每项执行 `.venv-test/bin/python -m experiments.verify_evidence --case <kv|attention|prefix> --directory results/gpu/daytona/20261105T085121-experiments/<case> --commit 1cbc12e510e2b8c7daa49ae6b8944e9baff99db3`：分别12/18/96行证据通过。KV最大绝对误差5.43594e-5且top1=100%；Attention最大0.015625、math/flash算子及六份trace hash通过；Prefix96行全部输出OK，off无命中、shared热命中≥512、unique最多6。
- `.venv-analysis/bin/python results/gpu/daytona/review-20261105/plot.py`生成3张真实数据图；p50/p95及16组结果保存为CSV，不能以条件延迟忽略失败率。
- 归档后重新运行全量CPU工程测试：**139 passed / 8.77秒**，见[原始JUnit](../results/cpu/gpu-archive-20261105/engineering.xml)；分析环境`pip check`无依赖冲突。该轮工作区仅增加文档、原始数据和离线复核/绘图文件，服务源码仍对应上述SHA。
- GPU来源源码的[工程Actions 41982968884](https://github.com/ThingsWorld/llm-service/actions/runs/41982968884)与[软诊断41982968705](https://github.com/ThingsWorld/llm-service/actions/runs/41982968705)均已核实success；不把后续归档提交当作已在GPU重跑。

原理与限制：连续批处理、前缀缓存和后端由profile同时改变，整体吞吐变化不能归因到单项。KV/Attention有独立同输入数值对照，Prefix有真实cached_tokens而非仅看速度。Prefix独立SLO未标定，因此goodput=null；鉴权/账本开销对照、持续负载、完整setup stdout/native freeze、洁净固定快照重建和正式评测均未完成。内容错误已定位，具体原因及修复效果需新GPU运行验证。此次只归档证据、文档和离线分析脚本，服务源码未改动。

## 2026-11-05：正确率诊断工具与公司4090环境恢复

对照原始错误输入及输出，确认是完整JSON中的字段内容错误，不能通过延长超时修复。审查Chat/payload/SSE转发，新增数字跨SSE事件的网关回归，不修改模型答案；同一短任务两个profile均失败也不能证明某个单独后端有缺陷。

新增`benchmarks.diagnose_accuracy`与`gpu_validate.sh diagnose`：两个受影响完整16请求分组，加两个新seed控制组，经完整网关与引擎直连各3轮，合计384条计划请求；实际使用独立固定tokenizer，输入重生成与512/1024长度检查。保留错误、输出、期望值、实际engine参数、工作区状态，不产生分数。直连诊断不取代经鉴权/账本的性能测量，也不把不同cache/batch历史的独立请求差异直接判为网关错误。

添加默认关闭的`FP32_LM_HEAD`，仅映射已核对的SGLang0.5.9官方`--enable-fp32-lm-head`；模型与中性采样不变，切换包含在setup指纹中，非法值在停止服务前拒绝。尚无该候选的GPU正确性或性能结果，不能宣称修复。完整bench可显式设置新`BENCH_SEED`验证泛化。

- 新增受控传输/拒绝/指纹/幂等测试；首轮相关测试55通过/0.85秒，全量153通过/9.59秒。增加安装前拒绝非法值与实际引擎版本校验后，最终全量**154通过/10.29秒**，见[最终JUnit](../results/cpu/accuracy-diagnostic-20261105/engineering-final.xml)。这些测试不启动GPU。
- 使用独立4.51.3 tokenizer实际重生成两个归档分组及两个新seed分组，共64个输入；归档完全一致，新控制不同，长度检查通过。这仅是输入生成检查，不是模型推理。
- 公司服务器SSH只读初检显示实体RTX4090存在，但加载驱动580.173.02与磁盘580.178.04不符，nvidia-smi退出18、CUDA初始化804；默认Python3.10.12，存在CUDA12.4 nvcc。未安装/修改驱动。见[初检](../results/environment/self-managed-20261105/preflight.json)。
- 用户自行重启后重新连接，RTX4090/24564MiB、空闲24041MiB、利用率0%，加载驱动580.178.04、CUDA初始化0，8000/30000无监听。见[重启后原始报告](../results/environment/self-managed-20261105/post-reboot.json)。模型服务尚待隔离Python与依赖/模型准备。

上述源码改动以归档提交`1bb97cecc83ed5e204b4e948d5b08bf0350015b3`为基准，不改写既有Daytona记录的源码SHA。远端SSH连接地址、用户名、私钥和任何服务凭据未写入这些公共结果；公司自测不能替代正式Daytona评分。

### 公司初次重放与直连工具修正

公司环境已完成Python3.12.15隔离安装、175包完整闭包校验、pip check和真实CUDA分配。网络阻断Hugging Face，按固定HF revision的Git blob哈希校验10个小文件，并以HF公布的SHA-256校验ModelScope官方Qwen镜像的四个权重分片，确认与原权重逐字节相同后使用离线缓存；没有替换模型或版本。

源码`2a2ce25d345b27ea701024552d6939c979ab3178`第一次384行诊断中，经完整网关的192次请求全部完成，186正确：两个原始分组各45/48，两个新seed控制各48/48。两处数字错误均重复3次。引擎直连的192行均为客户端`LocalProtocolError/status=null`，没有发到GPU，不能算作模型答错。原因是诊断复用的request_once为无凭据直连构造了带尾空格的`Authorization: Bearer `，h11在真实HTTP传输中拒绝，而MockTransport未暴露这一错误。

已修正为无key时不发送Authorization；普通网关请求仍带原始Bearer，服务鉴权规则未变。新增真实loopback TCP/h11回归，相关28项通过/0.32秒，全量**155通过/8.93秒**，见[JUnit](../results/cpu/accuracy-diagnostic-20261105/engine-header-regression.xml)。保留首次失败记录，修正后需重新运行GPU对照；此工具修正不声称修复模型内容错误。
