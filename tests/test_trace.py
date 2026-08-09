from __future__ import annotations

from datetime import date

import pytest

from echo.core.trace import (
    InMemorySequenceProvider,
    TraceIDError,
    TraceIDGenerator,
    format_trace_id,
    parse_trace_id,
)


def test_format_trace_id_matches_spec_example() -> None:
    assert format_trace_id("ai", date(2026, 8, 9), 1) == "ECHO-AI-20260809-000001"


def test_parse_trace_id_round_trip() -> None:
    trace_id = format_trace_id("ai", date(2026, 8, 9), 42)
    parts = parse_trace_id(trace_id)
    assert parts.vertical == "AI"
    assert parts.day == date(2026, 8, 9)
    assert parts.sequence == 42


def test_parse_trace_id_rejects_malformed_input() -> None:
    with pytest.raises(TraceIDError):
        parse_trace_id("not-a-trace-id")


def test_format_trace_id_rejects_out_of_range_sequence() -> None:
    with pytest.raises(TraceIDError):
        format_trace_id("ai", date(2026, 8, 9), 0)
    with pytest.raises(TraceIDError):
        format_trace_id("ai", date(2026, 8, 9), 1_000_000)


def test_generator_increments_sequence_per_vertical_per_day() -> None:
    provider = InMemorySequenceProvider()
    generator = TraceIDGenerator(vertical="ai", sequence_provider=provider)
    day = date(2026, 8, 9)

    first = generator.generate(on=day)
    second = generator.generate(on=day)

    assert first == "ECHO-AI-20260809-000001"
    assert second == "ECHO-AI-20260809-000002"


def test_generator_sequence_resets_on_new_day() -> None:
    provider = InMemorySequenceProvider()
    generator = TraceIDGenerator(vertical="ai", sequence_provider=provider)

    day_one = generator.generate(on=date(2026, 8, 9))
    day_two = generator.generate(on=date(2026, 8, 10))

    assert day_one == "ECHO-AI-20260809-000001"
    assert day_two == "ECHO-AI-20260810-000001"


def test_generator_keeps_verticals_independent() -> None:
    provider = InMemorySequenceProvider()
    day = date(2026, 8, 9)
    ai_gen = TraceIDGenerator(vertical="ai", sequence_provider=provider)
    tech_gen = TraceIDGenerator(vertical="tech", sequence_provider=provider)

    assert ai_gen.generate(on=day) == "ECHO-AI-20260809-000001"
    assert tech_gen.generate(on=day) == "ECHO-TECH-20260809-000001"
    assert ai_gen.generate(on=day) == "ECHO-AI-20260809-000002"
