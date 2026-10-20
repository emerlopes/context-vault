def test_inbox_add_list_and_preserve_text(cli, vault_repo):
    out = cli("inbox", "add", "--text", "Anota que precisamos rever o contrato do serviço QRS, depois explico.",
              "--entity", "QRS", "--question", "O QRS pertence a qual domínio?")
    assert out["commit"]
    entries = cli("inbox", "list")["entries"]
    assert len(entries) == 1
    assert entries[0]["text"].startswith("Anota que precisamos rever")
    assert entries[0]["entities"] == ["QRS"] and entries[0]["pending_question"]
    assert cli("status")["inbox_pending"] == 1
    events = cli("journal", "list")["events"]
    assert events[-1]["operation"] == "inbox.add"
    assert events[-1]["source"]["original_text"].endswith("depois explico.")


def test_inbox_classify_with_proposal_in_single_transaction(cli, vault_repo):
    entry = cli("inbox", "add", "--text", "QRS calcula tarifas")["record_id"]
    out = cli("inbox", "classify", entry[:13], "--proposal", "-",
              stdin='{"request_id":"cls","operation":"memory.create","confirmed":true,'
                    '"note":{"type":"domain","title":"Tarifas","entities":["QRS"]},'
                    '"change":{"section":"Sistemas e serviços","subsection":"QRS","content":"Calcula tarifas."}}')
    assert out["inbox_entry"]["status"] == "classified"
    assert out["inbox_entry"]["classified_to"] == out["record_id"]
    assert cli("inbox", "list")["entries"] == []
    assert cli("status")["git"]["clean"] is True


def test_inbox_classify_to_existing_and_discard(cli, vault_repo):
    note = cli.create("domain", "Tarifas")
    e1 = cli("inbox", "add", "--text", "a")["record_id"]
    e2 = cli("inbox", "add", "--text", "b")["record_id"]
    assert cli("inbox", "classify", e1, "--target", note["record_id"])["classified_to"] == note["record_id"]
    assert cli("inbox", "discard", e2)["entry"]["status"] == "discarded"
    assert len(cli("inbox", "list", "--all")["entries"]) == 2
    assert cli("inbox", "classify", "01900000-dead", "--target", note["record_id"], expect=3)


def test_inbox_requires_text(cli, vault_repo):
    assert cli("inbox", "add", expect=5)["error"]["code"] == "VALIDATION_ERROR"
