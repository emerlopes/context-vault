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

## Etapa 5 — Relacionamentos e recuperação contextual ✅

- [x] Relações tipadas validadas por tipo de origem/alvo (`related_to`, `depends_on`, `owned_by`, `participates_in`,
      `discussed_in`, `decided_in`, `blocks`, `supersedes`, `part_of`) em create/relate/upsert e no `validate`
      (`INVALID_RELATION`); `remove_relations` rastreável no histórico
- [x] Grafo derivado de notas, tarefas e compromissos (`services/graph.py`), consulta bidirecional com nomes inversos,
      participações vigentes x encerradas, referências quebradas
- [x] `related <id>` (profundidade 1–5, `--type`, `--kind`, `--direction`, `--current`)
- [x] `context <termo>` — síntese "tudo que sabemos" agrupada por categoria, fontes, categorias vazias, hipóteses
      à parte, responsáveis com detecção de divergência, menções sem relação; `found: false` quando não há registro
- [x] `meetings brief [ref] [--date]` — registrado x sugestões; seleção por ID, compromisso, assunto, ativa ou próxima
- [x] `daily brief [--date]` — compromissos em ordem, objetivo, contexto, pendências relacionadas, conflitos,
      tarefas do dia/atrasadas, marcos, cancelados à parte, pontos de preparação
- [x] Testes: CV-048, CV-052, CV-053–CV-058 (nível Core), navegação no grafo, validação de relações (229 testes)

> **Ponto de partida (handoff da Etapa 5):**
> - Serviços novos: `services/graph.py` (`Graph.build`, `related`, `check_relations`, `RELATION_RULES`),
>   `services/context.py` (`context`, `note_digest`, `section_items`, `note_facts`), `services/briefings.py`
>   (`meeting_brief`, `daily_brief`). CLI em `cli/retrieval.py` (+ `meetings brief` em `cli/operations.py`).
> - A skill (Etapa 6) deve orientar: "me prepara para a reunião" → `meetings brief`; "o que tenho hoje" →
>   `daily brief`; "tudo sobre X" → `context X`; apresentar `suggestions` separadas de `recorded` e citar `sources`.
> - CV-036 ("o que mudou no Orion nesta semana") ainda depende de `journal list` + `read --history`; avaliar um
>   filtro por período em `context` na Etapa 7 se os cenários exigirem.

## Etapa 6 — Skill e adaptadores ✅

- [x] `skills/context-vault/SKILL.md` (contrato comportamental: pré-voo da CLI, regras invioláveis, roteamento de
      intenções, captura assistida com perguntas A/B/C e uma por vez, confirmações, erros, política de respostas)
- [x] `references/` — classification, retrieval, agenda, meetings, tasks, conventions (formatos JSON reais da CLI)
- [x] `AGENTS.md` na raiz (aponta para a skill, sem duplicá-la) e `AGENTS.md` da memória atualizado
- [x] Adaptador Claude Code: `~/.claude/skills` ou `.claude/skills` + plugin/marketplace em `.claude-plugin/`
      (validados com `claude plugin validate`)
- [x] Adaptador OpenAI Codex: `~/.agents/skills` / `.agents/skills` (+ `AGENTS.md`)
- [x] Adaptador Gemini CLI: `~/.agents/skills` (alias oficial de `~/.gemini/skills`) + extensão
      `gemini-extension.json` / `GEMINI.md`
- [x] Devin (Cognition): `~/.agents/skills` (Devin CLI) e `.agents/skills` commitado no repositório (Devin na nuvem)
- [x] `context-vault install-skill --agent <claude-code|codex|gemini|devin|agents|all>` (`--scope user|project`,
      `--project-dir`, `--target`, `--source pasta|zip`, `--force`, `--link`, `--dry-run`), `skill status|uninstall|agents|package`
- [x] Instalação local por zip: `package-skill` (skill + `INSTALL.md` + `install.sh`/`install.ps1`, opcional `--wheel`;
      `--skill-only` para upload no Claude) e `install-skill --source <zip>`; skill embutida no wheel
- [x] Testes de instalação/descoberta: contrato Agent Skills, links/âncoras, comandos e opções citados existem na CLI,
      manifests, instalação por agente/escopo, alterações locais preservadas, desinstalação, zip seguro, `install.sh`
      com e sem CLI (270 testes)

> **Ponto de partida (handoff da Etapa 6):**
> - Código: `src/context_vault/adapters/` (`agents.py` = pastas de descoberta por agente, `installer.py`,
>   `assets/` = arquivos do zip); CLI em `cli/skills.py`. Skill canônica em `skills/context-vault/`.
> - **Não validado com agentes reais:** Codex, Gemini CLI e Devin não estão instalados nesta máquina e o
>   `claude -p` não autenticou (OAuth expirado). Os caminhos seguem a documentação oficial de cada um
>   (links em `context-vault skill agents`). Validar na Etapa 7/8 com os agentes instalados.
> - Testes de nível agente (catálogo §18) devem usar a skill como contrato: cada regra R01–R12 está no `SKILL.md`.
> - `test_documented_commands_exist` falha se a skill citar comando/opção que não existe: mantenha a skill
>   sincronizada ao mudar a CLI.

## Etapa 7 — Testes de cenário e robustez ✅

- [x] Cenários A–G da especificação end-to-end via CLI (`tests/scenarios/test_spec_flows.py`)
- [x] Catálogo (grupos A–M, regras R01–R12) no nível Core: os 84 cenários têm teste; o nível agente está
      documentado no modelo §18 (`tests/scenarios/agent_level.yaml`) com status BLOQUEADO (sem agente executável)
- [x] Segurança: conteúdo de nota não vira estrutura nem proveniência (`neutralize`, CV-062), caminhos externos e
      symlinks recusados com `PERMISSION_DENIED` (também em `read`), schemas inválidos, falha de E/S com envelope
      JSON e `saved: false` (CV-063), índice apontando para arquivo apagado detalhado (CV-064)
- [x] Multiagente: processos separados no mesmo repositório (`--repo`, `CONTEXT_VAULT_REPO`, config do usuário),
      14 operações concorrentes sem perda nem duplicação, mesmo `request_id` em dois agentes, skill para todos os agentes
- [x] Portabilidade: CRLF e BOM em arquivos editados à mão, `.gitattributes` com LF, caminhos `\`, nomes reservados
      do Windows, `NON_PORTABLE_PATH`/`CASE_COLLISION` no `validate`, fuso explícito
- [x] Relatório: `uv run pytest --cv-report docs/RELATORIO_TESTES.md` ([RELATORIO_TESTES.md](RELATORIO_TESTES.md))
- [x] Correções no Core encontradas pelos cenários: `context --since` / `journal list --period` (CV-036), histórico
      com estado anterior no `context` (CV-007), mesma tarefa para outra pessoa/contexto (CV-074/CV-075), datas vagas
      (CV-073), `identity_status` provisório (CV-008) — decisões D40–D48 (340 testes; 1 ignorado no macOS: colisão de maiúsculas exige sistema de arquivos sensível a caixa)

> **Ponto de partida (handoff da Etapa 7):**
> - Testes de cenário em `tests/scenarios/` (helpers em `_helpers.py`); cada teste cita no código os IDs
>   que cobre — o plugin `tests/cv_report.py` usa isso para montar o relatório. Ao criar testes novos para um
>   cenário do catálogo, cite o `CV-0xx` na linha do `def` ou no corpo.
> - **Nível agente ainda não executado:** `claude -p` sem OAuth válido; Codex, Gemini CLI e Devin não instalados.
>   Para rodar: catálogo §20 com cada agente, registrar no modelo §18 e atualizar `agent_level.yaml` (status/motivo).
> - A Etapa 8 deve documentar: `context --since`, `journal list --period`, `identity_status`, códigos novos do
>   `validate` (`INDEX_MISSING_FILE`, `NON_PORTABLE_PATH`, `CASE_COLLISION`), `details.saved` nos erros e
>   `CONTEXT_VAULT_DEBUG`. Limitações reais: um responsável por tarefa; equivalência semântica é decisão do agente;
>   detecção de contradição/sensibilidade é léxica.
> - A suíte completa leva ~1min40s (setup dos testes de recuperação + processos reais nos testes multiagente).

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
| 2026-10-20 | 5 | Relacionamentos: validação de relações tipadas, `remove_relations`, grafo bidirecional (`related`), síntese por assunto (`context`), `meetings brief` e `daily brief` com registrado x sugestões. 229 testes. |
| 2026-10-20 | 6 | Skill: `SKILL.md` + 6 referências, `AGENTS.md`/`GEMINI.md`, plugin Claude Code, extensão Gemini, `install-skill` para Claude Code/Codex/Gemini/Devin (pasta compartilhada `.agents/skills`), status/desinstalação seguras, pacote zip com instaladores, skill no wheel, `python -m context_vault`. 270 testes. |
| 2026-10-20 | 7 | Cenários: fluxos A–G, 84 cenários do catálogo no nível Core, segurança (injeção em notas, caminhos, symlinks, falha de E/S), multiagente com processos concorrentes, portabilidade (CRLF/BOM, nomes Windows), relatório `--cv-report`. Correções: `context --since`, `journal --period`, histórico detalhado, duplicatas por responsável/contexto, datas vagas, pessoa provisória, índice detalhado, envelope JSON em erros de E/S. 340 testes. |
