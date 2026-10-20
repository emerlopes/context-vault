# Convenções

## Invocação

- Opções globais vêm **antes** do comando: `context-vault --repo ~/minha-memoria --output text status`.
- Saída padrão: envelope JSON em stdout — `{"status": "success", "operation": "...", ...}` ou
  `{"status": "error", "operation": "...", "error": {"code", "message", "details"}}`. Use sempre o JSON;
  `--output text` é para humanos.
- Entradas JSON por arquivo (`--input arquivo.json`) ou pela entrada padrão (`--input -`), por exemplo
  com heredoc:

  ```bash
  context-vault apply --proposal - <<'EOF'
  {"request_id": "...", "operation": "memory.upsert", ...}
  EOF
  ```

- Repositório: `--repo` > `CONTEXT_VAULT_REPO` > `~/.config/context-vault/config.yaml` > `~/context-vault-memory`.
- `context-vault <comando> --help` lista as opções reais; prefira-o a adivinhar parâmetros.

## Exit codes

| Exit | Código |
|---|---|
| 0 | sucesso |
| 1 | `INTERNAL_ERROR` |
| 2 | uso inválido da CLI (opção errada) |
| 3 | `NOT_FOUND` |
| 4 | `AMBIGUOUS_MATCH` |
| 5 | `VALIDATION_ERROR` |
| 6 | `REVISION_CONFLICT` |
| 7 | `PERMISSION_DENIED` |
| 8 | `REPOSITORY_UNAVAILABLE` |
| 9 | `INDEX_INCONSISTENT` (rode `index rebuild`) |
| 10 | `GIT_ERROR` |
| 11 | `CONFIRMATION_REQUIRED` |
| 12 | `LOCK_TIMEOUT` |

Erros de sistema de arquivos (repositório somente leitura, sem permissão, disco cheio) chegam como
`REPOSITORY_UNAVAILABLE` com `details.saved: false`; falhas inesperadas como `INTERNAL_ERROR` com
`details.saved: false`. Em ambos nada foi gravado: diga isso ao usuário. Caminho fora do repositório
(`../`, absoluto, `.git`, link simbólico para fora) → `PERMISSION_DENIED`.

## `request_id`

Único por intenção do usuário, estável entre tentativas da **mesma** operação (ex.:
`req-<AAAAMMDD>-<assunto>-<n>`). Repetir com o mesmo conteúdo devolve o resultado original
(`idempotent_replay: true`) sem duplicar. Mesmo `request_id` com conteúdo diferente é recusado: gere
outro. Reenviar com `"confirmed": true` após uma confirmação pode manter o mesmo `request_id` (pedidos
recusados não são registrados).

## IDs e revisões

- IDs são UUIDv7 estáveis; `read` aceita ID, prefixo com 8+ caracteres ou caminho relativo.
- `revision` (`sha256:…`) do `read` vai em `expected_revision`; `REVISION_CONFLICT` = alguém mudou o
  arquivo depois da sua leitura: leia de novo e reavalie.

## Estrutura da memória

```text
INDEX.md                 catálogo gerado (não editar)
dominios/                domain
projetos/                project
arquitetura/             architecture
arquitetura/decisoes/    architecture_decision (ADR-0001 …)
pessoas-times/pessoas/   person
pessoas-times/times/     team
reunioes/AAAA/MM/        meeting
agenda/AAAA/MM.yaml      compromissos
pendencias/tarefas.yaml  tarefas
.context-vault/          índice, inbox, diário, locks, cache (interno)
```

## Seções por tipo

| Tipo | Seções |
|---|---|
| domain | Visão geral, Conceitos, Sistemas e serviços, Processos, Regras de negócio, Integrações, Responsáveis, Dependências, Dúvidas conhecidas, Histórico, Referências |
| project | Visão geral, Objetivos, Escopo, Status atual, Entregas, Marcos, Riscos, Bloqueios, Dependências, Decisões, Pessoas envolvidas, Próximos passos, Histórico de atualizações, Referências |
| architecture | Contexto, Componentes envolvidos, Funcionamento, Contratos, Dependências, Restrições, Riscos, Decisões relacionadas, Histórico, Referências |
| architecture_decision | Contexto, Problema, Alternativas consideradas, Decisão, Justificativa, Consequências, Riscos, Histórico, Referências |
| person | Função, Responsabilidades, Projetos, Sistemas sob responsabilidade, Acordos, Histórico, Referências |
| team | Visão geral, Membros, Responsabilidades, Sistemas, Projetos, Histórico, Referências |
| meeting | Objetivo, Participantes, Contexto anterior, Pauta, Discussões, Decisões, Pendências, Dúvidas em aberto, Próximos passos, Referências |

Uma seção inexistente é criada antes de Histórico/Referências. Não escreva em `Histórico` diretamente:
o Core move para lá o que é substituído.

## Metadados úteis (`note` / `meta`)

- Todas: `title`, `description`, `aliases` (siglas, apelidos), `entities` (sistemas/termos citados),
  `tags`, `status`.
- project: `status` (`planned`, `active`, `blocked`, `paused`, `completed`, `cancelled`, `archived`),
  `owner`, `start_date`, `target_date`, `priority`.
- person: `role`, `responsibilities`. ADR: `status`, `decision_date`, `supersedes`.
- Campos gerenciados pelo Core (`milestones`, `blockers`, `memberships`, `superseded_by`, `team_ids`,
  `member_ids`) só mudam pelas operações próprias.

## Origem (`source`)

`type`: `user` (o usuário disse), `meeting` (com `meeting_id`), `document` (com `reference`),
`agent_inference` (sua conclusão — fica marcada como não confirmada), `import`. Inclua
`original_text` com a frase do usuário e `effective_date` quando ele disser desde quando vale.

## Manutenção

`status`, `validate`, `index rebuild`, `index check`, `recover` (transações interrompidas). Esses
comandos não alteram conteúdo de conhecimento.
