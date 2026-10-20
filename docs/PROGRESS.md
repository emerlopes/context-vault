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

## Etapa 3 — Módulos de conhecimento ⬜

- [x] Templates de seções por tipo (feito na Etapa 2 — `services/templates.py`)
- [ ] `supersedes` / `superseded_by` entre ADRs (numeração automática já feita na Etapa 2)
- [ ] Contradições: detecção de afirmação conflitante no Core (preservação do estado anterior via `memory.correct` já feita na Etapa 2)
- [ ] Fatos x hipóteses (`agent_inference` marcado)
- [ ] Projetos: status permitidos, marcos/entregas com data, bloqueios
- [ ] Pessoas/times: desambiguação de homônimos (`AMBIGUOUS_MATCH`), filtros de privacidade
- [ ] Atualização de referências ao renomear (IDs já estáveis; falta atualizar `entities`/menções em outras notas)
- [ ] Exclusão controlada (`memory.delete`, exige `allow_destructive_operations` + confirmação)
- [ ] Lacunas: criar a partir dos fluxos do agente (Exemplos B–H do doc de assistência)
- [ ] Testes de classificação (assunto conhecido/desconhecido, sigla ambígua, múltiplos candidatos, duplicado, contraditório)

## Etapa 4 — Módulos operacionais ⬜

- [ ] Agenda: `agenda/AAAA/MM.yaml`, `add`, `list --date/--from/--to`, `update`, `cancel`, `complete`
- [ ] Detecção de conflitos (alerta, não bloqueia)
- [ ] Resolução de datas relativas (`hoje`, `amanhã`, `quinta`, `sexta`, `próxima semana`) — comando `dates resolve`
- [ ] Reuniões: `meetings create/list/read/update/note/summarize`, arquivo por reunião em `reunioes/AAAA/MM/`
- [ ] Preservação da ata (correções rastreáveis, sem reescrita silenciosa)
- [ ] Reunião ativa (associação de anotações)
- [ ] Pendências: `tasks add/list/update/complete`, filtros (responsável, projeto, status, atraso, vencimento na semana)
- [ ] Testes de agenda, reuniões e pendências

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
