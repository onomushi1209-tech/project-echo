from __future__ import annotations

from datetime import datetime, timezone

import pytest

from echo.models.source import SourceItem
from echo.research.config import ResearchConfig
from echo.research.extraction import extract_fact_candidates
from echo.core.text import normalize_text, token_set, tokenize
from echo.research.claims import group_fact_candidates

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
CONFIG = ResearchConfig()


def _item(title: str, content: str = "") -> SourceItem:
    return SourceItem(
        source_id="a",
        source_key="s1",
        url="https://example.com/a",
        source_name="s1",
        title=title,
        published_at=NOW,
        retrieved_at=NOW,
        content=content,
        language="en",
        vertical="ai",
    )


def test_extracts_title_as_a_fact_candidate() -> None:
    candidates = extract_fact_candidates([_item("Research lab announces a major new model")], CONFIG)
    assert len(candidates) == 1
    assert candidates[0].text == "Research lab announces a major new model"


def test_extracts_sentences_from_content() -> None:
    item = _item(
        "Research lab announces a major new model",
        content="The model was trained for several months. It outperforms prior benchmarks significantly.",
    )
    candidates = extract_fact_candidates([item], CONFIG)
    texts = [c.text for c in candidates]
    assert "The model was trained for several months." in texts
    assert "It outperforms prior benchmarks significantly." in texts


def test_excludes_empty_content() -> None:
    item = _item("A usable title sentence here", content="")
    candidates = extract_fact_candidates([item], CONFIG)
    assert len(candidates) == 1  # title only


def test_excludes_very_short_sentences() -> None:
    item = _item("A usable title sentence here", content="OK. Read more.")
    candidates = extract_fact_candidates([item], CONFIG)
    texts = [c.text for c in candidates]
    assert "OK." not in texts
    assert "Read more." not in texts


def test_excludes_navigation_like_fragments() -> None:
    item = _item("A usable title sentence here", content="Home. Contact. About.")
    candidates = extract_fact_candidates([item], CONFIG)
    texts = [c.text for c in candidates]
    assert "Home." not in texts
    assert "Contact." not in texts


def test_removes_duplicate_sentence_within_same_item() -> None:
    item = _item(
        "Research lab announces a major new model",
        content="Research lab announces a major new model. Details will follow soon.",
    )
    candidates = extract_fact_candidates([item], CONFIG)
    texts = [c.text for c in candidates]
    assert texts.count("Research lab announces a major new model") == 1


def test_keeps_cross_source_repetition() -> None:
    item_a = SourceItem(
        source_id="a", source_key="s1", url="https://example.com/a", source_name="s1",
        title="Research lab announces a major new model", published_at=NOW, retrieved_at=NOW,
        content="", language="en", vertical="ai",
    )
    item_b = SourceItem(
        source_id="b", source_key="s2", url="https://example.com/b", source_name="s2",
        title="Research lab announces a major new model", published_at=NOW, retrieved_at=NOW,
        content="", language="en", vertical="ai",
    )
    candidates = extract_fact_candidates([item_a, item_b], CONFIG)
    assert len(candidates) == 2


def test_provenance_links_back_to_source_item() -> None:
    item = _item("Research lab announces a major new model")
    candidates = extract_fact_candidates([item], CONFIG)
    assert candidates[0].source_item.source_id == "a"


def test_empty_input_produces_no_candidates() -> None:
    assert extract_fact_candidates([], CONFIG) == []


JAPANESE_SENTENCE = "新しいモデルは本日、日本国内で正式に提供開始されました。"


def test_japanese_natural_sentence_is_useful_and_tokenized():
    candidates = extract_fact_candidates([_item(JAPANESE_SENTENCE)], CONFIG)
    assert [c.text for c in candidates] == [JAPANESE_SENTENCE]
    assert token_set(JAPANESE_SENTENCE)


def test_japanese_sentences_split_without_spaces_and_deduplicate():
    second = "利用料金と詳しい提供条件については公式サイトで確認できます。"
    candidates = extract_fact_candidates([_item(JAPANESE_SENTENCE, JAPANESE_SENTENCE + second)], CONFIG)
    assert [c.text for c in candidates] == [JAPANESE_SENTENCE, second]


@pytest.mark.parametrize("noise", [
    "", "！？。" * 15, "新製品", "日" + "！" * 40, "ーー" * 20, "詳しくはこちら",
    "________ ________ ________", "日 " + "！ " * 20,
    "日 本 語 " + "！ " * 20,
])
def test_japanese_noise_is_rejected(noise):
    assert extract_fact_candidates([_item(noise or " ")], CONFIG) == []


def test_japanese_grouping_distinguishes_agreement_and_unrelated_text():
    matching = extract_fact_candidates([_item(JAPANESE_SENTENCE), _item(JAPANESE_SENTENCE)], CONFIG)
    assert len(group_fact_candidates(matching, CONFIG)) == 1
    unrelated = "宇宙探査機による火星表面の観測結果について詳細な報告が公表されました。"
    candidates = extract_fact_candidates([_item(JAPANESE_SENTENCE), _item(unrelated)], CONFIG)
    assert len(group_fact_candidates(candidates, CONFIG)) == 2


def test_japanese_unicode_normalization_and_english_tokens():
    assert normalize_text("ＡＩ ﾓﾃﾞﾙ　提供開始。") == normalize_text("AI モデル 提供開始。")
    assert tokenize("The research lab releases a new model today.") == [
        "research", "lab", "releases", "model", "today",
    ]
    assert token_set("新しいＡＩモデルは日本国内で本日正式に公開されました。")


def test_english_sentence_with_short_japanese_product_name_is_preserved():
    sentence = "The company launched the new 凛 model today"
    candidates = extract_fact_candidates([_item(sentence)], CONFIG)
    assert [candidate.text for candidate in candidates] == [sentence]
