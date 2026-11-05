# 可供平台核验的固定样本复现

当前状态：未修复，不是通过证明；尚未启动正式评测。请求平台使用相同固定输入、当前公开参考运行栈复核，以区分模型生成局限与上游推理实现问题。

固定模型`Qwen/Qwen2.5-7B-Instruct`，revision `a09a35458c702b33eeacc393d103063234e8bc28`，BF16；SGLang0.5.9/Torch2.9.1/Transformers4.57.1，RTX4090，驱动580.178.04。基准客户端Transformers4.51.3/tokenizers0.21.4/jinja2 3.1.6。中性解码、temperature=0、JSON模式、冻结的512/1024输入和96/384输出上限，未改提示与答案判定。

两个样本均来自任务书示例seed20261018的V5负载：

| 样本 | 期望 | 实际错误 |
|---|---|---|
| short/C4/repeat1/short-3 | id=91173, city=Paris, units=39 | id=9173，其余字段正确 |
| long/C16/repeat2/long-12 | 最后一条id=77085, city=Berlin, units=74 | 最后一条units=82，复制了上一条的units |

完整输入已保存于[短任务分组](../results/gpu/daytona/20261105T082811-bench/serving/baseline-short-c4-r1-inputs.json)和[长任务分组](../results/gpu/daytona/20261105T082811-bench/serving/baseline-long-c16-r2-inputs.json)，不能删掉共享前缀后声称是同一负载。原始Daytona矩阵与公司重复对照均保留，见[公司复核报告](../results/gpu/self-managed-review-20261105/README.md)。

经完整网关、引擎直连SSE及引擎直接非流式均能出现内容错误；CPU网关逐字符转发回归证明受控路径不删重复数字、不修补错误答案。FP32输出层、Triton后端、FP32 attention归约、确定性推理及组合对照均未消除这两处错误。不能把确定性等同于正确性，或把不同batch/cache历史的独立请求差异直接归责于网关。

同版SGLang的Transformers模型实现控制也用相同BF16权重和请求复现两处错误，0/2正确，见[原始报告](../results/environment/self-managed-20261105/transformers-control-with-runtime/report.json)。这仍不能证明所有可能的上游问题都已排除；当前只能确认已测试方案没有有效修复。

后续比较旧版控制端与运行时完整token IDs，512/1024均完全一致；直接向native /generate提交这些IDs、JSON schema与显式中性采样，错误仍在。生成logprobs中，短例错误`7`相对正确下一字`1`的对数概率高约1.625，长例错误`8`相对正确`7`高1.0，错误已经发生在贪心生成决策。[完整证据与脚本](../results/gpu/accuracy-causal-review-20261105/README.md)。

完全独立于SGLang的Transformers BF16 SDPA、SDPA MATH、attention中间值FP32也复现两错；eager短例正确、长例却增加字段错误。禁用BF16 matmul低精度归约、FP32残差也没有同时正确的配置。HF探针未加JSON grammar，只作诊断；不能替代服务验收或据此宣布具体上游根因。不完整探针与失败输出均保留。

2026-11-05通过OpenLabs只读核对，返回公开参考版本仍为`27284ce8455cf845eade7e2e2f4b4c18c7e67454`，acceptance.json版本`d5cd2fdc90056e710cf741ac1eec4c5b042ea3818d505e4a3975697f1df9241f`。检索没有产生专项修复结论、平台复核回复或正式成绩。本说明尚未发给Mentor或平台人员。

复现源码完整SHA：`f8582900e8210eb44b433f93d6743d7422424347`。已有兼容服务、私密环境及固定benchmark客户端后，默认配置执行：

```bash
export LLM_TEST_ENVIRONMENT=self-managed
export BENCH_PYTHON="$PWD/.venv-benchmark/bin/python"
FP32_LM_HEAD=0 bash scripts/gpu_validate.sh diagnose
```

脚本保留两个完整16请求分组、另两个新seed控制组，每组3轮、两路径，共384尝试；任意错误返回非零。结果只能用于复现，不代替四目标组的完整正式性能测量。初次工具的192条LocalProtocolError已有独立修复，不与模型错误混淆。

请平台确认：同输入在公开参考SGLang栈是否同样复现；在固定模型/提示/中性解码约束下，应如何处理这种可重复的字段复制错误。当前没有证据支持声明48/48或放宽99%门槛；若需要更改验收负载，应由平台发布新版本，历史失败继续保留。
