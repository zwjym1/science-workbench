"""Risk-control signatures for public guest responses.

Pure and dependency-free on purpose: the capture layer, the normaliser and the
tests must all agree on what a block looks like. Getting this wrong in the
permissive direction means a healthy session gets rate-limited every time a
video happens to be deleted, which is the failure mode this module exists to
prevent.
"""
from __future__ import annotations

from typing import Any, Mapping

#: Status codes Douyin uses for verification / throttle envelopes. Values here
#: are observed, not documented, so treat additions as needing confirmation.
RISK_STATUS_CODES = frozenset({8, 2154, 2156, 10000, 10001})


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def detect_risk_control(payload: Mapping[str, Any]) -> str | None:
    """Name the risk-control signal in ``payload``, or return ``None``."""
    if not payload:
        return 'empty_body'
    code = _as_int(payload.get('status_code'))
    if code is not None and code in RISK_STATUS_CODES:
        return f'status_code:{code}'
    if payload.get('verify_center_decision_conf'):
        return 'verify_center'
    if payload.get('captcha') or payload.get('verify_page'):
        return 'captcha_page'
    # An empty aweme_list or comments list is legitimate (nothing there);
    # an empty aweme_detail or user envelope is a block, not an absence.
    for key in ('aweme_detail', 'user'):
        if key in payload and not payload[key]:
            return f'empty:{key}'
    return None


def classify_http_restriction(status: int) -> str | None:
    """Map a transport-level status to a restriction label."""
    if status in (401, 403):
        return f'HTTP {status} (identity or permission rejected)'
    if status == 429:
        return 'HTTP 429 (throttled; stop instead of retrying harder)'
    if status >= 500:
        return f'HTTP {status} (upstream; do not treat as missing content)'
    return None
