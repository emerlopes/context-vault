"""Relative date/time resolution in Portuguese (spec §12.9, catalog §2.3).

Always resolved against the real "now" of the environment in the configured timezone
(`Vault.now()`), never against dates mentioned earlier in a conversation.

Weeks start on Monday. Rules:

- `hoje`, `amanhã`, `depois de amanhã`, `ontem`, `anteontem`.
- `<dia da semana>` (`quinta`, `na sexta`, `sexta-feira`): next occurrence after today. Said on the
  same weekday it is ambiguous (today or in 7 days) → next week, `ambiguous: true`.
- `esta/nesta <dia>`: occurrence in the current week (may be in the past → `past: true`).
- `próxima <dia>` / `<dia> que vem`: if the day is still ahead this week it is ambiguous (this week or
  the next one) → nearest, `ambiguous: true`; otherwise next week. `<dia> da próxima semana` → next week.
- `esta semana`, `próxima semana`/`semana que vem`, `este mês`, `próximo mês`: ranges.
- `fim do mês`, `daqui a N dias`, `em N semanas`, `dia 25`, `25/10`, `25/10/2026`, `2026-10-25`.
- Times: `10h`, `14h30`, `14:30`, `às 10`, `meio-dia`, `3h da tarde`; intervals `das 14h30 às 15h30`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from ..clock import get_zone
from ..errors import ValidationError
from ..storage.markdown import strip_accents

WEEKDAYS = {
    "segunda": 0, "seg": 0, "terca": 1, "ter": 1, "quarta": 2, "qua": 2, "quinta": 3, "qui": 3,
    "sexta": 4, "sex": 4, "sabado": 5, "sab": 5, "domingo": 6, "dom": 6,
}
WEEKDAY_NAMES = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
NUMBERS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
           "oito": 8, "nove": 9, "dez": 10, "quinze": 15, "trinta": 30}
FILLERS = {"na", "no", "a", "as", "o", "os", "de", "do", "da", "dos", "das", "em", "para", "pra", "ate", "dia",
           "e", "feira", "pela", "pelo", "proximo", "proxima", "que", "vem", "esta", "este", "nesta", "neste",
           "essa", "esse", "nessa", "nesse", "agora", "hora", "horas", "manha", "tarde", "noite"}

_WD = r"(segunda|terca|quarta|quinta|sexta|sabado|domingo|seg|ter|qua|qui|sex|sab|dom)(?:[- ]feira)?"
_NUM = r"(\d+|" + "|".join(NUMBERS) + r")"
_HOUR = r"(\d{1,2})(?:\s*(?:h|:)\s*(\d{2})?|\s*horas?)(?:\s*min)?"


@dataclass
class Resolution:
    input: str
    reference: date
    timezone: str
    kind: str = "date"  # date | range | time
    date: date | None = None
    end_date: date | None = None
    time: time | None = None
    end_time: time | None = None
    ambiguous: bool = False
    alternatives: list[date] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unparsed: str | None = None

    def starts_at(self) -> datetime | None:
        if self.date is None or self.time is None:
            return None
        return datetime.combine(self.date, self.time, tzinfo=get_zone(self.timezone))

    def ends_at(self) -> datetime | None:
        if self.date is None or self.end_time is None:
            return None
        end = datetime.combine(self.date, self.end_time, tzinfo=get_zone(self.timezone))
        start = self.starts_at()
        if start is not None and end <= start:
            end += timedelta(days=1)
        return end

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "input": self.input, "kind": self.kind, "reference_date": self.reference.isoformat(),
            "timezone": self.timezone,
            "date": self.date.isoformat() if self.date else None,
            "weekday": WEEKDAY_NAMES[self.date.weekday()] if self.date else None,
            "ambiguous": self.ambiguous,
        }
        if self.end_date:
            data["end_date"] = self.end_date.isoformat()
        if self.time:
            data["time"] = self.time.strftime("%H:%M")
        if self.end_time:
            data["end_time"] = self.end_time.strftime("%H:%M")
        if self.starts_at():
            data["starts_at"] = self.starts_at().isoformat()  # type: ignore[union-attr]
        if self.ends_at():
            data["ends_at"] = self.ends_at().isoformat()  # type: ignore[union-attr]
        if self.date and self.kind == "date" and self.date < self.reference:
            data["past"] = True
        if self.alternatives:
            data["alternatives"] = [{"date": d.isoformat(), "weekday": WEEKDAY_NAMES[d.weekday()]}
                                    for d in self.alternatives]
        if self.notes:
            data["notes"] = self.notes
        if self.unparsed:
            data["unparsed"] = self.unparsed
        return data


def _norm(text: str) -> str:
    text = strip_accents(text).lower()
    text = text.replace("–", "-").replace("à", "a")
    return re.sub(r"\s+", " ", text).strip(" ?.!,")


def _number(token: str) -> int:
    return int(token) if token.isdigit() else NUMBERS[token]


def _hour(h: str, m: str | None, period: str | None) -> time:
    hour, minute = int(h), int(m or 0)
    if period in ("tarde", "noite") and hour < 12:
        hour += 12
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValidationError(f"Horário inválido: {h}:{m or '00'}")
    return time(hour, minute)


def _extract_times(text: str, res: Resolution) -> str:
    period = r"(?:\s*da (manha|tarde|noite))?"
    interval = re.compile(r"\b(?:das?|de|entre)\s+" + _HOUR + period + r"\s+(?:as?|ate|e|-)\s+" + _HOUR + period + r"\b")
    match = interval.search(text)
    if match:
        res.time = _hour(match.group(1), match.group(2), match.group(3))
        res.end_time = _hour(match.group(4), match.group(5), match.group(6) or match.group(3))
        return text[:match.start()] + " " + text[match.end():]
    single = re.compile(r"\b(?:as?\s+)?" + _HOUR + period + r"\b")
    match = single.search(text)
    if match:
        res.time = _hour(match.group(1), match.group(2), match.group(3))
        return text[:match.start()] + " " + text[match.end():]
    bare = re.compile(r"\bas\s+(\d{1,2})" + period + r"\b")
    match = bare.search(text)
    if match:
        res.time = _hour(match.group(1), None, match.group(2))
        return text[:match.start()] + " " + text[match.end():]
    for word, value in (("meio-dia", time(12, 0)), ("meio dia", time(12, 0)), ("meia-noite", time(0, 0))):
        if word in text:
            res.time = value
            return text.replace(word, " ")
    return text


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _month_end(day: date) -> date:
    first_next = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
    return first_next - timedelta(days=1)


def _safe_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        raise ValidationError(f"Data inválida: {day:02d}/{month:02d}/{year}") from None


def _extract_date(text: str, res: Resolution) -> str:
    today = res.reference

    def take(pattern: str) -> re.Match[str] | None:
        return re.search(pattern, text)

    def cut(match: re.Match[str]) -> str:
        return text[:match.start()] + " " + text[match.end():]

    if m := take(r"\b(\d{4})-(\d{2})-(\d{2})\b"):
        res.date = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return cut(m)
    if m := take(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b"):
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        res.date = _safe_date(year, int(m.group(2)), int(m.group(1)))
        if not m.group(3) and res.date < today:
            res.notes.append("Data sem ano já passou neste ano; confirme se é do próximo ano.")
            res.ambiguous = True
            res.alternatives = [_safe_date(year + 1, res.date.month, res.date.day)]
        return cut(m)
    if m := take(r"\bdepois de amanha\b"):
        res.date = today + timedelta(days=2)
        return cut(m)
    if m := take(r"\banteontem\b"):
        res.date = today - timedelta(days=2)
        return cut(m)
    if m := take(r"\bamanha\b"):
        res.date = today + timedelta(days=1)
        return cut(m)
    if m := take(r"\bontem\b"):
        res.date = today - timedelta(days=1)
        return cut(m)
    if m := take(r"\bhoje\b"):
        res.date = today
        return cut(m)
    if m := take(r"\b(?:daqui a|em|dentro de)\s+" + _NUM + r"\s+(dias?|semanas?|meses|mes)\b"):
        amount = _number(m.group(1))
        unit = m.group(2)
        if unit.startswith("dia"):
            res.date = today + timedelta(days=amount)
        elif unit.startswith("semana"):
            res.date = today + timedelta(weeks=amount)
        else:
            month = today.month - 1 + amount
            first = date(today.year + month // 12, month % 12 + 1, 1)
            res.date = first.replace(day=min(today.day, _month_end(first).day))
        return cut(m)
    if m := take(r"\b" + _WD + r"\s+da\s+(?:proxima semana|semana que vem)\b"):
        target = WEEKDAYS[m.group(1)]
        res.date = _week_start(today) + timedelta(days=7 + target)
        return cut(m)
    if m := take(r"\b(?:(?:proxim[ao]|n?est[ae]|n?ess[ae])\s+)" + _WD + r"(?:\s+que vem)?\b") \
            or take(r"\b" + _WD + r"\s+que vem\b"):
        target = WEEKDAYS[m.group(1)]
        phrase = m.group(0)
        this_week = _week_start(today) + timedelta(days=target)
        if re.match(r"n?(est|ess)", phrase):
            res.date = this_week
            if this_week < today:
                res.notes.append("O dia citado desta semana já passou.")
        elif target > today.weekday():
            res.date = this_week
            res.ambiguous = True
            res.alternatives = [this_week + timedelta(days=7)]
            res.notes.append("\"Próxima\" pode significar esta semana ou a seguinte; confirme.")
        else:
            res.date = this_week + timedelta(days=7)
        return cut(m)
    if m := take(r"\b" + _WD + r"\b"):
        target = WEEKDAYS[m.group(1)]
        delta = (target - today.weekday()) % 7
        if delta == 0:
            res.date = today + timedelta(days=7)
            res.ambiguous = True
            res.alternatives = [today]
            res.notes.append("O dia da semana citado é hoje; confirme se é hoje ou na próxima semana.")
        else:
            res.date = today + timedelta(days=delta)
        return cut(m)
    if m := take(r"\b(?:proxima semana|semana que vem)\b"):
        res.kind = "range"
        res.date = _week_start(today) + timedelta(days=7)
        res.end_date = res.date + timedelta(days=6)
        return cut(m)
    if m := take(r"\b(?:n?est[ae]|n?ess[ae])\s+semana\b"):
        res.kind = "range"
        res.date = _week_start(today)
        res.end_date = res.date + timedelta(days=6)
        return cut(m)
    if m := take(r"\b(?:proximo mes|mes que vem)\b"):
        res.kind = "range"
        res.date = _month_end(today) + timedelta(days=1)
        res.end_date = _month_end(res.date)
        return cut(m)
    if m := take(r"\b(?:n?est[ae]|n?ess[ae])\s+mes\b"):
        res.kind = "range"
        res.date = today.replace(day=1)
        res.end_date = _month_end(today)
        return cut(m)
    if m := take(r"\b(?:fim|final) do mes\b"):
        res.date = _month_end(today)
        return cut(m)
    if m := take(r"\bdia\s+(\d{1,2})\b"):
        day = int(m.group(1))
        candidate = _safe_date(today.year, today.month, day) if day <= _month_end(today).day else None
        if candidate is None or candidate < today:
            nxt = _month_end(today) + timedelta(days=1)
            candidate = _safe_date(nxt.year, nxt.month, day)
        res.date = candidate
        return cut(m)
    return text


def resolve(expression: str, now: datetime, timezone: str) -> Resolution:
    """Resolve a Portuguese date/time expression relative to `now` (already in `timezone`)."""
    if not expression or not expression.strip():
        raise ValidationError("Informe a expressão de data a resolver")
    res = Resolution(input=expression, reference=now.date(), timezone=timezone)
    text = _norm(expression)
    text = _extract_date(text, res)
    text = _extract_times(text, res)
    leftover = [w for w in re.split(r"[\s,]+", text) if w and w not in FILLERS]
    if res.date is None and res.time is None:
        raise ValidationError(f"Não foi possível interpretar a data: {expression!r}",
                              details={"input": expression, "reference_date": res.reference.isoformat()})
    if res.date is None:
        res.kind = "time"
    if leftover:
        res.unparsed = " ".join(leftover)
    return res


def parse_day(value: str | date | None, now: datetime, timezone: str) -> tuple[date | None, Resolution | None]:
    """ISO date or relative expression → (date, resolution if relative). Ranges are refused."""
    if value is None or value == "":
        return None, None
    if isinstance(value, date):
        return value, None
    try:
        return date.fromisoformat(value), None
    except ValueError:
        pass
    res = resolve(value, now, timezone)
    if res.kind != "date" or res.date is None:
        raise ValidationError(f"Esperava uma data, não um intervalo/horário: {value!r}", details=res.to_dict())
    return res.date, res


def parse_range(value: str, now: datetime, timezone: str) -> tuple[date, date]:
    """ISO date, relative date or range expression → inclusive (start, end)."""
    try:
        day = date.fromisoformat(value)
        return day, day
    except ValueError:
        pass
    res = resolve(value, now, timezone)
    if res.date is None:
        raise ValidationError(f"Esperava uma data ou período: {value!r}")
    return res.date, res.end_date or res.date


def parse_datetime(value: str | datetime, now: datetime, timezone: str) -> tuple[datetime | None, Resolution | None]:
    """ISO datetime (naive = configured timezone) or relative expression with a time.

    Returns (None, resolution) when only a date could be resolved (time missing)."""
    zone = get_zone(timezone)
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=zone)), None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = None
    if parsed is not None:
        if len(value.strip()) <= 10:  # plain ISO date: no time informed
            return None, Resolution(input=value, reference=now.date(), timezone=timezone, date=parsed.date())
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)), None
    res = resolve(value, now, timezone)
    if res.kind == "range":
        raise ValidationError(f"Esperava data e horário, não um período: {value!r}", details=res.to_dict())
    if res.date is None:
        res.date = now.date()
        res.notes.append("Sem data explícita: considerado hoje.")
    return res.starts_at(), res
