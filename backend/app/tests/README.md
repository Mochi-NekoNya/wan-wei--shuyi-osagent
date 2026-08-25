# 测试目录说明

本目录包含后端 pytest 测试套件。测试文件采用两种命名风格并存：

## 按模块/行为组织的测试（推荐新文件遵循）

| 文件 | 覆盖模块/行为 |
|---|---|
| `test_capsule_store.py` | 胶囊存储 CRUD |
| `test_command_loop.py` | 命令循环 |
| `test_memoryos_*.py` | MemoryOS 治理层（lifecycle / governance / accounting / health / harness / api） |
| `test_platform_api_smoke.py` | 万枢平台八模块冒烟 |
| `test_security_baseline.py` / `test_security_followup.py` | 安全基线与回归 |
| `test_retrieval.py` | 检索服务 |
| `test_affect_*.py` | 情感检测与绑定 |
| `test_automation_real_exec.py` | 自动化真实执行与 gear 门禁 |
| `test_ssrf_extra_hosts_unification.py` | SSRF 白名单单源化 |
| `test_mcp_sse_http_transports.py` | MCP SSE/HTTP 传输 |

## 工单式命名测试（历史保留，不改文件名以保持追溯）

以下 `test_fix_wNN.py` 和 `test_issueNN_*.py` 文件对应特定工单或 issue 的回归测试：

| 文件 | 来源工单/issue | 主要覆盖 |
|---|---|---|
| `test_fix_w01.py` | W01 | 初始安全修复批次 |
| `test_fix_w02.py` | W02 | 初始安全修复批次 |
| `test_fix_w03.py` | W03 | 初始安全修复批次 |
| `test_fix_w04.py` | W04 | 初始安全修复批次 |
| `test_fix_w05.py` | W05 | 初始安全修复批次 |
| `test_fix_w06.py` | W06 | 初始安全修复批次 |
| `test_fix_w07.py` | W07 | 初始安全修复批次 |
| `test_fix_w08.py` | W08 | 初始安全修复批次 |
| `test_fix_w09.py` | W09 | 初始安全修复批次 |
| `test_fix_w14_build.py` | W14 | 构建与打包 |
| `test_fix_w15_decay_lost_update.py` | W15 | 情感衰减并发丢失更新 |
| `test_fix_w15_spaces_path_traversal.py` | W15 | 空间路径遍历防护 |
| `test_fix_w16_knowledge_xss.py` | W16 | 知识库 XSS 防护 |
| `test_fix_w16_normalize_session.py` | W16 | 会话规范化 |
| `test_fix_w17_policy_gate_bypass.py` | W17 | 策略门绕过修复 |
| `test_fix_w18_redact_not_sanitized.py` | W18 | 脱敏未净化修复 |
| `test_fix_w19_affect_body_validation.py` | W19 | 情感请求体验证 |
| `test_fix_w20_soul_ownership.py` | W20 | Soul 所有权隔离 |
| `test_fix_w21_reflection_authorization.py` | W21 | 反思授权 |
| `test_issue38_platform_batch_b.py` | #38 | 平台批量 B 安全修复 |
| `test_issue38_resilience_batch_c.py` | #38 | 韧性 C 批次修复 |
| `test_issue45_gateway_honest_failure.py` | #45 | 网关诚实失败 |
| `test_issue45_loopback.py` | #45 | 回环地址处理 |
| `test_issue45_plan_verify.py` | #45 | 计划验证 |

> **注意**：为避免破坏 Git 历史追溯与现有 CI 引用，工单式命名文件**不计划批量重命名**。
> 新测试请按模块/行为命名；若需查找某 issue 的回归测试，可检索本表。
