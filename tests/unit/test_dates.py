"""Relative date resolution (clock fixed on Tuesday 2026-10-20 09:00 -03:00, catalog §2.3)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from context_vault.errors import ValidationError
from context_vault.services.dates import parse_datetime, parse_day, parse_range, resolve

TZ = "America/Sao_Paulo"
NOW = datetime(2026, 10, 20, 9, 0, tzinfo=ZoneInfo(TZ))


def r(text):
    return resolve(text, NOW, TZ).to_dict()


@pytest.mark.parametrize("text,expected", [
    ("hoje", "2026-10-20"), ("amanhã", "2026-10-21"), ("amanha", "2026-10-21"), ("depois de amanhã", "2026-10-22"),
    ("ontem", "2026-10-19"), ("quinta", "2026-10-22"), ("quinta-feira", "2026-10-22"), ("sexta", "2026-10-23"),
    ("na sexta", "2026-10-23"), ("até sexta", "2026-10-23"), ("segunda", "2026-10-26"), ("domingo", "2026-10-25"),
    ("quinta da próxima semana", "2026-10-29"), ("próxima segunda", "2026-10-26"), ("esta segunda", "2026-10-19"),
    ("daqui a 3 dias", "2026-10-23"), ("em 2 semanas", "2026-11-03"), ("fim do mês", "2026-10-31"),
    ("25/10", "2026-10-25"), ("25/10/2026", "2026-10-25"), ("2026-11-02", "2026-11-02"), ("dia 5", "2026-11-05"),
])
def test_dates(text, expected):
    out = r(text)
    assert out["date"] == expected
    assert out["reference_date"] == "2026-10-20"


def test_same_weekday_is_ambiguous():
    out = r("terça")
    assert out["ambiguous"] is True
    assert out["date"] == "2026-10-27"
    assert out["alternatives"][0]["date"] == "2026-10-20"


def test_next_weekday_still_ahead_is_ambiguous():
    out = r("próxima quinta")
    assert out["ambiguous"] is True and out["date"] == "2026-10-22"
    assert out["alternatives"][0]["date"] == "2026-10-29"
    assert r("sexta")["ambiguous"] is False  # plain "sexta" is the coming Friday (CV-025)


def test_week_ranges():
    nxt = r("próxima semana")
    assert (nxt["kind"], nxt["date"], nxt["end_date"]) == ("range", "2026-10-26", "2026-11-01")
    this = r("nesta semana")
    assert (this["date"], this["end_date"]) == ("2026-10-19", "2026-10-25")
    assert parse_range("esta semana", NOW, TZ)[1].isoformat() == "2026-10-25"


def test_times_and_intervals():
    out = r("amanhã às 10h")
    assert out["starts_at"] == "2026-10-21T10:00:00-03:00"
    out = r("amanhã das 14h30 às 15h30")
    assert (out["time"], out["end_time"]) == ("14:30", "15:30")
    assert out["ends_at"] == "2026-10-21T15:30:00-03:00"
    assert r("quinta às 14h")["starts_at"] == "2026-10-22T14:00:00-03:00"
    assert r("3h da tarde")["time"] == "15:00"
    assert r("meio-dia")["time"] == "12:00"
    assert r("às 14h")["kind"] == "time"


def test_parse_helpers():
    assert parse_day("sexta", NOW, TZ)[0].isoformat() == "2026-10-23"
    assert parse_day("2026-10-30", NOW, TZ) == (datetime(2026, 10, 30).date(), None)
    start, res = parse_datetime("2026-10-22T14:00", NOW, TZ)
    assert start.isoformat() == "2026-10-22T14:00:00-03:00" and res is None
    start, res = parse_datetime("2026-10-22", NOW, TZ)
    assert start is None and res.date.isoformat() == "2026-10-22"  # date only: time missing
    with pytest.raises(ValidationError):
        parse_day("próxima semana", NOW, TZ)  # a range is not a day


def test_unknown_expression():
    with pytest.raises(ValidationError):
        resolve("algum dia", NOW, TZ)


@pytest.mark.parametrize("text", ["começo do mês que vem", "meados da próxima semana", "lá pela sexta"])
def test_vague_expressions_are_ambiguous(text):  # CV-073
    out = r(text)
    assert out["ambiguous"] is True and "Expressão vaga" in out["notes"][0]


@pytest.mark.parametrize("text", ["fim do mês", "sexta", "amanhã às 10h", "meio-dia"])
def test_precise_expressions_are_not_vague(text):
    assert "notes" not in r(text) or not any("vaga" in n for n in r(text)["notes"])
