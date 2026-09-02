"""偏好记忆的 Beta 置信度建模（算法设计框架 B1）。

设计文档：``notes/09-algorithm-design-framework.md`` §B1。

把 preference capsule 的 ``state`` 从「拍一个 strength 数字」升级为贝叶斯统计
后验：用 Beta-Binomial 共轭对「这条偏好被采纳 / 被违背」的次数建模。

    prior:        Beta(α₀=1, β₀=1)          # 无信息先验
    被采纳/命中:   α += 1（reflect_task 判定 helpful）
    被违背/失配:   β += 1（用户纠正 / 显式拒绝确认）
    均值:         E = α / (α + β)           # 后验均值
    置信度:       conf = 1 - 2·sd           # sd 为后验标准差的折算项

计数键写在 capsule ``state`` 内（``preference_alpha`` / ``preference_beta``），
向后兼容——旧读者读到这两个新键也无感；``confidence()`` 对缺失键按 0 处理，
默认落在无信息先验 Beta(1,1) 上。

本模块是纯函数、不依赖数据库层，方便检索侧（C2 排序乘子）直接复用。
"""

import math
from typing import Any

#: state JSON 里的计数键名（命名随 state 既有风格：snake_case 整数计数）。
ALPHA_KEY = "preference_alpha"
BETA_KEY = "preference_beta"

#: Beta 先验参数（无信息先验，等价于各先观察一次）。
PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0


def update_confidence(meta: dict[str, Any], outcome: str) -> dict[str, Any]:
    """按一次反馈结果更新偏好计数（就地修改 ``meta`` 并返回）。

    Args:
        meta: capsule 的 ``state`` 字典（含 ``preference_alpha`` /
            ``preference_beta`` 计数键，缺省视为 0）。
        outcome: ``"reinforce"`` 表示偏好被采纳 → α 计数 +1；
            ``"deprecate"`` 表示偏好被违背 → β 计数 +1。

    Raises:
        ValueError: ``outcome`` 不是 ``"reinforce"`` / ``"deprecate"``。
    """
    if outcome not in ("reinforce", "deprecate"):
        raise ValueError(
            f"outcome 必须是 'reinforce' 或 'deprecate'，得到: {outcome!r}"
        )
    alpha = int(meta.get(ALPHA_KEY, 0) or 0)
    beta = int(meta.get(BETA_KEY, 0) or 0)
    if outcome == "reinforce":
        alpha += 1
    else:
        beta += 1
    # 计数键始终写全（含 0）：让 state JSON 的 Beta 模型状态自明，
    # 集成侧无需处理「键缺失」分支。
    meta[ALPHA_KEY] = alpha
    meta[BETA_KEY] = beta
    return meta


def confidence(meta: dict[str, Any]) -> dict[str, float]:
    """计算当前 Beta 后验参数与置信度。

    返回 ``{"alpha", "beta", "mean", "conf"}``：

    - ``alpha`` / ``beta``：后验参数（先验 + 累计计数）；
    - ``mean``：后验均值 α/(α+β)——即设计文档里写回 ``strength`` 的候选值；
    - ``conf``：置信度 = 1 − 2·sqrt(αβ/((α+β)²(α+β+1)))，样本越多越自信。
    """
    alpha = PRIOR_ALPHA + float(meta.get(ALPHA_KEY, 0) or 0)
    beta = PRIOR_BETA + float(meta.get(BETA_KEY, 0) or 0)
    total = alpha + beta
    mean = alpha / total
    conf = 1.0 - 2.0 * math.sqrt(
        alpha * beta / (total * total * (total + 1.0))
    )
    return {"alpha": alpha, "beta": beta, "mean": mean, "conf": conf}


__all__ = [
    "ALPHA_KEY",
    "BETA_KEY",
    "PRIOR_ALPHA",
    "PRIOR_BETA",
    "confidence",
    "update_confidence",
]
