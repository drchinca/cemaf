"""Unit tests for DefaultEntityExtractor."""

from cemaf.datasources.entity_extractor import DefaultEntityExtractor


class TestDefaultEntityExtractor:
    def test_empty_text_returns_nothing(self) -> None:
        extractor = DefaultEntityExtractor()
        assert extractor.extract(text="") == ()

    def test_plain_sentence_extracts_nothing(self) -> None:
        extractor = DefaultEntityExtractor()
        result = extractor.extract(text="Look up the order and confirm shipping")
        assert result == ()

    def test_camel_case_extracted(self) -> None:
        extractor = DefaultEntityExtractor()
        result = extractor.extract(text="Look up OrderPipeline status")
        assert len(result) == 1
        assert result[0].label == "OrderPipeline"
        assert result[0].id == "orderpipeline"

    def test_gazetteer_match_case_insensitive(self) -> None:
        extractor = DefaultEntityExtractor(gazetteer=frozenset({"Salesforce"}))
        result = extractor.extract(text="check salesforce for the account")
        assert len(result) == 1
        assert result[0].label == "Salesforce"

    def test_deterministic_same_input_same_output(self) -> None:
        extractor = DefaultEntityExtractor(gazetteer=frozenset({"Salesforce"}))
        text = "Look up OrderPipeline in Salesforce"
        assert extractor.extract(text=text) == extractor.extract(text=text)

    def test_dedupes_repeated_mentions(self) -> None:
        extractor = DefaultEntityExtractor()
        result = extractor.extract(text="OrderPipeline failed, check OrderPipeline logs")
        assert len(result) == 1

    def test_version_is_pinned(self) -> None:
        extractor = DefaultEntityExtractor()
        assert extractor.version == "1.0.0"
