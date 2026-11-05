# 公司RTX4090正确率调查：未找到有效修复

用户授权连接公司服务器，并自行重启以修复驱动版本不匹配。此后真实部署了固定7B/BF16 SGLang服务，完成六组配置对照；两处归档内容错误仍然存在。没有修改默认配置、提示、模型、采样或正确率门槛来掩盖失败，也没有启动正式评测。

本机导入压缩包SHA-256：`260a6bff48b6fb41416be95914da292a4c3514fc6f286e9b3fd7df26012c9c9f`。77个原始文件、5,499,843字节；远端按三个实际私密凭据值扫描均无命中，本机检查包哈希、路径、文件类型、大小和凭据模式后解包，未修改原始文件。权重、.env、私钥、账本和SSH地址均不包含在结果包中。

环境为RTX4090/24564MiB、驱动580.178.04、Python3.12.15、Torch2.9.1/CUDA12.8、Transformers4.57.1、SGLang0.5.9，175包完整闭包及pip check通过。安装工具uv0.13.7下载包以官方release SHA-256 `c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83`验证，仅安装到用户目录。系统Python和GPU驱动未由本项目修改。

Hugging Face网络不可达，故在本机从固定HF revision下载并用Git blob hash核对10个小文件；四个权重分片从ModelScope的官方Qwen镜像下载，再逐文件计算SHA-256，与固定HF revision公布值比较，全部一致。没有更换模型版本。见[权重验证](../../environment/self-managed-20261105/collection/model-weight-verification.json)、[小文件验证](../../environment/self-managed-20261105/collection/model-small-file-verification.json)及[HF文件清单](../../environment/self-managed-20261105/collection/hf-pinned-files.json)。

每个配置按两个归档分组及两个新seed控制分组运行，16个不同输入/分组重复3轮，经网关和引擎两条路径共384次尝试。不是384个独立新样本，也不是完整768请求性能矩阵，不据此计算正式分数或SLO。

| 运行（UTC） | 实际配置 | 归档short：网关/直连 | 归档long：网关/直连 | 新seed short和long：各路径 |
|---|---|---|---|---|
| [10:20:58](../self-managed/20261105T102058-diagnose/) | 初次工具运行，FlashInfer |45/48，0/48*|45/48，0/48*|48/48，0/48*|
| [10:30:43](../self-managed/20261105T103043-diagnose/) | FlashInfer，原始精度 |45/48，45/48|45/48，48/48|均48/48|
| [10:33:11](../self-managed/20261105T103311-diagnose/) | FlashInfer，FP32 head |45/48，45/48|45/48，45/48|均48/48|
| [10:46:59](../self-managed/20261105T104659-diagnose/) | Triton，原始精度 |45/48，45/48|45/48，45/48|均48/48|
| [10:58:21](../self-managed/20261105T105821-diagnose/) | Triton，FP32 attention归约 |45/48，45/48|45/48，45/48|均48/48|
| [11:00:06](../self-managed/20261105T110006-diagnose/) | Triton，确定性推理 |45/48，45/48|45/48，45/48|均48/48|
| [11:03:30](../self-managed/20261105T110330-diagnose/) | Triton，FP32 head+归约+确定性 |45/48，45/48|45/48，45/48|均48/48|

`*`：第一次工具在无key的直连请求中发送空Bearer头，被h11拒绝；192次LocalProtocolError没有发到GPU，不能计为模型错误。已保留该次结果并修正请求头，增加真实TCP/h11回归。其余六次均完整执行，无传输错误，仍有内容错误。

总计2688个矩阵尝试，2496次成功完成、2421次内容正确，75次完成但内容错误，192次为上述客户端工具失败。这些数据高度重复，不能当作独立泛化样本估计总体模型准确率。[本机复核JSON](review.json)和[逐配置CSV](comparison.csv)保留各分母、source commit、实际engine选项与失败原文。执行 `.venv-benchmark/bin/python results/gpu/self-managed-review-20261105/review.py`，已确认输入重生成、token重计数、严格答案判定、矩阵与汇总全部一致；`integrity_pass=true`只指数据一致，七次`all_correct`全部为false。

进一步直接调用SGLang非流式接口，同样出现id 91173→9173、末条units 74→82，见[原始JSON](../../environment/self-managed-20261105/collection/direct-nonstream-triton-head0.json)。另有省略response_format的两次非流式探针，也都出现相同错误，见[探针记录](../../environment/self-managed-20261105/collection/unconstrained-nonstream-combined.json)；该探针改变了请求格式，仅用于诊断，不能作为任务书验收证据。这四次探针不包含在上述矩阵计数中。

结论只到这里：错误已经在SGLang直接返回的内容中复现；现有数值候选未消除错误，不能证明某个参数是有效修复，也不能排除尚未定位的上游推理问题。不同路径的cache/batch历史仍不同，不能仅凭长任务两路径结果差异断言网关篡改输出。下一步应由平台/上游用同一固定输入核验，而非自行改变冻结提示、模型或答案。

运行源码对应三份完整提交：初次工具`2a2ce25d345b27ea701024552d6939c979ab3178`；请求头修正后的前三组`b07a87006bf8277809c4704edbf035e90190f0f3`；后续三组`f8582900e8210eb44b433f93d6743d7422424347`。后续归档提交不改写这些来源。

另补SGLang官方支持的`--model-impl transformers`实现控制，同一7B BF16、同一JSON模式、原样输入。初次手动运行器未复用setup的PATH，因找不到ninja在JIT阶段退出，`complete=false/0样本`，不能算模型失败；修正运行器使用同一环境配置函数后，两个直接非流式样本仍全部错误（0/2）。见[首次失败](../../environment/self-managed-20261105/transformers-control/report.json)和[环境修正后结果](../../environment/self-managed-20261105/transformers-control-with-runtime/report.json)，临时运行器原文及SHA-256一并保存。临时探针的退出码本身不代表通过，必须看complete和逐样本quality_pass。这两份控制通过单独SFTP取回，不属于上述77文件压缩包；不计入2688矩阵尝试或任何正式分数。

测试结束已通过setup停止本项目自有服务，GPU空闲显存恢复24041MiB、利用率0%；公司服务器未关机或销毁。模型缓存与私密DATA_DIR保留在远端，见[收集及清理记录](../../environment/self-managed-20261105/collection/collection.json)。
