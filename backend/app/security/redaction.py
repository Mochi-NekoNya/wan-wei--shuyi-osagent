"""Redaction utilities for sensitive data in audit logs and responses."""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


# Patterns for sensitive data detection
_PATTERNS = [
    # Passwords
    (re.compile(r'(password["\']?\s*[:=]\s*["\']?)([^"\'}\r\n,]+)', re.IGNORECASE), r'\1***REDACTED***'),
    # Generic credential assignments
    (re.compile(r'((?:api[_-]?key|secret|token)["\']?\s*[:=]\s*["\']?)([^"\'}\r\n,]+)', re.IGNORECASE), r'\1***REDACTED***'),
    # Bearer tokens
    (re.compile(r'(Bearer\s+)([A-Za-z0-9\-._~+/]+=*)', re.IGNORECASE), r'\1***REDACTED***'),
    # Common provider / SaaS token formats
    (re.compile(r'\b(sk-[A-Za-z0-9_-]{16,})', re.IGNORECASE), r'***REDACTED***'),
    (re.compile(r'\b(sk-ant-[A-Za-z0-9_-]{16,})', re.IGNORECASE), r'***REDACTED***'),
    (re.compile(r'\b(sess-[A-Za-z0-9]{32,})', re.IGNORECASE), r'***REDACTED***'),
    (re.compile(r'\b(gh[pousr]_[A-Za-z0-9_]{20,})'), r'***REDACTED***'),
    (re.compile(r'\b(AIza[0-9A-Za-z_-]{20,})'), r'***REDACTED***'),
    (re.compile(r'\b(xox[baprs]-[0-9A-Za-z-]{10,})'), r'***REDACTED***'),
    (re.compile(r'\b(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})'), r'***REDACTED***'),
    # Database URLs with user:password@host
    (re.compile(r'([a-z][a-z0-9+.-]*://[^/:\s]+:)([^@\s]+)(@)', re.IGNORECASE), r'\1***REDACTED***\3'),
    # Natural language passwords
    (re.compile(r'((?:the\s+)?password\s+(?:is|=|:)\s+)([^\r\n,;]+)', re.IGNORECASE), r'\1***REDACTED***'),
    # AWS keys
    (re.compile(r'\b(AKIA[0-9A-Z]{16})', re.IGNORECASE), r'***REDACTED***'),
    (re.compile(r'\b(ASIA[0-9A-Z]{16})', re.IGNORECASE), r'***REDACTED***'),
    # FIX-05: Email addresses (与 policy_gate EMAIL_PATTERNS 对齐)
    (re.compile(r'\b[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}\b'), r'[REDACTED_EMAIL]'),
    # Chinese mobile phone (11 digits starting with 1)
    (re.compile(r'\b1[3-9]\d{9}\b'), r'***PHONE***'),
    # Chinese ID card (18 digits or 17 digits + X)
    (re.compile(r'\b\d{17}[\dXx]\b'), r'***ID***'),
    # Private key blocks
    (re.compile(r'-----BEGIN [A-Z ]+PRIVATE KEY-----[^-]+-----END [A-Z ]+PRIVATE KEY-----', re.DOTALL),
     r'***PRIVATE_KEY_REDACTED***'),
]


def redact_sensitive_text(text: str) -> str:
    """
    Redact sensitive information from text.

    Args:
        text: Input text that may contain sensitive data

    Returns:
        Text with sensitive data replaced by redaction markers
    """
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _redact_value(value: Any) -> Any:
    """Return a recursively redacted copy of a JSON-compatible value."""
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return deepcopy(value)


def redact_capsule_for_output(capsule: dict[str, Any]) -> dict[str, Any]:
    """Create an independent capsule copy that is safe for external output.

    issue #116：输出脱敏**无条件执行**，不再由 ``policy_result == "redact"``
    门控。旧实现形成「闸门放行 → 跳过脱敏」闭环：policy_gate 的凭据识别
    只覆盖 AWS/sk- 两种前缀，ghp_/AIza/xox/JWT/PEM/数据库连接串等格式
    会被判 ``allow``，于是本模块专门为这些格式写的掩码规则在结构上永远
    走不到——明文密钥可入库并原样读回。脱敏是输出边界的独立防线，
    不该依赖上游风险分级的完备性。

    The deep-copy contract is intentional: output handling must never replace
    the original text held by storage or by another caller sharing the same
    in-memory object.
    """
    return _redact_value(capsule)


def redact_dict(data: dict[str, Any], in_place: bool = False) -> dict[str, Any]:
    """
    Recursively redact sensitive data from dictionary.

    Args:
        data: Dictionary that may contain sensitive data
        in_place: If True, modify dict in place; otherwise create copy

    Returns:
        Dictionary with sensitive data redacted
    """
    if not in_place:
        data = data.copy()

    for key, value in data.items():
        if isinstance(value, str):
            data[key] = redact_sensitive_text(value)
        elif isinstance(value, dict):
            data[key] = redact_dict(value, in_place=False)
        elif isinstance(value, list):
            data[key] = [
                redact_dict(item, in_place=False) if isinstance(item, dict)
                else redact_sensitive_text(item) if isinstance(item, str)
                else item
                for item in value
            ]

    return data


def redact_audit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Redact sensitive data from audit log payload.

    For rejected events (policy blocks), stores metadata instead of full content:
    - risk_tags: What triggered the block
    - sensitivity_level: S0-S3 classification
    - content_hash: Hash of content for correlation
    - content_preview: First 100 chars (redacted)

    Args:
        payload: Audit payload that may contain sensitive data

    Returns:
        Redacted payload suitable for audit logging
    """
    result = redact_dict(payload, in_place=False)

    # Policy-rejected content is blocked from memory, including nested legacy
    # event payloads. Keep decision metadata but discard every content field.
    is_reject = (result.get('policy_result') == 'reject'
                  or result.get('guard', {}).get('policy_result') == 'reject')
    if is_reject:
        def strip_content(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: '[REDACTED - Policy Block]' if key == 'content' else strip_content(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [strip_content(item) for item in value]
            return value

        result = strip_content(result)

    return result
