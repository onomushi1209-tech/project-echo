from __future__ import annotations

import pytest

from echo.models.enums import ConflictSeverity
from echo.research.conflicts import detect_conflict


@pytest.mark.parametrize("text_a,text_b", [
    ("The Orion model is unavailable today", "The Orion model is unavailable today"),
    ("The Orion model is unavailable today", "The Orion model remains unavailable today"),
    ("The Orion release was delayed and released today", "Orion release was delayed and released today"),
    ("The Orion model is preapproved for testing today", "The Orion model is rejected for testing today"),
])
def test_status_words_require_exclusive_lexical_opposites(text_a, text_b):
    assert detect_conflict(text_a, text_b) is None
    assert detect_conflict(text_b, text_a) is None


def test_available_and_unavailable_are_true_opposites():
    signal = detect_conflict("The Orion model is available today", "The Orion model is unavailable today")
    assert signal is not None
    assert signal.conflict_type == "status_keyword"
    assert signal.severity == ConflictSeverity.MAJOR


def test_status_keyword_conflict_detected() -> None:
    signal = detect_conflict("Product X released today", "Product X release delayed")
    assert signal is not None
    assert signal.conflict_type == "status_keyword"
    assert signal.severity in (ConflictSeverity.MAJOR, ConflictSeverity.POTENTIAL)


def test_negation_conflict_detected() -> None:
    signal = detect_conflict(
        "The company confirmed the merger will proceed as planned",
        "The company confirmed the merger will not proceed as planned",
    )
    assert signal is not None
    assert signal.conflict_type == "negation"


def test_numeric_conflict_detected() -> None:
    signal = detect_conflict(
        "Company reports revenue of 50 million dollars",
        "Company reports revenue of 80 million dollars",
    )
    assert signal is not None
    assert signal.conflict_type == "numeric"


def test_date_conflict_detected() -> None:
    signal = detect_conflict("Event scheduled for March 1", "Event scheduled for March 15")
    assert signal is not None
    assert signal.conflict_type == "date"


def test_no_conflict_for_agreeing_sentences() -> None:
    signal = detect_conflict(
        "Research lab releases new model today",
        "Research lab has released a new model",
    )
    assert signal is None


def test_no_conflict_for_unrelated_sentences() -> None:
    signal = detect_conflict(
        "Research lab releases new model today",
        "Quarterly earnings beat analyst expectations",
    )
    assert signal is None


def test_no_conflict_for_identical_sentences() -> None:
    signal = detect_conflict("Research lab releases new model today", "Research lab releases new model today")
    assert signal is None


def test_matching_numbers_is_not_a_conflict() -> None:
    signal = detect_conflict(
        "Company reports revenue of 50 million dollars",
        "Company reports revenue of 50 million dollars again",
    )
    assert signal is None
