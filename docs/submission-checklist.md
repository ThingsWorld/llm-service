# 提交目录与验收核对

此清单记录交付状态，不代替平台正式评测。Daytona练习GPU数据已返回并复核，存在正确率失败；正式结论尚未取得。

| 核对项 | 路径/依据 | 当前状态 |
|---|---|---|
| 根 setup 固定合同 | setup.sh；native_setup.py；--contract-test / --stop | 练习GPU服务与profile切换已运行；完整setup stdout缺失，正式洁净快照重建待验证 |
| 锁定依赖与模型 | requirements.lock / runtime / native-linux-py312 / tokenizer / analysis；两个固定模型 revision | CPU安装通过；GPU报告torch2.9.1/Transformers4.57.1/SGLang0.5.9，完整native freeze待补 |
| baseline / optimized | configs/*.yaml；/info；supervisor.engine_command | 完整768请求与原始数据已复核；四目标组三通过，long/C16正确率失败 |
| 网关、SSE、队列与取消 | server/；真实 socket/Event 测试 | GPU流式计时齐全；20次取消、网关及引擎abort计数、队列归零；显存回收时间线待补 |
| 多租户 Key、轮换、记账、额度、恢复 | control_plane/；migrations/；pricing.json | CPU及GPU双用户live/轮换/账单通过；正式15项私有黑盒未运行 |
| 管理页面 | console/index.html；scripts/check_console.cjs | 本地Chromium13项核心交互通过；GPU用量与其他浏览器待验证 |
| Agent 父子账本与白名单 | agent/；server/app.py；CPU 请求校验与调用轨迹测试 | GPU双用户真实Agent父子账本HTTP断言通过；正式检查待运行 |
| 18 项软诊断 | .github/workflows/llm-soft.yml；GitHub artifact | 已在公开 main 成功运行，按完整 SHA 对应记录 |
| 公开自测与压测 | scripts/check_control_plane.py；benchmarks/；fetch_public_tools.py | Daytona768测量+96预热已重算；公司6配置对照仍未修复内容错误，首次客户端工具缺陷单独保留 |
| 三项机制入口 | experiments/run.sh --case kv/prefix/attention --out ... | GPU KV12/Attention18/Prefix96行证据通过；Prefix专用SLO待确认 |
| 真实结果与图表 | results/；docs/test-records.md / performance.md | Daytona原始数据/6份trace/3图及公司7次原始诊断、CPU复核JSON/CSV、负结果和复现说明已归档 |
| 一键复现/职责/排障 | README；implementation-plan.md；SOURCES.md | 已说明路径对应、环境、恢复、价格与密钥规则 |
| 隐私与产物排除 | .gitignore；凭据模式扫描；私有运行目录 | 不提交环境凭据、SSH临时命令、账本、权重、venv或浏览器下载 |
| 公开仓库与完整提交 | https://github.com/ThingsWorld/llm-service | GitHub 已确认公开；具体 SHA 与运行见测试记录和 Git HEAD |
| 最终性能/评分/人工验收 | 平台本人正式报告 | 未提交正式 GPU 评测；不编造最终分数 |

最终 GPU 阶段完成后，还需逐一核对 manifest.commit、相同输入对照、失败分母、配置哈希、运行环境、所有 skipped/unknown/null 状态、服务重建、用户账单、原始记录与图表，再填写最终完整40位提交 SHA。提交清单尚不代表项目整体完成。
