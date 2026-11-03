# 源码与证据来源

本项目使用任务书明确指定的公开参考源码作为底座：

- 仓库：https://github.com/mrvgao/agentist-llm-reference
- 固定提交：`9961c0503c2eb3fa702794ef9281dd88f96d9456`
- 初次导入的文件与原始 SHA-256：`docs/source-import.json`。
- 导入范围：网关、管理服务、Agent、实验、公开 benchmark、CPU 测试与依赖锁；后续修改由本仓库 Git 记录追溯。没有导入参考仓库的 results、成绩或历史性能文档。

CPU workflow 直接下载自任务书指定的 https://agentist.org/lab/llm-lab/soft/llm-soft.yml ，初始 SHA-256 `6b0a537c5af8b85af76e4ac0622ba0c4649883844997244966e8db97c1ba043d`，保留官方文件的完整字节。工作流使用 GitHub 托管 CPU runner，固定 Actions commit 与公开检查器 SHA-256；只生成临时凭据，无 GPU 申请能力。

`benchmarks/acceptance.json` 从用户提供任务书第四部分逐字节提取，SHA-256 `d5cd2fdc90056e710cf741ac1eec4c5b042ea3818d505e4a3975697f1df9241f`。其中 calibration/confirmation 数据属于平台参考阈值来源，不能作为本项目实测。本项目的新测试只写在 `results/`，标明本地 CPU、GitHub CPU 或 Daytona GPU 环境及提交身份。

SGLang、PyTorch、Transformers、FastAPI、httpx、模型与其余依赖遵循各自许可证；权重不随仓库分发。FlashInfer 服务后端与独立 PyTorch FlashAttention 实验分别记录。不得将本地公开检查器或可修改报告作为官方成绩。
