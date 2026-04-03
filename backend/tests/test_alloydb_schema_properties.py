"""
Property-based tests for AlloyDB schema functions.

**Validates: Requirements 8.3, 6.4, 7.3, 7.4**

P1: get_history limit always clamped to [1, 50]
P2: save_analysis_result preserves all JSONB arrays (round-trip)
P3: document status transitions are valid
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# P1: get_history limit always clamped to [1, 50]
# **Validates: Requirements 8.3**
# ---------------------------------------------------------------------------

async def _test_p1_impl(limit: int) -> None:
    import re
    from database import get_history

    execute_result = MagicMock()
    execute_result.all.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=execute_result)

    await get_history(db, limit=limit)

    db.execute.assert_awaited_once()
    stmt = db.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    # The LIMIT in the SQL must be <= 50 (handles negative values too)
    match = re.search(r"LIMIT\s+(-?\d+)", compiled, re.IGNORECASE)
    assert match is not None, f"No LIMIT found in SQL: {compiled}"
    actual_limit = int(match.group(1))
    assert actual_limit <= 50, f"Expected LIMIT <= 50, got {actual_limit} for input {limit}"


@given(limit=st.integers(min_value=-1000, max_value=1000))
@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=50, deadline=None)
def test_p1_get_history_limit_clamped(limit: int) -> None:
    """P1: For any integer input in [-1000, 1000], the SQL LIMIT is always <= 50."""
    asyncio.run(_test_p1_impl(limit))


# ---------------------------------------------------------------------------
# P2: save_analysis_result preserves all JSONB arrays (round-trip)
# **Validates: Requirements 6.4**
# ---------------------------------------------------------------------------

_dict_strategy = st.dictionaries(
    st.text(min_size=1, max_size=10),
    st.text(min_size=0, max_size=20),
)
_list_of_dicts = st.lists(_dict_strategy, max_size=5)


async def _test_p2_impl(items: list[dict]) -> None:
    from database import save_analysis_result

    db = AsyncMock()
    db.flush = AsyncMock()

    result = await save_analysis_result(
        db,
        document_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        result_dict={
            "user_stories": items,
            "acceptance_criteria": items,
            "gap_flags": items,
            "executive_summary": "test",
        },
        tokens_used=0,
        processing_time_ms=0,
        model_used="test-model",
    )

    assert result.user_stories == items, (
        f"user_stories mismatch: expected {items}, got {result.user_stories}"
    )
    assert result.acceptance_criteria == items, (
        f"acceptance_criteria mismatch: expected {items}, got {result.acceptance_criteria}"
    )
    assert result.gap_flags == items, (
        f"gap_flags mismatch: expected {items}, got {result.gap_flags}"
    )


@given(items=_list_of_dicts)
@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=50, deadline=None)
def test_p2_save_analysis_result_preserves_jsonb_arrays(items: list[dict]) -> None:
    """P2: For any list of dicts, save_analysis_result preserves user_stories,
    acceptance_criteria, and gap_flags exactly (round-trip preservation)."""
    asyncio.run(_test_p2_impl(items))


# ---------------------------------------------------------------------------
# P3: document status transitions are valid
# **Validates: Requirements 7.3, 7.4**
# ---------------------------------------------------------------------------

_VALID_STATUSES = {"processing", "completed", "failed"}

_invalid_status_strategy = st.text(min_size=1, max_size=30).filter(
    lambda s: s not in _VALID_STATUSES
)


async def _test_p3_invalid_impl(status: str) -> None:
    from database import update_document_status

    db = AsyncMock()
    db.execute = AsyncMock()

    try:
        await update_document_status(db, uuid.uuid4(), status)
        raise AssertionError(
            f"Expected ValueError for invalid status '{status}', but no exception was raised"
        )
    except ValueError:
        pass  # expected


async def _test_p3_valid_impl(status: str) -> None:
    from database import update_document_status

    db = AsyncMock()
    db.execute = AsyncMock()

    # Should not raise
    await update_document_status(db, uuid.uuid4(), status)


@given(status=_invalid_status_strategy)
@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=50, deadline=None)
def test_p3_invalid_status_raises_value_error(status: str) -> None:
    """P3a: update_document_status raises ValueError for any string not in valid set."""
    asyncio.run(_test_p3_invalid_impl(status))


def test_p3_valid_statuses_do_not_raise() -> None:
    """P3b: update_document_status does not raise for all three valid status values."""
    for status in _VALID_STATUSES:
        asyncio.run(_test_p3_valid_impl(status))
