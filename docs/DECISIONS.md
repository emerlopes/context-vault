# Decisões técnicas

Decisões tomadas onde a especificação ([main.md](main.md)) era ambígua. Sempre escolher a opção
mais simples, segura e extensível (spec §1).

## D1 — Código separado da memória

O código (`src/`, `skills/`, `tests/`) vive neste repositório. A memória é um repositório Git
separado, criado por `context-vault init` (padrão `~/context-vault-memory`). A estrutura da memória
segue a spec §4 (`INDEX.md`, os 7 módulos, `.context-vault/`, `config.yaml`, `README.md`, `AGENTS.md`).

Resolução do repositório: `--repo` > `CONTEXT_VAULT_REPO` > `~/.config/context-vault/config.yaml`
(`memory.repository`; caminho sobrescrevível por `CONTEXT_VAULT_CONFIG`) > padrão.
Configuração de comportamento: `<repo>/config.yaml` > config do usuário > padrões.

## D2 — Saída JSON por padrão

A CLI é pensada primeiro para agentes: toda saída é um envelope JSON
(`{"status": "success"|"error", "operation": ..., ...}`) em stdout. `--output text` gera texto legível.
Opções globais vêm antes do comando: `context-vault --repo X --output text status`.

## D3 — Exit codes estáveis

| Código | Exit |
|--------|------|
| sucesso | 0 |
| `INTERNAL_ERROR` | 1 |
| uso inválido (Typer) | 2 |
| `NOT_FOUND` | 3 |
| `AMBIGUOUS_MATCH` | 4 |
| `VALIDATION_ERROR` | 5 |
| `REVISION_CONFLICT` | 6 |
| `PERMISSION_DENIED` | 7 |
| `REPOSITORY_UNAVAILABLE` | 8 |
| `INDEX_INCONSISTENT` | 9 |
| `GIT_ERROR` | 10 |
| `CONFIRMATION_REQUIRED` | 11 |
| `LOCK_TIMEOUT` | 12 |

`CONFIRMATION_REQUIRED` e `LOCK_TIMEOUT` foram adicionados aos códigos da spec §19.3.

## D4 — IDs UUIDv7 próprios

Python 3.11–3.13 não tem `uuid.uuid7`. Implementação própria em `ids.py` (RFC 9562, monotônico
dentro do mesmo milissegundo).

## D5 — Data/hora

- Toda data/hora persistida tem fuso explícito (datetimes "naive" são rejeitados).
- "Agora" vem sempre do relógio real no fuso configurado. `CONTEXT_VAULT_NOW` (ISO 8601) existe
  apenas para testes determinísticos.

## D6 — Schemas estritos

Modelos Pydantic com `extra="forbid"`: campos desconhecidos geram `VALIDATION_ERROR`.
Diferenças em relação aos exemplos da spec:

- Todas as notas (inclusive ADR) exigem `created_at`/`updated_at`.
- Notas aceitam, além de `related_ids`, uma lista `relations` tipada (`{type, target_id, note}`) com os
  tipos da spec §16.2.
- Status de domínio/arquitetura/pessoa/time: `active | deprecated | archived`.
- Status de ADR: `proposed | accepted | rejected | deprecated | superseded | archived`.
- Status de reunião: `scheduled | in_progress | completed | cancelled | archived`.
- Compromissos e tarefas guardam `history` (lista de mudanças) para preservar histórico de
  reagendamentos, cancelamentos e conclusões.
- Prioridade: `low | normal | high | urgent`.

## D7 — Pastas por tipo

| Tipo | Pasta |
|------|-------|
| `domain` | `dominios/` |
| `project` | `projetos/` |
| `architecture` | `arquitetura/` |
| `architecture_decision` | `arquitetura/decisoes/` |
| `person` | `pessoas-times/pessoas/` |
| `team` | `pessoas-times/times/` |
| `meeting` | `reunioes/AAAA/MM/` |

`validate` acusa `WRONG_LOCATION` quando o tipo não bate com a pasta.

## D8 — YAML determinístico

Serialização com ordem de campos preservada, datas ISO 8601 sem aspas, strings ambíguas
(ex.: `"10:00"`) entre aspas, UTF-8 e LF. Escritas são atômicas (arquivo temporário + `os.replace`).
Revisão de arquivo = `sha256:` dos bytes.

## D9 — Git controlado

Wrapper com allowlist (`init`, `add`, `commit`, `status`, `log`, `rev-parse`, `diff --cached`).
Não existe API de `push`, `reset`, `clean` ou `checkout`. Se o usuário não tiver identidade Git
configurada, os commits usam `ContextVault <context-vault@localhost>` apenas naquele comando
(sem alterar configuração global). Branch inicial: `main`.

`index.json` e `INDEX.md` são versionados (derivados, mas facilitam auditoria);
`locks/`, `cache/` e `journal/pending/` são ignorados.

## D10 — Lock único por repositório

Um lock global de escrita (`.context-vault/locks/write.lock`) serializa todas as escritas. A
concorrência lógica entre agentes é tratada por `expected_revision` (sha256 do arquivo): quem
leu uma versão antiga recebe `REVISION_CONFLICT`. Lock órfão: processo morto no mesmo host
ou mais de 300 s. Timeout padrão 10 s (`CONTEXT_VAULT_LOCK_TIMEOUT`).

## D11 — Transações com WAL

Antes de alterar cada arquivo, o conteúdo original vai para
`.context-vault/journal/pending/<txid>.json`. O commit Git leva `context-vault-tx: <txid>` na
mensagem. Recuperação: se o commit com aquele txid existe → roll-forward; senão → rollback.
Falha no Git com `auto_commit: true` desfaz a operação inteira (nada é declarado salvo sem
persistência confirmada). Só os arquivos tocados pela transação entram no commit.

## D12 — Origem dentro do Markdown

Cada bloco inserido recebe um comentário HTML invisível
`<!-- cv:event=<id> source=<tipo> at=<data> [meeting=..] [ref=..] [effective=..] -->`.
O evento correspondente fica no diário com o texto original quando informado
(`source.original_text`). Inferências (`agent_inference`) recebem o prefixo visível
`_(Inferência — não confirmada)_`.

## D13 — Modos de alteração de seção

- `merge` (padrão): adiciona só se o conteúdo normalizado ainda não estiver na seção; se estiver,
  nada muda no arquivo e o diário registra `memory.confirm` (nova evidência sem duplicar texto).
- `append`: sempre adiciona.
- `replace` / `memory.correct`: substitui o corpo e move o estado anterior para `## Histórico`
  (citado, com data e motivo). Exige confirmação quando `confirm_conflicting_updates`.

Novas seções entram antes de `Histórico`/`Referências`. Seções são localizadas sem diferenciar
maiúsculas/acentos.

## D14 — Confirmações (modo equilibrado)

`apply` recusa com `CONFIRMATION_REQUIRED` (exit 11, `details.reasons`) quando houver: tópico novo,
possível duplicata (mesmo título/alias e tipo), correção, arquivamento, ou classificação `medium`/`low`.
O agente pergunta ao usuário e reenvia com `"confirmed": true`. `autonomy: conservative` exige
confirmação para toda alteração; `autonomous` dispensa tópico novo e arquivamento.

## D15 — Idempotência

`.context-vault/requests.jsonl` (versionado) guarda `request_id` → hash do conteúdo + resultado.
Repetir o mesmo pedido devolve o resultado original com `idempotent_replay: true` (o campo `commit`
do replay é `null`; use `read --history`). Mesmo `request_id` com conteúdo diferente →
`VALIDATION_ERROR`. Pedidos recusados (confirmação, conflito) não são registrados.

## D16 — Catálogo em cache

`.context-vault/cache/catalog.json` (ignorado pelo Git) guarda o parse de cada nota por
(mtime_ns, tamanho). Índices e busca só reprocessam o que mudou; apagar o cache é seguro.

## D17 — Lacunas de conhecimento

Campo `knowledge_gaps` em notas, tarefas e compromissos: `{id, field, question, status
(unknown|deferred|resolved), priority, answer}`. Lacunas não são tarefas. `deferred` indica que o
usuário adiou e o agente não deve repetir a pergunta sem nova necessidade.

## D18 — `read` aceita prefixo

`read` aceita ID completo, prefixo com 8+ caracteres (`AMBIGUOUS_MATCH` se houver mais de um) ou
caminho relativo da nota.
