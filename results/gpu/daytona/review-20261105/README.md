# 2026-11-05 Daytona练习数据复核

用户在已申请的Daytona练习机运行并通过SSH返回压缩包。本机检查gzip、tar路径/文件类型、125个原始文件（4,763,915字节）和凭据模式后解包，未改写原始结果。压缩包SHA-256：`ba85ff01b6e14cb28d0ad1a3044ab670ceec64d4468701cc85877bfc541da407`；逐文件SHA-256见[review.json](review.json)。压缩包本身留在被忽略的`.cache/incoming/`。

GPU运行源码SHA：`1cbc12e510e2b8c7daa49ae6b8944e9baff99db3`。设备为NVIDIA GeForce RTX4090、24564MiB，驱动580.178.04；机制manifest报告torch2.9.1、Transformers4.57.1、SGLang0.5.9、CUDA12.8。服务模型为固定Qwen2.5-7B-Instruct/BF16；KV独立实验按任务书使用固定1.5B/FP32。这些是返回文件的身份信息，不是平台独立证明。

| 阶段 | 原始目录（UTC开始时间） | 本机复核结论 |
|---|---|---|
| smoke | [08:25:20](../20261105T082520-smoke/) | 双用户真实Agent/流式/非流式/计费与轮换HTTP断言通过；旧key401、新key200、各7个管理写路由隔离；20次断流取消后队列归零 |
| bench | [08:28:11](../20261105T082811-bench/) | 两profile各384测量+48预热；输入重生成、对照输入相同、独立重计数和全部汇总重算通过；性能存在内容错误 |
| experiments | [08:51:21](../20261105T085121-experiments/) | KV12行、Attention18行、Prefix96行证据校验通过；六份profiler trace与对应hash一致 |

baseline有53次明确SSE请求超时，C8长任务26次、C16长任务27次；另1条成功但答案错误。optimized全部384请求完成，其中382正确。四个冻结目标组中short/C8、short/C16、long/C8八项指标全部满足，long/C16正确率47/48=97.9167%低于99%，该组不通过；其他七项满足也不能抵消。short/C4在两个profile的相同输入中均出现错误，不掩盖为非正式目标组而忽略。

具体内容错误：[review.json](review.json)保存原输出与期望值。`baseline-short-c4-r1-short-3`与`optimized-short-c4-r1-short-3`将id 91173输出为9173；`optimized-long-c16-r2-long-12`将最后一条units 74输出为82。没有修改提示、采样策略、输出、模型或正确性判定。具体数值/调度原因待诊断与GPU复测，不能宣布项目整体通过。

取消数据同时包含网关abort确认增量20、SGLang `num_aborted_requests_total=20`以及引擎running/queue归零；原始指标快照已保留。此证据不证明预分配显存池全部退还或精确回收时间。setup编排运行到后续阶段，但缺少完整启动stdout/native freeze，正式固定快照洁净重建仍待执行。

离线复核命令（从仓库根目录执行，不申请GPU）：

```bash
# 先按根README准备requirements-benchmark.lock对应的独立客户端与固定tokenizer缓存
.venv-benchmark/bin/python results/gpu/daytona/review-20261105/review.py
# 图表另用requirements-analysis.lock对应的环境
.venv-analysis/bin/python results/gpu/daytona/review-20261105/plot.py
```

`review.py`退出0仅表示证据内部一致；`all_optimized_targets_pass=false`明确保留性能失败，不产生分数。复核用返回的计时窗口重算汇总，不能从行数据重新证明跨请求墙钟窗口。manifest为`participant_cli_unattested`，official_score=false。完整冻结门槛、方法与局限见[性能报告](../../../../docs/performance.md)。

原始数据不因归档提交而变更运行SHA。后续若修复服务，必须用新SHA和新输出目录GPU复测，不能把本次记录重新标为新代码通过。Prefix专用SLO、鉴权/账本开销对照、持续负载能力、完整管理私有黑盒、固定快照重建及正式评分均待确认/待执行。

[16组CSV及p50/p95](serving.csv) · [性能图](serving-performance.png) · [成功/正确率图](serving-quality.png) · [机制图](mechanisms.png)
