# 固定样本的输入、采样与独立推理复核

**两处内容错误仍未修复，没有合格发布候选，未提交正式评测。** 这里是公司 RTX4090 的诊断证据，不是正式分数或完整性能矩阵。

源码 checkout 为 `f8582900e8210eb44b433f93d6743d7422424347`；额外探针保存在每个 `raw/*/probe.py`，与运行报告的 SHA-256 逐个核对。探针不属于该 checkout 中已经提交的生产代码。固定模型、revision、BF16 权重及原始两例输入不变。独立 HF 探针不启用 JSON grammar；它们仅用于诊断。

| 完整对照 | short-3 | long-12 |
| --- | --- | --- |
| SGLang Chat 默认参数 | 错 | 错 |
| SGLang Chat 显式中性采样 | 错 | 错 |
| SGLang native canonical input_ids，保持 JSON 约束 | 错 | 错 |
| SGLang Chat 加 logprobs | 错 | 错 |
| 独立 HF eager | 对 | 错，且产生更多字段错误 |
| 独立 HF SDPA | 错 | 错 |
| HF SDPA 强制 MATH | 错 | 错 |
| HF eager attention 中间值 FP32，输出 BF16 | 错 | 错 |
| HF 禁止 BF16 matmul 低精度归约 / eager | 错 | 错 |
| 同上 / SDPA | 错 | 错 |
| HF FP32 残差 / eager | 对 | 错 |
| 同上 / SDPA | 错 | 错 |

新旧客户端 tokenizer 生成的完整 token IDs **完全相同**，分别 512/1024；直接给定 canonical IDs 也仍错，未观察到输入截断或 chat-template 版本差异导致这两处错误。实际引擎为 `sampling_defaults=openai`，显式指定 rep=1、top_p=1、top_k=-1 也不改变结果。

logprobs 显示短任务在输出 `91` 后选择 `7`，其对数概率比正确的下一个 `1` 高约1.625；长任务最后一项 units 选择 `8`，比正确的 `7` 高1.0。温度0贪心选择会取较高者，错误已经出现在生成决策中。**不能据此断言所有上游引擎问题都已排除，也不能证明调整某种精度必然修复。** 原始候选与计算见 [review.json](review.json)。

完整 SGLang 输入/采样探针8次、0正确；完整独立HF对照16次、2正确。这只是两个固定输入的重复，不能把2/16当作通用模型正确率，或把偶然正确的短样本作为发布证明。精度/残差变体仅改变中间算术，未改生产默认。

不完整运行也保留：

- `input-sampling-control-v1`：完成7次生成后，上一个请求内部清理尚未结束，flush_cache返回400，`complete=false`。v2只为flush增加5秒有界等待，没有重试生成或覆盖数据。
- `independent-hf-control-v1`：device_map需要未安装的accelerate，0次生成。v2改为普通加载后`.to(cuda)`，没有改变锁定依赖。
- `independent-hf-control-v5`：FP32残差探针的RoPE输出提升导致线性层dtype不匹配，0次生成；v6保留BF16 RoPE后完成。这是探针错误，不算模型答错。

共8个控制目录，5个完整、3个不完整；实际完成31次生成、2次正确，完整且全部正确的控制为0。最后只退出自有进程；[真实清理检查](raw/cleanup.log)显示8000/30000无监听，GPU空闲24041 MiB、利用率0%。未关机或修改驱动。

本机执行：

```bash
.venv-benchmark/bin/python results/gpu/accuracy-causal-review-20261105/review.py
```

实际输出：`integrity_pass=true, controls=8, completed_generations=31, correct=2, all_correct_controls=0`。脚本重比原始输入、canonical IDs、生成token、严格答案、响应与探针hash，保存逐文件hash。完整性通过不表示正确率通过，也没有独立GPU认证。

额外GPU重放需要兼容的已安装锁定运行时与完整固定模型缓存，专用空闲4090、8000/30000均无监听；不与其他服务同时运行。把`raw/input-cases.json`放到`~/.cache/llm-accuracy-tools/input-sampling-cases.json`，从项目根目录用native `.venv/bin/python`执行所选`raw/*/probe.py`。脚本的目标输出目录必须不存在；保留原始运行时不要覆盖，不能把两个手工探针当作完整验收。

仍须找到合法修复，在新提交上完成受影响完整分组、新输入、完整矩阵与发布回归，才可使用已推送的40位SHA正式评测。当前没有这样的SHA。不能以答案替换、改种子或删难例交付“修复”。
