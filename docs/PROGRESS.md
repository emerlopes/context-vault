# ContextVault — Plano de implementação e progresso

Especificação: [main.md](main.md). Complementos: [assistência_inteligente_anotacoes.md](assistência_inteligente_anotacoes.md)
(captura assistida — impacta Etapas 2, 3 e 6) e [catalogo_de_testes.md](catalogo_de_testes.md)
(cenários CV-xxx, grupos A–M — cada etapa deve cobrir os cenários do seu módulo; validação completa na Etapa 7).
Decisões técnicas: [DECISIONS.md](DECISIONS.md).

Cada etapa foi dimensionada para caber em uma sessão de trabalho. Ao final de cada sessão,
atualize os checkboxes e o **Registro de sessões** no fim deste arquivo.

Como retomar em uma nova sessão:

> Leia `docs/PROGRESS.md` e `docs/DECISIONS.md` e continue a próxima etapa pendente.

Comandos úteis:

```bash
uv sync                      # instala dependências no .venv
uv run pytest                # roda os testes
uv run context-vault --help  # CLI
```

---

## Etapa 1 — Fundação ✅

- [x] `pyproject.toml`, pacote `src/context_vault`, entry point `context-vault`
- [x] Erros padronizados (`NOT_FOUND`, `AMBIGUOUS_MATCH`, ...) com exit codes
- [x] Envelope de saída JSON / texto
- [x] Geração de IDs UUIDv7
- [x] Relógio com fuso configurável (`America/Sao_Paulo`)
- [x] Configuração (`config.yaml`) com validação e expansão de `~`
- [x] Resolução do repositório de memória (`--repo` > `CONTEXT_VAULT_REPO` > config do usuário > padrão)
- [x] Segurança de caminhos (path traversal, symlink escape)
- [x] Modelos Pydantic: domínio, projeto, arquitetura, ADR, pessoa, time, reunião, compromisso, tarefa, inbox, proposta, relações
- [x] Frontmatter Markdown (parse/dump determinístico)
- [x] Wrapper Git (init, commit local, sem push, sem operações destrutivas)
- [x] Comandos `init`, `status`, `validate`
- [x] Testes unitários da fundação

## Etapa 2 — Memória (notas, índice, busca, propostas) ✅

- [x] Repositório de notas: criar / ler / atualizar seção (merge, append, replace) / renomear / mover / arquivar / relacionar / metadados
- [x] Revisão por conteúdo (`sha256:`) e `expected_revision` → `REVISION_CONFLICT`
- [x] Lock de escrita (`.context-vault/locks/write.lock`) com timeout e remoção de lock órfão
- [x] Transação com write-ahead em `.context-vault/journal/pending/` + rollback / roll-forward (`recover`, automático na próxima escrita)
- [x] Diário de eventos `.context-vault/journal/AAAA/MM/AAAA-MM-DD.md` (`journal list`)
- [x] Origem registrada em cada bloco (`<!-- cv:event=... source=... -->`) e no diário; `agent_inference` marcado como não confirmado
- [x] Indexador: `INDEX.md` + `.context-vault/index.json` derivados dos metadados, atualizados em toda escrita
- [x] `index rebuild` / `index check` com detecção de IDs duplicados, links quebrados, metadados inválidos, local errado
- [x] Catálogo incremental em cache (`.context-vault/cache/catalog.json`) — 2.000 notas: rebuild 1,4 s, busca 0,45 s
- [x] Busca híbrida (ID, título, alias, entidade, tag, descrição, seção, conteúdo, relações, pendências, agenda, inbox, diário) com score explicável e trechos; histórico pesa menos
- [x] `search`, `read <id|prefixo|caminho>` (relações, backlinks, pendências, compromissos, `--history`)
- [x] `propose` (plano + diff + confirmações exigidas, sem gravar) e `apply` (persiste + índice + diário + commit)
- [x] Confirmações do modo equilibrado: `new_topic`, `possible_duplicate`, `conflicting_update`, `archive`, `medium/low_confidence`, `conservative_mode` → `CONFIRMATION_REQUIRED`
- [x] Idempotência por `request_id` (`.context-vault/requests.jsonl`); reuso com conteúdo diferente é recusado
- [x] Detecção de duplicação (conteúdo equivalente na seção → `memory.confirm`, sem repetir texto)
- [x] Inbox: `inbox add`, `inbox list`, `inbox classify <id> [--target|--proposal]`, `inbox discard`
- [x] Lacunas de conhecimento (`knowledge_gaps`, doc de assistência §8): `add_gaps` / `resolve_gaps` (resolved/deferred), `gaps list`
- [x] Testes: persistência, índice, busca, idempotência, concorrência, recuperação, inbox, lacunas (97 testes)

## Etapa 3 — Módulos de conhecimento ✅

- [x] Templates de seções por tipo (feito na Etapa 2 — `services/templates.py`)
- [x] `supersedes` / `superseded_by` entre ADRs: novo ADR com `supersedes` marca o anterior como `superseded`
      (justificativa preservada, relação `supersedes`, confirmação `supersede_decision`); `superseded_by` é gerenciado pelo Core
- [x] Contradições: detecção heurística de polaridade oposta (`possible_contradiction`, com `temporal`) e
      `change.replaces` para substituir uma afirmação específica preservando-a em `## Histórico`
- [x] Fatos x hipóteses: `change.certainty: hypothesis` → `_(Hipótese — não confirmada)_`; `read` lista `unconfirmed`
- [x] Projetos: status permitidos (enum), `milestones` (marco/entrega com data e histórico de mudanças),
      `blockers` (abrir/resolver), avisos de status x bloqueios; `projects list|milestones|blockers`
- [x] Pessoas/times: `resolve <termo>` (homônimos/siglas → `AMBIGUOUS_MATCH`), `memberships` (início/fim em
      projetos e times, espelhado na nota do projeto/time; `read` mostra membros atuais e anteriores)
- [x] Privacidade: credenciais recusadas (`PERMISSION_DENIED`, também na inbox); saúde, família e avaliações
      pessoais exigem confirmação (`sensitive_content`)
- [x] Renomear/mover atualiza links Markdown e `entities` de notas vinculadas
- [x] Exclusão controlada (`memory.delete`): exige `allow_destructive_operations` + confirmação `destructive`
      (inclusive no modo autônomo); remove referências por ID em outras notas
- [x] Lacunas: `suggested_gaps` no plano/resultado (ADR sem justificativa, projeto sem objetivo/responsável,
      projeto bloqueado sem motivo...), nunca repetindo campos já registrados ou adiados
- [x] Testes: classificação (conhecido/desconhecido, sigla ambígua, homônimos, duplicado, contraditório),
      CV-006, CV-010–CV-014, CV-031–CV-035, CV-037–CV-040, privacidade, renomeação, exclusão (144 testes)

## Etapa 4 — Módulos operacionais ✅

- [x] Agenda: `agenda/AAAA/MM.yaml`, `agenda add|list|update|cancel|complete|read` (`--dry-run` no add);
      `list --date/--from/--to/--at/--next/--query/--related` (datas relativas e períodos aceitos)
- [x] Detecção de conflitos: `conflicts` + aviso, não bloqueia (bloqueia só com `agenda.confirm_conflicts: true`
      ou modo conservador → `schedule_conflict`)
- [x] Datas relativas (`hoje`, `amanhã`, `quinta`, `sexta`, `próxima semana`, `dd/mm`, `daqui a N dias`, horários e
      intervalos) — `dates resolve`; ambiguidades (`próxima quinta`, dia da semana = hoje) → `ambiguous_date`
- [x] Sem horário → `missing_time` (pergunta); só cria sem horário com `all_day: true`. Duração nunca inventada
- [x] Reuniões: `meetings create|list|read|update|note|summarize|start|end|active` (notas `meeting` via propostas;
      a partir de compromisso com `appointment_id`; pendências extraídas na mesma transação)
- [x] Preservação da ata: correções só com `replaces` + `reason` (original em `## Histórico`); troca de data move o
      arquivo e registra no histórico
- [x] Reunião ativa = status `in_progress` (`meetings start`); anotação sem reunião explícita → ativa, ou
      `NOT_FOUND`/`AMBIGUOUS_MATCH` (nunca escolhe a mais recente — CV-043)
- [x] Pendências: `tasks add|list|update|complete|read`; filtros responsável, projeto/relacionado (inclui via reunião),
      status, `--overdue`, `--due 'esta semana'`, `--meeting <id|last>`; duplicata exata reconhecida, parecida →
      `possible_duplicate`, nova execução de concluída → `repeats_completed_task`, reabrir → `reopen_completed_task`
- [x] Pendente da Etapa 3 resolvido: `memory.delete` remove referências em tarefas/compromissos (mesma transação);
      projeto encerrado avisa sobre pendências abertas sem concluí-las (CV-027)
- [x] Testes: datas, agenda (CV-046–CV-051), pendências (CV-016–CV-027), reuniões (CV-041–CV-045, cenário C),
      reunião ativa, correção de ata, exclusão com referências (213 testes)

> **Ponto de partida (handoff da Etapa 4):**
> - Serviços: `services/agenda.py`, `services/tasks.py`, `services/meetings.py`, `services/dates.py`;
>   escrita YAML compartilhada em `services/records.py` (`render_tasks`, `render_agenda`, `replay`,
>   `link_participants`, `resolve_person`). CLI em `cli/operations.py`.
> - Briefings (Etapa 5) podem reutilizar `meetings.summarize()` (seções da ata + tarefas da reunião),
>   `agenda.list_appointments(day=...)` (itens com `related`, `meeting`, `conflicts`) e
>   `tasks.list_tasks(related=..., overdue=True)`.
> - `meetings brief` deve separar o registrado das sugestões da IA (spec §11.4) e nunca inferir decisões da pauta.
> - Relações tipadas de tarefas/compromissos ainda são só `related_ids` (sem tipo) — avaliar na Etapa 5.

## Etapa 5 — Relacionamentos e recuperação contextual ⬜

- [ ] Relações tipadas validadas (`related_to`, `depends_on`, `owned_by`, ...) com consulta bidirecional
- [ ] `related <id>` (navegação no grafo, profundidade configurável)
- [ ] `context <termo>` — síntese "tudo que sabemos" agrupada por categoria
- [ ] `meetings brief <id>` — dados para briefing de reunião
- [ ] `daily brief [--date]` — dados para briefing diário
- [ ] Testes de recuperação por relacionamento, briefings

## Etapa 6 — Skill e adaptadores ⬜

- [ ] `skills/context-vault/SKILL.md` (contrato comportamental)
- [ ] `references/` — classification, retrieval, agenda, meetings, tasks, conventions
- [ ] `AGENTS.md` (entrada para agentes compatíveis)
- [ ] Adaptador Claude Code (skill / plugin)
- [ ] Adaptador OpenAI Codex (AGENTS.md / skills)
- [ ] Adaptador Gemini CLI (GEMINI.md / extensão)
- [ ] Comando `context-vault install-skill --agent <nome>`
- [ ] Testes de instalação/descoberta dos adaptadores
- [ ] Permitir instalação local, para que seja possivel compartilhar via zip a skill para as pessoas elas fazerem a instalção local das skill sem passar por marketplace

## Etapa 7 — Testes de cenário e robustez ⬜

- [ ] Cenários A–G da especificação (end-to-end via CLI)
- [ ] Catálogo de testes (grupos A–M, regras R01–R12) — nível Core automatizado; nível agente documentado no modelo §18
- [ ] Testes de segurança (prompt injection tratado como dado, symlinks, schema inválido)
- [ ] Multiagente: mesmo repositório, operações concorrentes
- [ ] Portabilidade (caminhos Windows, fins de linha)
- [ ] Relatório de execução dos testes

## Etapa 8 — Documentação e entrega ⬜

- [ ] README (instalação, configuração, uso)
- [ ] Referência da CLI
- [ ] Exemplos de interação
- [ ] Guia de solução de problemas
- [ ] Arquitetura
- [ ] Limitações reais
- [ ] Validação de instalação limpa

---

## Registro de sessões

| Data | Etapa | Resumo |
|------|-------|--------|
| 2026-10-20 | 1 | Fundação: projeto Python, config, modelos, segurança de caminhos, Git, `init`/`status`/`validate`, testes. |
| 2026-10-20 | 2 | Memória: editor de seções, transações com WAL/lock, diário, índices, catálogo em cache, busca híbrida, `read`, `propose`/`apply`, idempotência, inbox, lacunas. 97 testes. |
| 2026-10-20 | 3 | Conhecimento: ADRs substituídos, contradições + `replaces`, hipóteses, marcos/entregas/bloqueios, vínculos pessoa↔projeto/time, `resolve`, filtros de privacidade, referências ao renomear/mover, `memory.delete`, lacunas sugeridas, `projects …`. 144 testes. |
| 2026-10-20 | 4 | Operacional: datas relativas (`dates resolve`), agenda com conflitos/reagendamento/cancelamento, pendências com duplicatas/histórico/filtros, reuniões (criação, reunião ativa, anotações com pendências, correções rastreáveis, resumo), exclusão limpando referências, aviso de projeto encerrado. 213 testes. |
