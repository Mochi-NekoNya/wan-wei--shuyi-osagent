"""``meb_score_report.json`` 的校验契约。

与 ``app/memory_arena/metrics_contract.py`` 同款形状与用法（``main()`` 读 stdin、
返回稳定错误码），这样 CI 里两份报告的校验步骤写法一致。

存在意义：报告是给 CI 门禁和控制台消费的。字段缺失或比率越界时，要在**产出时**
就失败，而不是等面板渲染出一个 ``undefined`` 才发现。
"""

from __future__ import annotations

import json
import sys
from typing import Any

#: 五类评测（规范 BenchmarkHarness §2.1 的 category 取值）。
CATEGORIES = (
    "preference_extraction",
    "knowledge_recall",
    "conflict_update",
    "forgetting",
    "poisoning",
)

#: MHEB 四个加权维度（规范 Harm×Economics §3）。
DIMENSIONS = ("ux", "safety", "product", "academic")

#: MHEB 权重。和必须为 1。
MHEB_WEIGHTS: dict[str, float] = {
    "ux": 0.40,
    "safety": 0.25,
    "product": 0.25,
    "academic": 0.10,
}

#: MQ（Memory Quotient）五个子能力 → 承载它的用例类别（规范 IQMQ双轴框架 §10.3）。
#:
#: 这不是新造一套评测，而是给已有的 5 个类别换一个**能力视角**的读法：
#: category_breakdown 回答「这类用例过了几条」，MQ 回答「记忆全生命周期里的哪一环
#: 弱」。两者数据同源，因此不会出现互相矛盾的两个分数。
#:
#: 映射是 1:1 的，这是规范设计如此而非巧合——五类用例本就按记忆生命周期切分。
MQ_SUBSKILLS: dict[str, str] = {
    "write_precision": "preference_extraction",
    "retrieval_efficiency": "knowledge_recall",
    "update_correctness": "conflict_update",
    "forgetting_control": "forgetting",
    "safety_governance": "poisoning",
}

#: MQ 子能力权重。和必须为 1。
#:
#: 安全治理权重最高（0.30）：一条被投毒的记忆造成的损害不与「少记住一条偏好」
#: 对称——前者会让 Agent 主动做错事，后者只是体验差一点。这与 MHEB 里
#: safety 一票否决的取向一致。写入精度权重最低（0.15）：写漏了还能再问一次，
#: 而更新错误与遗忘失控都会留下一条**错误但可被召回**的记忆，更难被发现。
MQ_WEIGHTS: dict[str, float] = {
    "write_precision": 0.15,
    "retrieval_efficiency": 0.20,
    "update_correctness": 0.20,
    "forgetting_control": 0.15,
    "safety_governance": 0.30,
}

_COUNT_FIELDS = ("total_cases", "passed", "failed")
_REQUIRED_RATE_FIELDS = ("pass_rate",)
#: 允许为 ``null`` 的比率字段：没有实测数据时必须如实为空，
#: 不接受用占位数字填满报告（REVIEW.md 把「模拟当实测」列为阻断级问题）。
_NULLABLE_RATE_FIELDS = ("retrieval_precision_at_5", "retrieval_recall_at_5")


def _is_rate(value: Any, *, allow_null: bool = False) -> bool:
    if allow_null and value is None:
        return True
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 <= value <= 1
    )


def score_report_validation_error(payload: object) -> str | None:
    """校验 MEB 报告。合法返回 ``None``，否则返回稳定错误码。"""
    if not isinstance(payload, dict):
        return "expected_object"

    for field in ("benchmark", "run_id", "timestamp", "suite"):
        if not isinstance(payload.get(field), str) or not payload[field]:
            return f"missing_field:{field}"

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return "missing_field:summary"
    for field in _COUNT_FIELDS:
        value = summary.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return f"invalid_count:summary.{field}"
    if summary["passed"] + summary["failed"] != summary["total_cases"]:
        return "summary_counts_mismatch"
    for field in _REQUIRED_RATE_FIELDS:
        if not _is_rate(summary.get(field)):
            return f"invalid_rate:summary.{field}"
    expected_pass_rate = round(summary["passed"] / max(summary["total_cases"], 1), 4)
    if round(float(summary["pass_rate"]), 4) != expected_pass_rate:
        return "pass_rate_mismatch"

    weights = payload.get("weights")
    if not isinstance(weights, dict) or set(weights) != set(DIMENSIONS):
        return "invalid_weights"
    if round(sum(float(value) for value in weights.values()), 6) != 1.0:
        return "weights_do_not_sum_to_one"

    scores = payload.get("scores")
    if not isinstance(scores, dict):
        return "missing_field:scores"
    for dimension in DIMENSIONS:
        if not _is_rate(scores.get(dimension), allow_null=True):
            return f"invalid_rate:scores.{dimension}"
    if not _is_rate(scores.get("mheb_overall")):
        return "invalid_rate:scores.mheb_overall"
    for field in _NULLABLE_RATE_FIELDS:
        if not _is_rate(scores.get(field), allow_null=True):
            return f"invalid_rate:scores.{field}"

    breakdown = payload.get("category_breakdown")
    if not isinstance(breakdown, dict):
        return "missing_field:category_breakdown"
    for category, stats in breakdown.items():
        if category not in CATEGORIES:
            return f"unknown_category:{category}"
        if not isinstance(stats, dict):
            return f"invalid_category_stats:{category}"
        for field in ("passed", "total"):
            value = stats.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return f"invalid_count:category_breakdown.{category}.{field}"
        if stats["passed"] > stats["total"]:
            return f"category_passed_exceeds_total:{category}"
        if not _is_rate(stats.get("rate")):
            return f"invalid_rate:category_breakdown.{category}.rate"

    if not isinstance(payload.get("failures"), list):
        return "missing_field:failures"
    if len(payload["failures"]) != summary["failed"]:
        return "failures_length_mismatch"

    error = _validate_mq(payload.get("mq"))
    if error is not None:
        return error

    # economics / health 是规范 §5 要求报告必须自带的两段，缺了报告就不完整。
    for field in ("economics", "health"):
        if not isinstance(payload.get(field), dict):
            return f"missing_field:{field}"
    return None


def _validate_mq(mq: object) -> str | None:
    """校验 MQ 段（规范 IQMQ双轴框架 §10.3）。

    两条硬要求：

    1. **未覆盖的子能力必须是 ``null``**，不能是 0。套件没跑到某一环时把它记 0
       会让 MQ 总分被无声压低，读起来像「这项能力很差」，而事实是「没测」。
    2. **``iq`` 必须是 ``null``**。IQ 由所接模型提供，本系统不测量它。留一个可以
       被填成数字的字段，早晚会有人往里塞一个估算值——契约层直接钉死。
    """
    if not isinstance(mq, dict):
        return "missing_field:mq"

    weights = mq.get("weights")
    if not isinstance(weights, dict) or set(weights) != set(MQ_SUBSKILLS):
        return "invalid_mq_weights"
    if round(sum(float(value) for value in weights.values()), 6) != 1.0:
        return "mq_weights_do_not_sum_to_one"

    subskills = mq.get("subskills")
    if not isinstance(subskills, dict) or set(subskills) != set(MQ_SUBSKILLS):
        return "invalid_mq_subskills"
    for name, value in subskills.items():
        if not _is_rate(value, allow_null=True):
            return f"invalid_rate:mq.subskills.{name}"

    if not _is_rate(mq.get("mq_overall"), allow_null=True):
        return "invalid_rate:mq.mq_overall"
    covered = [name for name, value in subskills.items() if value is not None]
    if covered and mq.get("mq_overall") is None:
        return "mq_overall_missing_despite_coverage"
    if not covered and mq.get("mq_overall") is not None:
        return "mq_overall_present_without_coverage"

    uncovered = mq.get("uncovered_subskills")
    if not isinstance(uncovered, list):
        return "missing_field:mq.uncovered_subskills"
    if sorted(uncovered) != sorted(set(MQ_SUBSKILLS) - set(covered)):
        return "mq_uncovered_mismatch"

    # IQ 轴由所接模型决定，本系统不测量——契约层钉死为 null。
    if "iq" not in mq:
        return "missing_field:mq.iq"
    if mq["iq"] is not None:
        return "iq_must_be_null_this_system_does_not_measure_it"
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"MEB score report JSON could not be loaded: {exc}", file=sys.stderr)
        return 2
    error = score_report_validation_error(payload)
    if error is not None:
        print(f"MEB score report contract failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
