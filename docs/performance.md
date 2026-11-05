# 性能与机制验证

## 当前证据

用户在Daytona RTX4090练习机运行三个自测阶段并返回原始压缩包，本机已校验并归档，见[复核记录](../results/gpu/daytona/review-20261105/README.md)及[审计JSON](../results/gpu/daytona/review-20261105/review.json)。源码SHA为 `1cbc12e510e2b8c7daa49ae6b8944e9baff99db3`。这些是练习自测，未经平台独立证明，不是正式评分；下表比较冻结要求和实测，不能以速度抵消正确率失败。

验收配置：`daytona-4090-v5-confirmed-5e2971c9`；workload：`typed-json-numbered-records-prose-exact-input/5`；acceptance SHA-256：`d5cd2fdc90056e710cf741ac1eec4c5b042ea3818d505e4a3975697f1df9241f`。

| 负载/C | output token/s ≥ | TTFT p95 ms ≤ | TPOT p95 ms/token ≤ | E2E p95 ms ≤ | quality goodput ≥ | SLO比例 ≥ | 成功/正确率 ≥ | 本项目实测 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| short/8 |71|1780|35|2350|3.67|.95|.99/.99|八项通过|
| short/16 |128|1830|40|2600|6.63|.95|.99/.99|八项通过|
| long/8 |254|1870|29|8900|.95|.95|.99/.99|八项通过|
| long/16 |485|2070|30|9350|1.81|.95|.99/.99|正确率失败，其余七项通过|

optimized实测（每组48请求，延迟单位ms）：

| 负载/C | 有效output token/s | TTFT p95 | TPOT p95 | E2E p95 | quality goodput req/s | SLO比例 | 成功/正确数 |
|---|---:|---:|---:|---:|---:|---:|---|
| short/8 |315.94|138.61|17.39|478.32|17.49|100%|48/48，48/48|
| short/16 |521.19|197.85|19.39|597.18|28.82|100%|48/48，48/48|
| long/8 |461.48|277.23|16.73|4390.29|1.85|100%|48/48，48/48|
| long/16 |840.36|452.79|17.43|4661.92|3.36|97.92%|48/48，47/48|

完整两profile共768测量请求，另96预热；原始输入重新生成完全一致，输出经固定tokenizer重计数，所有汇总重算一致。baseline共384请求、331成功、330正确：long/C8有26次、long/C16有27次明确`sse_request_timeout`。baseline与optimized的short/C4同一输入均将id 91173写成9173；optimized long/C16末条记录将units 74写成82。失败全部保留，不伪装为容量错误，也没有改提示、模型、输出或容差。此时不能称为全矩阵正确或完成确认运行。

[16组及p50/p95 CSV](../results/gpu/daytona/review-20261105/serving.csv)、[性能图](../results/gpu/daytona/review-20261105/serving-performance.png)、[全请求成功/正确率图](../results/gpu/daytona/review-20261105/serving-quality.png)一起解读；延迟分位数条件于成功正确请求，不能忽略失败率。

三项机制原始矩阵与本机校验均通过：[机制图](../results/gpu/daytona/review-20261105/mechanisms.png)。KV最大绝对误差5.43594e-5、top1一致率100%；长度128/512的32-token decode中位耗时，cache off为741.92/1715.18ms，on为708.81/704.35ms。Attention三长度误差最大0.015625，math/flash算子及六份trace哈希均检查通过。Prefix的off全部cached_tokens=0，on/shared热请求命中≥512，on/unique最多6；off/shared TTFT中位69.92ms，on/shared热请求33.56ms。相应数值只适用于各自独立实验负载。

## 方法与原理

连续批处理每轮安排活跃请求的 token 计算，新请求可在已有请求结束后加入；网关只做有界准入，active/queue 不是 GPU batch size。profile 同时改变并发、缓存和后端，整体收益不能归因于单项。

KV Cache 保存每层历史 K/V，decode 避免重算已有 token。逻辑容量公式为 `2 × layers × KV_heads × head_dim × dtype_bytes × tokens`。独立固定 1.5B FP32 实验逐位置比较 cache on/off logits，要求最大绝对误差≤0.001 且 top1=100%；长度128/512、回放32 token、3轮，共12行。最终服务仍是7B BF16，不能用 FP32 原理实验替代服务正确性。

RadixAttention 用前缀树匹配已有 KV，引用计数保护活跃节点，可淘汰节点由缓存池复用。Prefix 采用同服务7B BF16，on/off × shared/unique ×3×8=96行，512前缀ID、flush冷/热对照与实际 cached_tokens；速度不能证明命中。释放请求不要求 CUDA 内存池全部退还显存。

FlashAttention 通过分块与在线 softmax 避免完整注意力矩阵反复进出显存；math/flash 使用同一合成 Q/K/V（B1/H8/dh64/BF16/causal/dropout0），3长度×3轮×2后端=18行，最大绝对误差≤.02，并保存 profiler 算子与 trace。SGLang optimized 使用 FlashInfer，与 PyTorch SDPA FlashAttention 分别记录。

服务性能经完整鉴权/配额/账本网关测量。baseline/optimized 使用相同输入与seed：chat-template 输入512/1024、输出上限96/384、C1/4/8/16、3轮×16，共768测量请求，预热另存。独立 tokenizer 统计实际可见输出，失败保留在成功率/正确率分母；有效吞吐只统计成功正确的输出。还需受控对照记录鉴权/账本增量开销，正式性能测量不能关闭这些模块。

SSE 的首个非空 content 才计 TTFT；E2E 到完整流结束；TPOT=(最后content−首个content)/(独立输出tokens−1)，只有多个内容事件且N>1时有值。事件间隔不等于逐token ITL。CPU Event 测试证明网关未攒齐输出，仍需 GPU 直连/隧道或公网时间线确认实际链路。

## 局限与待确认

本次是练习机返回数据的离线复核，不等于固定快照洁净重建或平台独立测量；未保存完整setup stdout与native依赖freeze，不能仅凭三项库版本声称整个175包闭包均已逐一复核。短时闭环测量也不能证明持续负载容量。鉴权/账本增量开销的受控对照尚未执行，不能填写开销百分比。profile多项配置同时变化，整体收益不能归因于单项。

long/C16正确率和两profile的short/C4输出错误尚待修复及GPU复测，已定位到字段内容错误，具体数值/调度原因未证实。Prefix独立实验没有冻结的专用延迟SLO，quality_goodput=null仍为待确认，不能套用正式extraction阈值。取消记录中网关与引擎abort各20、队列归零，但没有独立显存回收时间线，不能声称预分配池显存退还。正式平台分数、完整管理黑盒及洁净重建尚未运行。

新增[数值/传输对照诊断](accuracy-diagnosis.md)。公司RTX4090已完成环境准备并复现内容错误；FP32输出层及单独切换Triton均未消除归档错误，直接非流式引擎请求也错。候选保持默认关闭；后续数值对照及完整性能复测尚未完成，不能把历史Daytona数据当作候选开关通过记录。

执行前刷新平台9份公开工具并校验manifest；按原任务书命令运行，再将本项目 manifest/raw/summary/图表及完整commit链接到这里。数值失败保留 complete=true 和非零退出，中途失败 complete=false，不删失败行，不放宽容差。
