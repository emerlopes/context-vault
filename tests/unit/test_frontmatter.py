import pytest

from context_vault.errors import ValidationError
from context_vault.ids import new_id
from context_vault.models import parse_note_meta
from context_vault.storage.frontmatter import parse_document, render_document
from context_vault.storage.yamlio import atomic_write, revision_of


def test_roundtrip_is_deterministic():
    meta = parse_note_meta(
        {
            "id": new_id(),
            "type": "meeting",
            "title": "Arquitetura do ABC",
            "date": "2026-10-20",
            "start_time": "10:00",
            "created_at": "2026-10-20T09:00:00-03:00",
            "updated_at": "2026-10-20T09:00:00-03:00",
        }
    )
    text = render_document(meta.model_dump(), "# Arquitetura do ABC\n\n## Objetivo\n")
    doc = parse_document(text)
    again = parse_note_meta(doc.meta)
    assert again == meta
    assert render_document(again.model_dump(), doc.body) == text
    assert 'start_time: "10:00"' in text or "start_time: '10:00'" in text
    assert "created_at: 2026-10-20T09:00:00-03:00" in text


def test_crlf_and_bom_tolerated():
    doc = parse_document("\ufeff---\r\ntitle: x\r\n---\r\nbody\r\n")
    assert doc.meta == {"title": "x"}
    assert doc.body.strip() == "body"


@pytest.mark.parametrize("text", ["no frontmatter", "---\ntitle: x\n", "---\n- a\n---\n", "---\n: : :\n---\n"])
def test_invalid_documents(text):
    with pytest.raises(ValidationError):
        parse_document(text)


def test_atomic_write_and_revision(tmp_path):
    path = tmp_path / "a" / "b.md"
    atomic_write(path, "x\n")
    rev = revision_of(path)
    assert rev.startswith("sha256:")
    atomic_write(path, "y\n")
    assert revision_of(path) != rev
    assert path.read_bytes() == b"y\n"
    assert list(path.parent.iterdir()) == [path]
