# Reuniões

Uma nota por reunião em `reunioes/AAAA/MM/`. Seções: Objetivo, Participantes, Contexto anterior, Pauta,
Discussões, Decisões, Pendências, Dúvidas em aberto, Próximos passos, Referências.

## Criar — `meetings create --input -`

```json
{
  "request_id": "req-20261020-reuniao-atlas",
  "title": "Alinhamento do Atlas",
  "date": "hoje",
  "start_time": "10h",
  "participants": ["João Silva", "Maria"],
  "related_ids": ["<id do projeto Atlas>"],
  "objective": "Definir a estratégia de migração"
}
```

- A partir de um compromisso: `{"request_id", "appointment_id": "<id>"}` (título, data, horário e
  participantes vêm do compromisso).
- Horário não informado fica vazio — não invente. Participantes conhecidos são vinculados; homônimos
  ficam só com o nome (o resultado avisa: pergunte quem é, se importar).
- `--dry-run` mostra o plano.

## Reunião ativa

"Estou na reunião do Atlas" → `meetings start <ref>` (cria antes se não existir). Enquanto estiver
`in_progress`, anotações sem reunião explícita vão para ela. `meetings active` mostra qual é.
Sem reunião ativa e sem referência → `NOT_FOUND`; mais de uma → `AMBIGUOUS_MATCH`: pergunte. **Nunca
escolha a mais recente por conta própria.** "Terminou a reunião" → `meetings end [ref] [--end-time 11h]`.

## Anotar — `meetings note --input -`

```json
{
  "request_id": "req-20261020-atlas-nota-1",
  "meeting": "Atlas",
  "entries": [
    {"kind": "discussion", "content": "Avaliada a migração para mensageria.", "author": "João"},
    {"kind": "decision", "content": "Usar fila assíncrona para o ABC."},
    {"kind": "question", "content": "Qual o volume diário de simulações?"}
  ],
  "tasks": [
    {"title": "Levantar volume diário de simulações", "assignee_name": "Maria", "due_date": "sexta"}
  ]
}
```

- `kind`: `objective`, `context`, `agenda`, `discussion`, `decision`, `task` (texto livre),
  `question`, `next_step`, `risk`, `reference`. `certainty: hypothesis` para suposições.
- Sem `meeting` → usa a reunião ativa.
- `tasks` viram pendências vinculadas à reunião (mesma transação). Só crie tarefa para ação
  efetivamente atribuída/combinada — discussão não é tarefa, pauta não é decisão.
- Decisão relevante de arquitetura: além da ata, considere uma ADR com `decided_in` → reunião
  (ver [classification](classification.md#decisões-adr)); pergunte se o usuário quer formalizar.

## Corrigir a ata — `meetings update --input -`

Correções exigem `reason` e preservam o original em `## Histórico`:

```json
{
  "request_id": "req-20261021-atlas-corr",
  "meeting": "<id>",
  "corrections": [{"section": "Decisões", "replaces": "Usar fila assíncrona para o ABC.",
                   "content": "Usar fila assíncrona para o ABC a partir de dezembro."}],
  "reason": "Usuário corrigiu a data de início"
}
```

Também: `date`/`start_time` (reagenda e move o arquivo), `status`, `add_participants`, `add_related_ids`,
`appointment_id`, `description`.

## Consultar

- `meetings list [--date D] [--related <id>] [--participant <nome>] [--query <assunto>]`
- `meetings read <ref> [--date D]` — nota + `summary`.
- `meetings summarize <ref>` — só o registrado: discussões, decisões, pendências, responsáveis, prazos,
  dúvidas. Se não há decisões/ata, diga isso (`notice`) — não preencha com suposições.
- `meetings brief [ref] [--date D]` — preparação (registrado x sugestões; ver [retrieval](retrieval.md#briefings)).
- "Quais pendências saíram da última reunião?" → `tasks list --meeting last`.
