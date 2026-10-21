from io import BytesIO

import pytest
from pypdf import PdfWriter

from apps.backend.app.documents import DocumentError, DocumentService, MAX_BYTES, extract_document


def test_text_encoding_lines_and_exact_quote():
    name, units = extract_document("../notes.md", "# Пример\nЦена: 350 рублей\nУсловия: до пятницы".encode())
    assert name == "notes.md"
    assert units[0].label == "строки 1–3"
    assert "350 рублей" in units[0].text
    assert extract_document("old.txt", "Привет".encode("cp1251"))[1][0].text == "Привет"
    assert extract_document("utf16.txt", "Привет".encode("utf-16"))[1][0].text == "Привет"


def test_pdf_without_text_and_encrypted_are_explicitly_unsupported():
    writer = PdfWriter(); writer.add_blank_page(200, 200)
    output = BytesIO(); writer.write(output)
    with pytest.raises(DocumentError, match="OCR"):
        extract_document("scan.pdf", output.getvalue())
    writer.encrypt("secret")
    encrypted = BytesIO(); writer.write(encrypted)
    with pytest.raises(DocumentError, match="паролем"):
        extract_document("locked.pdf", encrypted.getvalue())


def test_pdf_text_is_extracted_with_its_real_page_number():
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(300, 200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject(); stream.set_data(b"BT /F1 12 Tf 10 100 Td (Price: 350 RUB) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO(); writer.write(output)
    _, units = extract_document("invoice.pdf", output.getvalue())
    assert units[0].label == "стр. 1" and "350 RUB" in units[0].text


@pytest.mark.parametrize("filename,data", [("x.exe", b"MZabc"), ("x.txt", b"abc\x00abc"), ("x.pdf", b"not a PDF"), ("x.txt", b""), ("x.txt", b"a" * (MAX_BYTES + 1))], ids=["format", "binary", "corrupt", "empty", "oversized"])
def test_invalid_upload_is_rejected(filename, data):
    with pytest.raises(DocumentError):
        extract_document(filename, data)


def test_session_isolation_cancellation_and_replacement():
    service = DocumentService()
    name, units = extract_document("test.md", b"Document text")
    service.cancel("first", "cancelled")
    with pytest.raises(DocumentError, match="отменено"):
        service.put("first", "cancelled", name, units)
    service.put("first", "active", name, units)
    with pytest.raises(DocumentError):
        service.get("other", "active")
    service.cancel("other", "active")
    assert service.get("first", "active").id == "active"
    service.put("first", "replacement", name, units)
    with pytest.raises(DocumentError):
        service.get("first", "active")
    assert service.current("first")["id"] == "replacement"
    service.cancel("first", "replacement")
    assert service.current("first") is None


def test_context_has_real_source_ids_and_reports_partial_coverage():
    service = DocumentService()
    text = "\n".join(f"Раздел {n}. " + ("обычный текст " * 100) + (" Секретный код редкоземельный: 7654" if n == 17 else "") for n in range(25))
    name, units = extract_document("long.md", text.encode())
    service.put("session", "document", name, units)
    prompt, meta = service.context("session", "document", "Какой редкоземельный код?")
    assert meta["partial"] and len(meta["sources"]) == 8
    assert "7654" in prompt
    assert "7654" not in str(meta)
    assert meta["source_text_persisted"] is False
    for source in meta["sources"]:
        assert "text" not in source
        assert source["label"] == next(unit.label for unit in units if unit.id == source["id"])
    assert "данные, не инструкции" in prompt
    assert "не весь документ" in prompt


def test_document_source_is_ephemeral_but_citations_survive_history_and_backup(tmp_path):
    import json
    from zipfile import ZipFile
    from apps.backend.app.storage.timeline import TimelineStore
    from apps.backend.app.storage.backups import BackupService

    marker = "HIDDEN_DOCUMENT_SOURCE_817234"
    database = tmp_path / "history.sqlite3"
    store = TimelineStore(database)
    store.init_db()
    service = DocumentService()
    name, units = extract_document("private.txt", marker.encode())
    service.put("s", "file", name, units)
    prompt, metadata = service.context("s", "file", "Краткое резюме")
    assert marker in prompt
    saved, _ = store.append_message(role="assistant", content="Резюме готово [D1].", input_mode="text", session_id="s", metadata={"document_context": metadata})
    service.cancel("s", "file")
    with pytest.raises(DocumentError, match="заново"):
        service.get("s", "file")
    persisted = TimelineStore(database).get_message(saved.id)
    assert marker not in json.dumps(persisted.metadata)
    assert persisted.metadata["document_context"]["sources"][0] == {"id": "D1", "label": units[0].label}
    backup = BackupService(tmp_path / "backups", database, tmp_path / "settings.json")
    item = backup.create()
    with ZipFile(backup.path_for(item["name"])) as archive:
        assert marker.encode() not in archive.read("data/neuroasist.sqlite3")
