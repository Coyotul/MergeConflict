"""Safety checks: invalid uploads never become trusted, and files survive restarts safely."""
import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, ArrayObject

from src.core.errors import InvalidUpload
from src.storage.secure_documents.store import SecureDocumentStore
from tests.fixtures.documents import pdf_bytes, identity_text, image_bytes


def save(store, *, customer="cust-001", session="session-1", data=None, mime="application/pdf"):
    return store.store_document(
        customer_id=customer, session_id=session, filename="../../identity.exe",
        content_bytes=pdf_bytes(identity_text()) if data is None else data,
        mime_type=mime, doc_kind="id_card",
    )


@pytest.mark.parametrize("data,mime,code", [
    (b"", "application/pdf", "empty_upload"),
    (b"not a PDF", "application/pdf", "file_type_mismatch"),
    (b"%PDF-1.4 broken", "application/pdf", "invalid_file_format"),
    (b"MZ executable", "image/png", "file_type_mismatch"),
    (image_bytes(), "image/jpeg", "file_type_mismatch"),
    (b"text", "text/plain", "unsupported_media_type"),
])
def test_bad_file_is_rejected_without_leaving_a_file(tmp_path, data, mime, code):
    """A filename/content-type claim alone must never let unsafe bytes through."""
    store = SecureDocumentStore(tmp_path)
    with pytest.raises(InvalidUpload) as error:
        save(store, data=data, mime=mime)
    assert error.value.code == code
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


@pytest.mark.parametrize("customer", ["", "../cust-001", "cust/001", "cust\n001"])
def test_unsafe_customer_ids_are_rejected_instead_of_silently_merged(tmp_path, customer):
    store = SecureDocumentStore(tmp_path)
    with pytest.raises(ValueError):
        save(store, customer=customer)
    assert store.list_customer_documents("cust-001") == []


def test_original_bytes_and_verification_metadata_survive_a_restart(tmp_path):
    data = pdf_bytes(identity_text())
    record = save(SecureDocumentStore(tmp_path), data=data)
    restarted = SecureDocumentStore(tmp_path)
    actual, metadata = restarted.get_document_bytes(
        record["document_id"], customer_id="cust-001", session_id="session-1"
    )
    assert actual == data
    assert metadata["sha256_hash"] == record["sha256_hash"]
    assert (tmp_path / record["stored_path"]).suffix == ".pdf"
    assert (tmp_path / record["stored_path"]).resolve().is_relative_to(tmp_path.resolve())


@pytest.mark.parametrize("customer,session", [("cust-002", "session-1"), ("cust-001", "session-2")])
def test_a_document_cannot_be_read_from_another_customer_or_session(tmp_path, customer, session):
    store = SecureDocumentStore(tmp_path)
    record = save(store)
    with pytest.raises(PermissionError):
        store.get_document_bytes(record["document_id"], customer_id=customer, session_id=session)


def test_changed_file_bytes_are_detected_before_they_can_be_used(tmp_path):
    store = SecureDocumentStore(tmp_path)
    record = save(store)
    (tmp_path / record["stored_path"]).write_bytes(pdf_bytes("tampered"))
    assert store.verify_integrity(record["document_id"]) is False
    with pytest.raises(ValueError, match="integrity|SHA-256|Tamper"):
        store.get_document_bytes(record["document_id"], customer_id="cust-001", session_id="session-1")


def test_corrupt_registry_fails_closed_instead_of_forgetting_ownership(tmp_path):
    store = SecureDocumentStore(tmp_path)
    store.metadata_file.write_text("not valid JSON", encoding="utf-8")
    with pytest.raises(ValueError, match="registry"):
        SecureDocumentStore(tmp_path)


def test_registry_cannot_redirect_a_read_outside_the_storage_root(tmp_path):
    root = tmp_path / "uploads"
    store = SecureDocumentStore(root)
    record = save(store)
    outside = tmp_path / "other-customer.pdf"
    outside.write_bytes(pdf_bytes(identity_text()))
    registry = json.loads(store.metadata_file.read_text(encoding="utf-8"))
    registry[record["document_id"]]["stored_path"] = "../other-customer.pdf"
    store.metadata_file.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ValueError, match="path|root"):
        store.get_document_bytes(record["document_id"], customer_id="cust-001", session_id="session-1")


def test_failed_registry_write_rolls_back_the_uploaded_file(tmp_path, monkeypatch):
    store = SecureDocumentStore(tmp_path)

    def fail():
        raise OSError("simulated disk write failure")

    monkeypatch.setattr(store, "_save_registry", fail)
    with pytest.raises(OSError):
        save(store)
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


def test_parallel_uploads_from_separate_store_instances_do_not_lose_records(tmp_path):
    """Two chat sessions uploading together must not overwrite the registry."""
    stores = [SecureDocumentStore(tmp_path), SecureDocumentStore(tmp_path)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda i: save(stores[i % 2], session=f"session-{i}"), range(12)))
    restarted = SecureDocumentStore(tmp_path)
    assert len(restarted.list_customer_documents("cust-001")) == 12
    assert all(restarted.verify_integrity(record["document_id"]) for record in records)


def test_deleting_an_upload_removes_both_original_and_metadata(tmp_path):
    store = SecureDocumentStore(tmp_path)
    record = save(store)
    store.delete_document(record["document_id"], customer_id="cust-001", session_id="session-1")
    assert not (tmp_path / record["stored_path"]).exists()
    assert SecureDocumentStore(tmp_path).list_customer_documents("cust-001") == []


@pytest.mark.parametrize("variant", ["encrypted", "javascript", "embedded_file", "too_many_pages", "annotation_action"])
def test_encrypted_active_or_excessive_pdfs_are_rejected_before_storage(tmp_path, variant):
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    if variant == "encrypted":
        writer.encrypt("test-password")
    elif variant == "javascript":
        action = DictionaryObject({NameObject("/S"): NameObject("/JavaScript")})
        writer._root_object[NameObject("/OpenAction")] = writer._add_object(action)
    elif variant == "embedded_file":
        writer.add_attachment("program.exe", b"MZ")
    elif variant == "too_many_pages":
        for _ in range(40):
            writer.add_blank_page(width=595, height=842)
    else:
        annotation = DictionaryObject({
            NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/A"): DictionaryObject({NameObject("/S"): NameObject("/Launch")}),
        })
        page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
    output = BytesIO()
    writer.write(output)
    store = SecureDocumentStore(tmp_path)
    with pytest.raises(InvalidUpload) as error:
        save(store, data=output.getvalue())
    assert error.value.code == "invalid_file_format"
    assert store.list_customer_documents("cust-001") == []


def test_upload_size_limit_is_enforced_by_storage_not_only_the_http_router(tmp_path):
    store = SecureDocumentStore(tmp_path, max_file_size_bytes=100)
    with pytest.raises(InvalidUpload) as error:
        save(store)
    assert error.value.code == "upload_too_large"


def test_existing_document_ids_cannot_overwrite_an_original(tmp_path):
    store = SecureDocumentStore(tmp_path)
    first = save(store)
    with pytest.raises(ValueError, match="overwrite"):
        store.store_document(
            customer_id="cust-001", session_id="session-1", document_id=first["document_id"],
            filename="different.pdf", content_bytes=pdf_bytes("replacement"), mime_type="application/pdf", doc_kind="id_card",
        )
    assert store.verify_integrity(first["document_id"])


def test_customer_ids_differing_only_by_case_do_not_share_a_windows_folder(tmp_path):
    store = SecureDocumentStore(tmp_path)
    first, second = save(store, customer="Customer"), save(store, customer="customer")
    assert Path(first["stored_path"]).parent != Path(second["stored_path"]).parent
    assert len(store.list_customer_documents("Customer")) == 1
    assert len(store.list_customer_documents("customer")) == 1


def test_registry_reads_return_copies_that_cannot_change_authorization(tmp_path):
    store = SecureDocumentStore(tmp_path)
    first = save(store)
    store.list_customer_documents("cust-001")[0]["customer_id"] = "cust-002"
    store.get_document_bytes(first["document_id"], customer_id="cust-001", session_id="session-1")