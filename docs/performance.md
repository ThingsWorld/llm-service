# 性能与机制验证

## 当前证据

本项目目前只完成 CPU 协议与事务测试，见 [测试记录](test-records.md)。SGLang GPU 部署、性能与三项机制实验没有执行结果。下表是任务书冻结要求，不是本项目成绩。

验收配置：`daytona-4090-v5-confirmed-5e2971c9`；workload：`typed-json-numbered-records-prose-exact-input/5`；acceptance SHA-256：`d5cd2fdc90056e710cf741ac1eec4c5b042ea3818d505e4a3975697f1df9241f`。

| 负载/C | output token/s ≥ | TTFT p95 ms ≤ | TPOT p95 ms/token ≤ | E2E p95 ms ≤ | quality goodput ≥ | SLO比例 ≥ | 成功/正确率 ≥ | 本项目实测 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| short/8 |71|1780|35|2350|3.67|.95|.99/.99|未执行|
| short/16 |128|1830|40|2600|6.63|.95|.99/.99|未执行|
| long/8 |254|1870|29|8900|.95|.95|.99/.99|未执行|
| long/16 |485|2070|30|9350|1.81|.95|.99/.99|未执行|

## 方法与原理

连续批处理每轮安排活跃请求的 token 计算，新请求可在已有请求结束后加入；网关只做有界准入，active/queue 不是 GPU batch size。profile 同时改变并发、缓存和后端，整体收益不能归因于单项。

KV Cache 保存每层历史 K/V，decode 避免重算已有 token。逻辑容量公式为 `2 × layers × KV_heads × head_dim × dtype_bytes × tokens`。独立固定 1.5B FP32 实验逐位置比较 cache on/off logits，要求最大绝对误差≤0.001 且 top1=100%；长度128/512、回放32 token、3轮，共12行。最终服务仍是7B BF16，不能用 FP32 原理实验替代服务正确性。

RadixAttention 用前缀树匹配已有 KV，引用计数保护活跃节点，可淘汰节点由缓存池复用。Prefix 采用同服务7B BF16，on/off × shared/unique ×3×8=96行，512前缀ID、flush冷/热对照与实际 cached_tokens；速度不能证明命中。释放请求不要求 CUDA 内存池全部退还显存。

FlashAttention 通过分块与在线 softmax 避免完整注意力矩阵反复进出显存；math/flash 使用同一合成 Q/K/V（B1/H8/dh64/BF16/causal/dropout0），3长度×3轮×2后端=18行，最大绝对误差≤.02，并保存 profiler 算子与 trace。SGLang optimized 使用 FlashInfer，与 PyTorch SDPA FlashAttention 分别记录。

服务性能经完整鉴权/配额/账本网关测量。baseline/optimized 使用相同输入与seed：chat-template 输入512/1024、输出上限96/384、C1/4/8/16、3轮×16，共768测量请求，预热另存。独立 tokenizer 统计实际可见输出，失败保留在成功率/正确率分母；有效吞吐只统计成功正确的输出。还需受控对照记录鉴权/账本增量开销，正式性能测量不能关闭这些模块。

SSE 的首个非空 content 才计 TTFT；E2E 到完整流结束；TPOT=(最后content−首个content)/(独立输出tokens−1)，只有多个内容事件且N>1时有值。事件间隔不等于逐token ITL。CPU Event 测试证明网关未攒齐输出，仍需 GPU 直连/隧道或公网时间线确认实际链路。

## 局限与待确认

没有 GPU 原始数据，尚不能讨论实际收益、可持续并发或达标率。Prefix 独立实验没有冻结的专用延迟 SLO，不能套用正式 extraction 阈值或编造 goodput 达标。任何 null/未确认门槛必须保持待确认。参考 acceptance 内的 calibration/confirmation 仅用于说明阈值来源。

执行前刷新平台9份公开工具并校验manifest；按原任务书命令运行，再将本项目 manifest/raw/summary/图表及完整commit链接到这里。数值失败保留 complete=true 和非零退出，中途失败 complete=false，不删失败行，不放宽容差。
