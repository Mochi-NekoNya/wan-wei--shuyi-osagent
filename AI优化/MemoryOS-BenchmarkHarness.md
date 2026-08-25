# Memory Benchmark Harness 设计

> 来源：6.docx P2 建议 + 3.docx 评测体系
> 状态：设计草案 + 代码骨架，供浅唱审阅
> 日期：2026-08-20

## 1. 目标

把 MEB/MHEB 从"想法"变成"可运行 harness"。四类文件 + 自动 runner + 隐藏集。

```
memory_case.json      -- 测试用例（公开）
memory_trace.json     -- 检索/写入 Trace（诊断用）
memory_incident.json  -- 事故记录（Harm 用）
score_report.json     -- 评分报告（输出）
```

## 2. 文件 Schema

### 2.1 memory_case.json

```json
{
  "case_id": "MEB-001",
  "category": "preference_extraction | knowledge_recall | conflict_update | forgetting | poisoning",
  "title": "用户偏好：咖啡口味",
  "setup": [
    {"role": "user", "content": "记住，我只喝美式，不要加糖"}
  ],
  "queries": [
    {
      "id": "q1",
      "question": "我想喝咖啡，帮我点单",
      "expected": {"must_contain": ["美式"], "must_not_contain": ["拿铁", "糖"]},
      "eval": "contains"
    }
  ],
  "negative_cases": [
    {"query": "帮我推荐甜食", "expected_must_not_contain": ["美式"]}
  ],
  "timeout_s": 30,
  "tags": ["preference", "basic"]
}
```

### 2.2 memory_trace.json（每次检索必存）

```json
{
  "trace_id": "trc_abc123",
  "timestamp": "2026-08-20T12:00:00Z",
  "query": "帮我点咖啡",
  "query_rewrite": ["咖啡 美式 偏好"],
  "candidates": [
    {"capsule_id": "cap_1", "score": 0.92, "stage": "fts"},
    {"capsule_id": "cap_2", "score": 0.75, "stage": "vector"}
  ],
  "filters_applied": ["owner=user_1", "state=active"],
  "rerank": {"final": ["cap_1", "cap_2"], "method": "rrf"},
  "injected": ["cap_1"],
  "llm_response": "好的，为您点一杯美式",
  "latency_ms": 45,
  "tokens_used": 128
}
```

### 2.3 memory_incident.json

```json
{
  "incident_id": "inc_001",
  "mhg_level": 3,
  "type": "leakage | poisoning | deletion_failure | conflict_escalation",
  "description": "敏感记忆被注入到错误 scope",
  "trigger": {"query": "...", "capsule_id": "cap_9"},
  "detected_by": "policy_gate | red_team | user_report",
  "actions": ["publish_freeze"],
  "recovery": {"rollback_to": "led_xx", "verified": true}
}
```

### 2.4 score_report.json（runner 输出）

```json
{
  "benchmark": "MEB",
  "run_id": "run_20260820_01",
  "timestamp": "2026-08-20T12:00:00Z",
  "summary": {
    "total_cases": 100,
    "passed": 87,
    "failed": 13,
    "pass_rate": 0.87
  },
  "weights": {"ux": 0.40, "safety": 0.25, "product": 0.25, "academic": 0.10},
  "scores": {
    "ux_value": 0.85,
    "safety_harm_inverse": 0.90,
    "product_capability": 0.80,
    "academic_alignment": 0.70,
    "mheb_overall": 0.825
  },
  "category_breakdown": {
    "preference_extraction": {"pass": 20, "total": 25, "rate": 0.80},
    "knowledge_recall": {"pass": 25, "total": 25, "rate": 1.00},
    "conflict_update": {"pass": 15, "total": 20, "rate": 0.75},
    "forgetting": {"pass": 17, "total": 20, "rate": 0.85},
    "poisoning": {"pass": 10, "total": 10, "rate": 1.00}
  },
  "failures": [
    {"case_id": "MEB-003", "reason": "conflict not detected", "trace": "trc_xyz"}
  ],
  "economics": {
    "tokens_per_useful_recall": 128,
    "avg_latency_ms": 45,
    "compression_gain": 3.2
  }
}
```

## 3. Runner 骨架

```python
# memory_bench_runner.py
"""MEB/MHEB 评测 runner 骨架"""
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime, timezone


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    reason: str = ""
    trace_id: str = ""


class MemoryBenchRunner:
    """跑一个用例集，输出 score_report.json"""

    def __init__(self, harness: object, cases_path: Path, output_dir: Path):
        """
        harness: 被测记忆系统接口，需要实现:
            - write_setup(messages)        写入 setup 对话
            - query(question) -> dict      返回 {"text": 回答, "trace": {...}}
            - forget(capsule_id)           删除
        """
        self.harness = harness
        self.cases = json.loads(cases_path.read_text(encoding='utf-8'))
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _check_contains(self, answer: str, expected: dict) -> bool:
        must = expected.get('must_contain', [])
        must_not = expected.get('must_not_contain', [])
        if any(m not in answer for m in must):
            return False
        if any(m in answer for m in must_not):
            return False
        return True

    def run_case(self, case: dict) -> CaseResult:
        """单个用例：写入 setup → 跑 queries → 断言。"""
        # 1. setup
        for msg in case.get('setup', []):
            self.harness.write_setup(msg['content'])

        # 2. queries
        for q in case.get('queries', []):
            resp = self.harness.query(q['question'])
            answer = resp['text']
            expected = q.get('expected', {})
            if not self._check_contains(answer, expected):
                return CaseResult(case['case_id'], False, f"query {q['id']} 断言失败", resp.get('trace_id', ''))
            self._save_trace(resp.get('trace'))

        # 3. negative cases
        for neg in case.get('negative_cases', []):
            resp = self.harness.query(neg['query'])
            if any(m in resp['text'] for m in neg.get('expected_must_not_contain', [])):
                return CaseResult(case['case_id'], False, f"negative case 泄漏", resp.get('trace_id', ''))

        return CaseResult(case['case_id'], True)

    def run_all(self) -> dict:
        """跑全部用例，生成 score_report.json。"""
        results = []
        for case in self.cases:
            try:
                results.append(self.run_case(case))
            except Exception as e:
                results.append(CaseResult(case['case_id'], False, f"异常: {e}"))

        passed = sum(1 for r in results if r.passed)
        total = len(results)
        report = {
            "benchmark": "MEB",
            "run_id": f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "summary": {"total_cases": total, "passed": passed, "failed": total - passed,
                        "pass_rate": round(passed / total, 4) if total else 0},
            "weights": {"ux": 0.40, "safety": 0.25, "product": 0.25, "academic": 0.10},
            "failures": [asdict(r) for r in results if not r.passed],
        }
        out = self.output_dir / 'score_report.json'
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return report

    def _save_trace(self, trace: dict):
        if trace:
            (self.output_dir / f"memory_trace_{trace.get('trace_id', 'unknown')}.json").write_text(
                json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')


# --- 适配器示例：对接宛委·枢忆 ---
class WanweiHarness:
    """把宛委·枢忆的 API 包成 runner 需要的接口。"""

    def __init__(self, base_url: str, api_key: str):
        import urllib.request
        self.base_url = base_url
        self.api_key = api_key

    def write_setup(self, content: str):
        # POST /memory/capsules 或对话接口
        pass

    def query(self, question: str) -> dict:
        # POST /memory/retrieve 或对话接口，返回 {"text": ..., "trace": {...}}
        pass

    def forget(self, capsule_id: str):
        # POST /memory/forget/confirm
        pass


if __name__ == '__main__':
    # 示例：跑公开集
    cases = Path('cases/public/')
    runner = MemoryBenchRunner(WanweiHarness('http://127.0.0.1:8000', 'key'), cases / 'memory_case.json', Path('reports/'))
    report = runner.run_all()
    print(json.dumps(report['summary'], indent=2))
```

## 4. CI/CD 设计

| 频率 | 任务 | 内容 |
|------|------|------|
| 每 PR | Mini-MEB | 20 个核心用例（preference/recall/conflict/forgetting/poisoning 各 4） |
| 每日 | Long-MEB | 100 个公开用例 + 生成 score_report |
| 每周 | RedTeam-MEB | 投毒/泄漏/删除残留红队用例 |
| 每月 | Benchmark Sync | 同步 hidden set + 更新基线 |

## 5. 验收标准

- [ ] 一个 `pytest` 命令可跑完 Mini-MEB
- [ ] 每次失败都有 trace_id 可查
- [ ] score_report.json 可被 CI 解析并对比基线（pass_rate 下降 >5% 报警）
- [ ] hidden set 与 public set 分离（防过拟合）
