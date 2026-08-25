# 宛委·枢忆 系统性修复计划

> 目标：修复 30 个开放 GitHub issue + AI优化目录需求落地
> 当前 main: 3e0afa8 | 本地修改: 12 个文件（GLM 未完成提交）

## 一、现状盘点

### 1.1 GLM 已做但未提交（7 个 issue 有代码改动）
| Issue | 文件 | 状态 |
|-------|------|------|
| #89 知识库中文查询拆为单字 OR | `knowledge.py`, `retrieval.py` | 代码完成，需测试+提交 |
| #116 Policy Gate 凭据格式不可见 | `policy_gate.py`, `redaction.py` | 代码完成，需测试+提交 |
| #117 reflection 无上限 | `schemas.py`, `evolution.py` | 代码完成，需测试+提交 |
| #118 检索排序公式无查询项 | `retrieval.py`, `tuning/service.py` | 代码完成，需测试+提交 |
| #119 FTS5 tokenizer | `knowledge.py`, `retrieval.py` | 代码完成，需测试+提交 |
| #133 CJK+ASCII 混排丢弃 | `knowledge.py`, `utils/cjk_text.py`(新增) | 代码完成，需测试+提交 |
| #136 LIKE 降级无上限 | `knowledge.py` | 代码完成，需测试+提交 |

### 1.2 尚未修复的 23 个 issue

**集群A：安全/权限/敏感数据（8个）**
- #115 桌面端 dev 分支密钥 = PBKDF2(API key)
- #120 空库 GET /memory/health 返回满分
- #122 桌面端 localStorage 存 API key
- #126 smoke 脚本默认 api key 是公开常量
- #128 agents run 无归属校验
- #129 provider extra 明文回显
- #130 LAN token 泄露（URL 带 token、明文落盘）
- #132 MCP stdio 帧长度无上限

**集群B：架构/文档/卫生（11个）**
- #88 soul-chat 被 smoke 路径钳制 + [-4000:] 截断
- #90 main.py sys.modules 自替换
- #91 app_runtime.py 102 条路由拆分
- #92 assert 收窄 + 全仓宽 except Exception 清单
- #93 token 估算系数参与阈值（文档澄清）
- #94 工单式测试文件命名迁移
- #95 仓库卫生（reports/13%、web-console化石、4937行文档）
- #96 CHANGELOG 日记腔；README 品牌叙事先于 Quick Start
- #124 README local_mock 失效指引
- #125 PROJECT_AUDIT_MANIFEST 过期
- #127 REVIEW.md 要求提交 dist 但 .gitignore 忽略

**集群C：前后端对接与API契约（4个）**
- #123 双模块身份（backend.app.* vs app.*）
- #134 mobile upload 全量入内存再判 50MB
- #135 spaces 读路径不复核 root_path 白名单
- #137 前端只认字符串 detail，client.ts 整份丢弃 body

## 二、执行阶段

### Stage 1：GLM 工作收尾（提交已完成的 7 个 issue）
1. 确认新文件 `utils/cjk_text.py` 存在且被追踪
2. 运行本地测试确认改动不破坏现有测试
3. 提交并推送

### Stage 2：安全集群并行修复（8个子代理）
每个安全 issue 一个子代理，独立可并行。

### Stage 3：架构/文档集群并行修复（11个子代理）
每个 issue 或相关 issue 组一个子代理。

### Stage 4：API契约集群并行修复（4个子代理）
前后端对接问题，可并行。

### Stage 5：AI优化需求落地
MemoryOS 规范对接：
- Health 空库守卫（#120 已在此阶段处理）
- Governance 账本完整接入 capsule_store
- Accounting 经济账本 hook 接入
- Lifecycle 状态机完整性校验

### Stage 6：验证与回归
1. 全量 pytest 通过
2. 新增回归测试覆盖本次修复
3. 更新 CHANGELOG

## 三、关键依赖

```
Stage 1 (GLM收尾)
    │
    ├──→ Stage 2A (安全集群) ──┐
    │                          │
    ├──→ Stage 2B (架构集群) ──┤→ Stage 3 (验证)
    │                          │
    └──→ Stage 2C (API契约) ───┘
```

所有集群内部无依赖，可全并行；Stage 3 需等待全部完成。
