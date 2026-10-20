# Agenda

Compromissos ficam em `agenda/AAAA/MM.yaml` e são gerenciados só pela CLI.

## Datas relativas

O Core resolve expressões em português pela **data atual real** no fuso configurado — não calcule
datas de cabeça. `dates resolve "quinta às 10h"` mostra a interpretação. Aceitos: `hoje`, `amanhã`,
dias da semana, `próxima semana`, `esta semana`, `dd/mm`, `daqui a N dias`, horários (`14h`, `14:30`)
e intervalos (`das 14h às 15h`). Os campos `when`, `date`, `starts_at`, `due_date` aceitam ISO ou a
expressão; a resolução volta em `resolved_dates`.

Ambíguo (`ambiguous_date` com `alternatives`): dia da semana igual a hoje, "próxima quinta" quando a
quinta desta semana ainda não passou, `dd/mm` já passado sem ano. Pergunte qual data.

## Criar — `agenda add --input -`

```json
{
  "request_id": "req-20261020-agenda-abc",
  "title": "Reunião sobre migração do ABC",
  "when": "quinta das 10h às 11h",
  "participants": ["João Silva"],
  "related_ids": ["<id do ABC ou do projeto>"],
  "description": "Alinhar a migração para assíncrono",
  "source": {"type": "user", "original_text": "Marca reunião quinta 10h sobre a migração do ABC com o João"}
}
```

Também: `date` + `start_time` + `end_time`, ou `starts_at`/`ends_at` ISO. `--dry-run` valida (datas,
conflitos, duplicatas) sem gravar.

- **Sem horário** → `missing_time`: pergunte o horário. Só crie sem horário com `all_day: true` quando o
  usuário disser que é o dia todo.
- **Duração nunca é inventada**: sem término informado, deixe sem `end_time`.
- **Conflitos**: o resultado traz `conflicts` e `warnings`; avise o usuário ("Conflita com … às 10h").
  Se o repositório exigir (`schedule_conflict`), pergunte antes.
- **Duplicata**: mesmo título e início → nada é criado (`duplicate: true`): diga que já estava na agenda.
  Mesmo título no mesmo dia → `possible_duplicate`: pergunte.
- Relacione ao assunto (`related_ids`) quando ele foi identificado com segurança.

## Consultar — `agenda list`

`--date amanhã`, `--date "esta semana"`, `--from/--to`, `--at 14h`, `--next`, `--query Atlas`,
`--related <id>`, `--all` (inclui cancelados). Sem filtros: de hoje em diante. Para "o que tenho
amanhã?" prefira `daily brief --date amanhã` (traz contexto e pendências relacionadas).

## Alterar

- Reagendar / mudar dados: `agenda update --input -` com `{"request_id", "id", "when": "sexta 15h", "reason"}`
  (ou `title`, `add_participants`, `location`, `add_related_ids`…). A duração conhecida é mantida e o
  histórico preservado.
- Cancelar: `agenda cancel <id> --reason "..."` (o registro fica, com status `cancelled`).
- Concluir: `agenda complete <id>`.
- Ler: `agenda read <id> [--history]`.

"Desmarca a reunião de quinta": `agenda list --date quinta` → se houver mais de uma, pergunte qual →
`agenda cancel`. Cancelar um compromisso nunca apaga a nota de reunião vinculada.
