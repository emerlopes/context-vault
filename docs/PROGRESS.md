# ContextVault — Plano de implementação e progresso

Especificação: [main.md](main.md). Complementos: [assistência_inteligente_anotacoes.md](assistência_inteligente_anotacoes.md)
(captura assistida — impacta Etapas 2, 3 e 6) e [catalogo_de_testes.md](catalogo_de_testes.md) (ainda vazio — usar na Etapa 7).
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

## Etapa 2 — Memória (notas, índice, busca, propostas) ⬜

- [ ] Repositório de notas: criar / ler / atualizar seção (merge, append, replace) / renomear / mover / arquivar
- [ ] Revisão por conteúdo (`sha256:`) e `expected_revision`
- [ ] Locks de escrita (`.context-vault/locks/`) com timeout e remoção de lock órfão
- [ ] Transação com write-ahead em `.context-vault/journal/pending/` + recuperação de operação interrompida
- [ ] Diário de eventos `.context-vault/journal/YYYY/MM/YYYY-MM-DD.md`
- [ ] Origem (`source`) registrada nas alterações (`user`, `meeting`, `document`, `agent_inference`, `import`)
- [ ] Indexador: `INDEX.md` + `.context-vault/index.json` derivados dos metadados
- [ ] `index rebuild` com detecção de IDs duplicados, links quebrados, metadados inválidos
- [ ] Busca híbrida (título, alias, ID, entidade, tag, conteúdo, relações) com score e trechos
- [ ] `search`, `read <id>`
- [ ] `propose` (valida e retorna plano/diff + requisitos de confirmação) e `apply` (persiste + commit)
- [ ] Idempotência por `request_id`
- [ ] Detecção de duplicação (mesmo conteúdo já presente na seção)
- [ ] Inbox: `inbox add`, `inbox list`, `inbox classify <id>`
- [ ] Testes: persistência, índice, busca, idempotência, concorrência, recuperação

## Etapa 3 — Módulos de conhecimento ⬜

- [ ] Templates de seções por tipo (domínio, projeto, arquitetura, ADR, pessoa, time)
- [ ] Numeração automática de ADR e `supersedes` / `superseded_by`
- [ ] Contradições: seção "Histórico" com estado anterior preservado, marcação de fato substituído
- [ ] Fatos x hipóteses (`agent_inference` marcado)
- [ ] Projetos: status permitidos, marcos/entregas com data, bloqueios
- [ ] Pessoas/times: desambiguação de homônimos (`AMBIGUOUS_MATCH`), filtros de privacidade
- [ ] Atualização de referências ao renomear
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
