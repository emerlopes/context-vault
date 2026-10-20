import pytest

from context_vault.errors import PermissionDeniedError
from context_vault.services.contradictions import find_contradictions
from context_vault.services.privacy import find_credentials, find_sensitive, scan
from context_vault.storage.markdown import SectionEditor


def _found(existing: str, new: str) -> list[dict]:
    return find_contradictions([("Integrações", existing)], new)


@pytest.mark.parametrize("existing,new", [
    ("ABC consulta XYZ.", "O ABC não consulta mais o XYZ."),
    ("ABC consulta XYZ.", "ABC deixou de consultar XYZ"),
    ("O ABC não usa o XYZ.", "O ABC usa o XYZ para validar propostas."),
])
def test_opposite_statements_are_flagged(existing, new):
    assert _found(existing, new)


@pytest.mark.parametrize("existing,new", [
    ("ABC consulta XYZ.", "ABC também consulta DEF."),
    ("ABC consulta XYZ.", "O DEF não tem integração com o QRS."),
    ("ABC não consulta XYZ.", "ABC não consulta o XYZ diretamente."),
    ("_(Hipótese — não confirmada)_ A causa pode ser o XYZ.", "A causa não é o XYZ."),
])
def test_compatible_or_unconfirmed_statements_are_not_flagged(existing, new):
    assert not _found(existing, new)


def test_temporal_change_is_identified():
    assert _found("ABC consulta XYZ.", "O ABC não consulta mais o XYZ.")[0]["temporal"] is True
    assert _found("ABC consulta XYZ.", "ABC nunca consultou XYZ.")[0]["temporal"] is False


@pytest.mark.parametrize("text", [
    "senha: hunter2024", "password=abc12345", "a senha do banco: S3gred0!",
    "-----BEGIN RSA PRIVATE KEY-----", "AKIAABCDEFGHIJKLMNOP", "postgres://app:s3cr3t@db.local/x",
    "token ghp_abcdefghijklmnopqrstuvwxyz0123456789",
])
def test_credentials_detected(text):
    assert find_credentials(text)


@pytest.mark.parametrize("text", [
    "A senha é forte.", "Precisamos rotacionar o token amanhã.", "O token expira em 1h",
    "Ver https://exemplo.com/docs", "Rodar pip install para instalar",
    "Fizemos o diagnóstico do problema de performance.",
])
def test_technical_text_is_not_flagged(text):
    assert not find_credentials(text)
    assert not find_sensitive(text)


def test_sensitive_categories():
    cats = {f["category"] for f in find_sensitive("Está de licença médica e passando por um divórcio; "
                                                  "teve avaliação de desempenho ruim.")}
    assert cats == {"health", "family", "personal_evaluation"}


def test_scan_refuses_credentials_without_echoing_values():
    with pytest.raises(PermissionDeniedError) as exc:
        scan(["ok", "senha: naoMostrar123"])
    assert "naoMostrar123" not in str(exc.value.to_dict())


def test_retract_moves_statement_to_history():
    editor = SectionEditor("# X\n\n## Integrações\n\nABC consulta XYZ.\n<!-- cv:event=1 source=user at=t -->\n\n"
                           "ABC consulta QRS.\n\n## Histórico\n")
    removed = editor.retract("abc consulta xyz", history_label="2026-10-20", reason="mudou")
    assert removed == "ABC consulta XYZ."
    current, history = editor.body.split("## Histórico")
    assert "XYZ" not in current and "ABC consulta QRS." in current and "cv:event=1" not in current
    assert "> ABC consulta XYZ." in history and "Motivo: mudou" in history
    assert editor.retract("inexistente", history_label="x") is None
