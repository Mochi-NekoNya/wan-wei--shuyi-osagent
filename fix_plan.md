# 架构修复计划

## Issue #88 【核心链路】_chat_request_context 拍平截断问题
- 文件：backend/app/app_runtime.py
- 函数：_chat_request_context (行1438)
- 修复：保留角色标签的结构化截断；system/soul提示永远保留；从最早的user消息开始截断
- 回归测试：test_issue88_structured_context_truncation

## Issue #90 【架构】main.py sys.modules自替换
- 文件：backend/app/main.py
- 修复：移除sys.modules自替换，改为显式re-export app_runtime关键符号
- 更新测试：所有monkeypatch backend.app.main 的测试改为 monkeypatch backend.app.app_runtime
- 回归测试：test_issue90_main_no_sys_module_alias

## Issue #91 【架构】app_runtime.py 单文件承载102条路由
- 文件：backend/app/app_runtime.py
- 修复：按功能域拆分为多个APIRouter子模块
  - routers/system.py: /health, /health/*, /metrics, /arena/*, /kylin/*
  - routers/memory.py: /memory/* (legacy & v2), /forget/*
  - routers/soul.py: /soul/*
  - routers/platform.py: /platform/*, /model-gateway/*, /tool-registry/*, /tuning/*, /exports/*
  - routers/workflow.py: /workflow/*
  - routers/research.py: /research-adoption/*, /reproduction/*, /deepening/*
  - routers/memoryos.py: /memoryos/*
- app_runtime.py中统一mount各router
- 回归测试：test_issue91_router_split_smoke

## Issue #92 【健壮性】assert + 全仓宽捕获except Exception
- 文件：多个
- 修复：
  1. app_runtime.py: assert soul_scope is not None → 显式HTTPException
  2. app_runtime.py: except Exception: 分类处理
  3. 扫描全仓assert和except Exception，逐一替换
- 回归测试：test_issue92_assert_replaced, test_issue92_narrow_except

## 执行顺序
1. #90 → #88 → #92 → #91 (由小到大，避免冲突)
2. 每个issue修复后运行pytest验证
3. 最终统一提交git
