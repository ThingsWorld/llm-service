# 输出内容错误的诊断与复测

当前结论：已定位输出字段错误，尚未证明具体原因，也没有已验证的修复。历史GPU数据继续对应源码 `1cbc12e510e2b8c7daa49ae6b8944e9baff99db3`，不能改标到新增诊断工具的提交上。

公司真实调查已完成六组数值配置及非流式探针，均未消除归档错误；[完整结果及源码对应](../results/gpu/self-managed-review-20261105/README.md)和[可交平台核验的说明](known-model-accuracy-issue.md)已归档。下列开关是诊断能力，默认关闭，不代表已经修复。

short/C4相同输入在baseline和optimized都把91173写成9173；optimized long/C16把最后一条units 74写成82。JSON结构有效、请求已完成，但内容不正确。延长超时或降低成功标准无法修复这些错误。两profile均出现短任务错误，也不能据此单独认定FlashInfer、Radix Cache或连续批处理有缺陷。

已经检查网关Chat校验、payload转发和SSE relay。新增CPU回归把正确/错误的数字输出拆成1字符及7字符SSE事件，经真实网关应用和HTTP backend transport重组后内容保持不变，且不修补错误答案。该结果覆盖受控传输路径，不等于已经观察到本次真实引擎输出边界。最新公开参考固定版本27284ce相对导入版本9961c05只有指标、测试、工作流及文档变更，没有可直接移植的数值正确率修复。

## 先比较同输入的两条路径

`benchmarks/diagnose_accuracy.py`只连接已有本机服务，不申请GPU。它读取受影响的完整16请求分组，而非只测试已知答案；另用新seed生成short/C4、long/C16各16个控制输入。按原始并发分别经过完整鉴权/账本网关和loopback SGLang直连，每组3轮，保留384条原始记录。固定模型、revision、BF16、temperature=0、中性解码、JSON模式和输出上限均保持一致。

记录实际SGLang `/server_info` 的白名单参数，包括输出层精度、attention、cache和CUDA Graph，与网关声明对照；不保存引擎中的API凭据。原始答案、期望值、失败、输入、源码SHA与工作区状态均保留。不完整执行返回非零；完整但有错误同样返回非零，`complete=true/all_correct=false`。这里没有SLO或正式分数。

不同路径请求可能有不同的batch/cache历史。仅凭两次独立请求输出不同，不能断定网关串流错误；需要再看受控传输测试、具体调度及重复性。直连用于诊断，不取代经鉴权和计费的正式性能测量。

## 可选精度对照，默认不启用

已核对[SGLang v0.5.9启动参数](https://github.com/sgl-project/sglang/blob/v0.5.9/python/sglang/srt/server_args.py)和[logits_processor](https://github.com/sgl-project/sglang/blob/v0.5.9/python/sglang/srt/layers/logits_processor.py)：`--enable-fp32-lm-head`把最终词表投影的hidden state和weight临时转为FP32做矩阵乘法。项目通过 `FP32_LM_HEAD=1` 显式选择；未设置或为0时行为不变。模型身份、BF16权重加载及中性采样不变，额外显存和耗时需要实测。切换该变量会改变setup指纹并重启自有服务，避免误复用旧进程；`/info.config.fp32_lm_head`如实声明。

这是有源码依据的候选对照，不保证改变错误答案，也不等于全面确定性推理。不能未测就默认启用或宣称已解决。SGLang另有确定性模式，但在0.5.9中FlashInfer搭配该模式会自动关闭Radix Cache；不能直接加该开关后仍声称缓存配置未变。[确定性说明](https://docs.sglang.io/docs/advanced_features/deterministic_inference)。

公司实测已否定“只打开FP32输出层就能修复这两处错误”的假设：原始FlashInfer/FP32 head off的short两路径均45/48、long网关45/48/直连48/48；FP32 head on的两个归档分组在两路径均45/48；Triton/head off同样均45/48。四个路径的新seed控制各48/48，但不能抵消归档错误。直接请求引擎非流式接口时，两个错误也都存在，排除本项目SSE拼接是这两次非流式错误的原因。

另提供默认关闭的`TRITON_ATTENTION_REDUCE_IN_FP32`和`DETERMINISTIC_INFERENCE`，分别映射同版官方参数。前者仅允许Triton；后者在FlashInfer+prefix on时拒绝启动该配置，防止引擎自动关闭缓存却仍声明缓存打开。两项都进入setup指纹，并在诊断中核对引擎实际参数，单独设置进行对照，不提前认定有效：

```bash
ATTENTION_BACKEND=triton FP32_LM_HEAD=0 TRITON_ATTENTION_REDUCE_IN_FP32=1 bash scripts/gpu_validate.sh diagnose
ATTENTION_BACKEND=triton FP32_LM_HEAD=0 DETERMINISTIC_INFERENCE=1 bash scripts/gpu_validate.sh diagnose
```

在已配置私密环境和独立benchmark Python的兼容4090服务器上，依次执行：

```bash
set -a
source .env
set +a
export LLM_TEST_ENVIRONMENT=self-managed
export BENCH_PYTHON="$PWD/.venv-benchmark/bin/python"

# 对照：现有输出层精度；有内容错误时脚本返回非零并保存数据
FP32_LM_HEAD=0 bash scripts/gpu_validate.sh diagnose

# 候选：仅改变最终词表投影精度；同样保留失败
FP32_LM_HEAD=1 bash scripts/gpu_validate.sh diagnose

# 只有候选通过后才值得运行完整矩阵；新seed验证泛化，不拟合门槛
FP32_LM_HEAD=1 BENCH_SEED=20261106 bash scripts/gpu_validate.sh bench

# 对照结束恢复当前默认配置
FP32_LM_HEAD=0 BENCH_PROFILE=optimized bash setup.sh
```

诊断通过也不能替代完整矩阵。若候选仍错，保留负结果，再逐项对照attention后端、CUDA Graph、cache冷/热与批次形状；不要同时改变多个因素或按已知输入特殊处理。修复有效必须由新完整SHA上的新GPU数据证明，正式四组每组仍需48/48正确，且八项指标同时满足。生产默认配置尚未选择候选。

## 公司服务器的真实前置检查

2026-11-05经用户提供的SSH配置连接成功，内核驱动设备记录明确显示NVIDIA GeForce RTX4090，`GPU Excluded: No`。首次加载驱动580.173.02，磁盘模块及NVML/libcuda为580.178.04，系统存在restart-required标记；nvidia-smi退出18，CUDA初始化返回804。显卡存在，驱动栈暂不可用。初次检查只读，未替换驱动或部署服务。[原始脱敏报告](../results/environment/self-managed-20261105/preflight.json)。

默认Python3.10.12、未发现PATH中的3.12或三个运行库；存在CUDA12.4工具链，后续需准备隔离Python3.12并实测JIT兼容性。应由管理员确认维护窗口后重启，检查已加载/已安装驱动对齐、nvidia-smi和CUDA分配恢复，再部署本项目。CUDA804属于不受支持的兼容配置错误，不能仅根据它假定GPU已不存在。[NVIDIA错误说明](https://docs.nvidia.com/deploy/cuda-compatibility/forward-compatibility.html)。

用户随后自行重启服务器。本机重新连接确认RTX4090/24564MiB、空闲24041MiB、GPU利用率0%，已加载驱动对齐580.178.04，CUDA初始化返回0；8000/30000端口空闲。见[重启后报告](../results/environment/self-managed-20261105/post-reboot.json)。驱动恢复不代表LLM测试已通过；隔离环境和模型准备后，仍须实际运行上述诊断及完整性能复测。
