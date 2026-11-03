# 提交目录与验收核对

此清单记录交付状态，不代替平台正式评测。GPU 数据与正式结论尚未取得。

| 核对项 | 路径/依据 | 当前状态 |
|---|---|---|
| 根 setup 固定合同 | setup.sh；native_setup.py；--contract-test / --stop | CPU 实际启动/幂等/恢复通过；GPU native 待执行 |
| 锁定依赖与模型 | requirements.lock / runtime / native-linux-py312 / tokenizer / analysis；两个固定模型 revision | CPU 安装与 pip check 通过；GPU 闭包实装待验证 |
| baseline / optimized | configs/*.yaml；/info；supervisor.engine_command | CPU 参数/命令检查通过；GPU 性能未验证 |
| 网关、SSE、队列与取消 | server/；真实 socket/Event 测试 | CPU 通过；GPU 取消与显存恢复待执行 |
| 多租户 Key、轮换、记账、额度、恢复 | control_plane/；migrations/；pricing.json | 本地 CPU/HTTP/两窗口 SIGKILL 通过；正式15项黑盒及 live 门槛未运行 |
| 管理页面 | console/index.html；scripts/check_console.cjs | 本地Chromium13项核心交互通过；GPU用量与其他浏览器待验证 |
| Agent 父子账本与白名单 | agent/；server/app.py；CPU 请求校验与调用轨迹测试 | CPU 协议/模拟调用通过；真实模型推理待验证 |
| 18 项软诊断 | .github/workflows/llm-soft.yml；GitHub artifact | 已在公开 main 成功运行，按完整 SHA 对应记录 |
| 公开自测与压测 | scripts/check_control_plane.py；benchmarks/；fetch_public_tools.py | HTTP mock 与工具哈希通过；完整768请求 GPU矩阵未执行 |
| 三项机制入口 | experiments/run.sh --case kv/prefix/attention --out ... | 源码与当前矩阵校验器就绪；GPU 原始数据、数值与算子待执行 |
| 真实结果与图表 | results/；docs/test-records.md / performance.md | 已保存 CPU 原始失败/通过记录；没有复制参考 GPU 图表或成绩 |
| 一键复现/职责/排障 | README；implementation-plan.md；SOURCES.md | 已说明路径对应、环境、恢复、价格与密钥规则 |
| 隐私与产物排除 | .gitignore；凭据模式扫描；私有运行目录 | 不提交环境凭据、SSH临时命令、账本、权重、venv或浏览器下载 |
| 公开仓库与完整提交 | https://github.com/ThingsWorld/llm-service | GitHub 已确认公开；具体 SHA 与运行见测试记录和 Git HEAD |
| 最终性能/评分/人工验收 | 平台本人正式报告 | 未提交正式 GPU 评测；不编造最终分数 |

最终 GPU 阶段完成后，还需逐一核对 manifest.commit、相同输入对照、失败分母、配置哈希、运行环境、所有 skipped/unknown/null 状态、服务重建、用户账单、原始记录与图表，再填写最终完整40位提交 SHA。提交清单尚不代表项目整体完成。
