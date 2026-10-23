from process_test_helpers import historical_profiles
from unittest.mock import Mock

from src.ocr.application.convert_document import ConvertDocumentUseCase
from src.ocr.application.process_page import ProcessPageUseCase


def test_shared_docling_client_is_kept_between_documents_and_invalidated_on_model_change(monkeypatch):
    from src.ocr.infrastructure.layout import docling_structure
    from src.ocr.runtime import models, fingerprint
    factory = Mock(side_effect=[Mock(), Mock()])
    monkeypatch.setattr(docling_structure, "DoclingStructureExtractor", factory)
    model = Mock(return_value="weights-1")
    monkeypatch.setattr(models, "model_fingerprint", model)
    monkeypatch.setattr(fingerprint, "source_fingerprint", lambda: "code-1")
    converter = ConvertDocumentUseCase(config_path=historical_profiles(), reuse_docling=True)
    config = {"primary_engine": "rapidocr", "docling": {"enabled": True, "device": "cpu"}}
    first = converter._docling_client(config)
    assert converter._docling_client(config) is first
    processor = ProcessPageUseCase.__new__(ProcessPageUseCase)
    processor.structure_extractor = first
    processor._owns_structure_extractor = False
    processor.close()
    first.close.assert_not_called()
    model.return_value = "weights-2"
    second = converter._docling_client(config)
    assert second is not first
    first.close.assert_called_once()
    converter.close()
    second.close.assert_called_once()


def test_disabling_docling_releases_previously_shared_worker(monkeypatch):
    from src.ocr.infrastructure.layout import docling_structure
    from src.ocr.runtime import models, fingerprint
    client = Mock()
    monkeypatch.setattr(docling_structure, "DoclingStructureExtractor", Mock(return_value=client))
    monkeypatch.setattr(models, "model_fingerprint", lambda _: "weights")
    monkeypatch.setattr(fingerprint, "source_fingerprint", lambda: "code")
    converter = ConvertDocumentUseCase(config_path=historical_profiles(), reuse_docling=True)
    converter._docling_client({"docling": {"enabled": True}})
    assert converter._docling_client({"docling": {"enabled": False}}) is None
    client.close.assert_called_once()
