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

## D19 — Planos com várias notas

Uma proposta pode alterar notas secundárias (ADR substituído, projeto/time de uma pessoa, notas com
links para a renomeada, notas que referenciam a excluída). Todas entram na mesma transação e no mesmo
commit; a revisão de cada arquivo secundário é verificada no `apply` (`REVISION_CONFLICT` se mudou).
O plano lista essas alterações em `related_changes`.

## D20 — Contradições são sinalizadas, não interpretadas

O Core compara cada frase nova com o estado atual da nota (fora de `## Histórico`, ignorando hipóteses
e inferências). Polaridade oposta (`não`, `nunca`, `deixou de`...) + ao menos 2 termos em comum (≥ 50%)
→ `contradictions` no plano e confirmação `possible_contradiction`. `temporal: true` quando há marcadores
como "mais", "agora", "passou a". A forma recomendada de registrar a mudança é `change.replaces` (a linha
antiga sai do estado atual e vai para `## Histórico` com motivo e origem). `mode: replace`/`memory.correct`
continuam substituindo a seção inteira.

## D21 — Hipóteses

`change.certainty: hypothesis` grava o texto com `_(Hipótese — não confirmada)_` (inferências do agente
continuam com `_(Inferência — não confirmada)_`). A deduplicação compara o texto sem o marcador. Para
confirmar uma hipótese, use `replaces` com o texto da hipótese.

## D22 — Dados estruturados no frontmatter + linha legível no corpo

- Projeto: `milestones` (`kind: milestone|delivery`, `due_date`, `status planned|done|missed|cancelled`,
  `history` de mudanças) e `blockers` (`open|resolved`, `since`, `resolved_on`, `resolution`).
- Pessoa: `memberships` (`kind: project|team`, `target_id`, `role`, `start_date`, `end_date`; sem
  `end_date` = vigente). Times são espelhados em `team_ids` (pessoa) e `member_ids` (time).
- Esses campos são gerenciados pelo Core (não podem ir em `meta`/`extra`); a proposta usa
  `milestones`, `blockers` e `memberships`.
- As seções Marcos/Entregas/Bloqueios/Projetos/Times/Pessoas envolvidas mostram uma linha por item
  vigente; ao mudar/encerrar, a linha anterior vai para o histórico. O Core não altera o status do
  projeto sozinho: apenas avisa (`warnings`) sobre status x bloqueios.

## D23 — Resolução de nomes (`resolve`)

Camadas: título/alias exato → primeiro nome de pessoa → entidade de domínio/arquitetura → entidade de
outras notas. Notas ativas vencem arquivadas/substituídas na mesma camada. Mais de um candidato na camada
decisiva → `AMBIGUOUS_MATCH` (exit 4) com `candidates`; nenhum → `NOT_FOUND` com `possible` e sugestão de
inbox.

## D24 — Privacidade

Credenciais (senha/token/chave com valor, chaves privadas, tokens conhecidos, connection strings com
senha) → `PERMISSION_DENIED` em propostas e na inbox; os valores nunca são ecoados. Saúde, assuntos
familiares e avaliações pessoais sensíveis → confirmação `sensitive_content` (`sensitive` no plano). Os
padrões são léxicos e conservadores para evitar falsos positivos em notas técnicas.

## D25 — Renomear e mover

Links Markdown relativos para o caminho antigo são reescritos. Em notas que referenciam a renomeada por
ID, `entities` igual ao título antigo vira o novo título (exceto se outro registro também usar esse nome).
Texto livre e histórico não são reescritos; o título antigo vira alias.

## D26 — Exclusão

`memory.delete` exige `security.allow_destructive_operations: true` (senão `PERMISSION_DENIED`) e sempre
confirmação `destructive`. Remove o arquivo e as referências por ID nas outras notas, pendências e
compromissos (desde a Etapa 4 — ver D32). O resultado avisa que o histórico Git mantém versões anteriores (spec §23.4).

## D27 — Lacunas sugeridas

`propose`/`apply` devolvem `suggested_gaps` (prioridade alta primeiro) com base no tipo: ADR sem
justificativa/contexto, projeto sem objetivo/responsável ou bloqueado sem bloqueio aberto, pessoa sem
função, domínio/arquitetura sem visão geral. O Core nunca as grava sozinho: o agente pergunta (uma por
vez) ou as registra via `add_gaps` (ex.: `status: deferred` quando o usuário não quer responder). Campos
com lacuna já registrada — inclusive adiada ou resolvida — não são sugeridos novamente.

## D28 — Datas relativas

`services/dates.py` resolve expressões em português contra `vault.now()` no fuso configurado (semana começa
na segunda). Dia da semana simples = próxima ocorrência após hoje (`sexta` numa terça = esta sexta). São
ambíguos (`ambiguous: true` + `alternatives`) e exigem confirmação `ambiguous_date` nas escritas: o dia da
semana igual a hoje, `próxima <dia>` quando o dia ainda está à frente nesta semana, e `dd/mm` sem ano já passado.
`esta/nesta semana` e `próxima semana` são períodos (segunda a domingo). Os campos de data das entradas
(`due_date`, `when`, `starts_at`, `date`) aceitam ISO ou expressão; a resolução volta em `resolved_dates`.

## D29 — Compromissos

- Arquivo pelo mês de `starts_at` no fuso configurado; reagendar para outro mês move o registro.
- Sem horário: `CONFIRMATION_REQUIRED` `missing_time`; `confirmed` não basta — só `all_day: true` cria sem horário
  (00:00 local, `ends_at` vazio). Duração nunca é inventada; ao reagendar, uma duração já conhecida é mantida (aviso).
- Conflito = sobreposição com outro compromisso `scheduled` (sem término = instante; mesmo início conflita;
  encostados não conflitam; dia inteiro não conflita). Padrão: `conflicts` + `warnings`, sem bloquear.
  `agenda.confirm_conflicts: true` (novo campo) ou modo conservador → confirmação `schedule_conflict`.
- Mesmo título e mesmo início → nada é criado (`duplicate: true`); mesmo título no mesmo dia → `possible_duplicate`.
- Cancelar/concluir mantém o registro e `history` (valores anteriores em `previous`); a nota de reunião vinculada
  nunca é alterada. Reagendar um cancelado exige `status: scheduled` explícito.
- `agenda list` sem filtros mostra de hoje em diante, sem cancelados (`--all` inclui).

## D30 — Pendências

- Um arquivo (`pendencias/tarefas.yaml`); campos canônicos da spec sempre visíveis (inclusive `null`).
- Novos campos opcionais: `notes` (contexto acrescentado depois, com origem) e `source` (origem da captura),
  também `source` em compromissos.
- Mesma tarefa aberta (título normalizado igual e mesmo responsável) → reconhecida, nada criado (`tasks.confirm`
  no diário). Parecida (Jaccard ≥ 0,5 com ao menos 2 palavras em comum) → `possible_duplicate` com candidatos: a
  equivalência semântica ("repo" x "repositório") é decisão do agente com o usuário.
- Título igual a uma tarefa concluída → `repeats_completed_task`, dispensado quando a nova tarefa cita a antiga em
  `related_ids` (nova execução, CV-023). Reabrir uma concluída → `reopen_completed_task`.
- Responsável: `assignee_id` ou `assignee_name`; um nome que identifica exatamente uma pessoa é vinculado, homônimos
  → `AMBIGUOUS_MATCH`, nome desconhecido fica só como nome (aviso). Nunca atribui ao usuário por padrão.
- Concluir registra `completed_at` (momento da comunicação); concluir de novo não gera segunda conclusão.
- `related_ids` aceita notas e outras tarefas. Filtro por projeto inclui tarefas de reuniões relacionadas ao projeto
  (`via_meeting`).

## D31 — Reuniões

- Criadas por propostas `memory.create` (provenance, diário, índice, commit). Reunião não é "tópico novo": não
  exige `new_topic`; duplicata = mesmo título na mesma data.
- Status padrão: `scheduled` se data/horário ainda estão à frente, senão `completed`. Horário não é inventado.
- Participantes identificados viram `participant_ids` e o nome canônico; homônimos ficam só como nome (aviso).
- `meetings note`: entradas por tipo (`discussion` → Discussões, `decision` → Decisões, `question` → Dúvidas em
  aberto, `next_step`, `risk`, `context`, `agenda`, `objective`); `tasks` viram pendências com
  `source_meeting_id` e os assuntos da reunião em `related_ids`, mais uma linha em Pendências — tudo num commit.
- Reunião ativa = `in_progress` (sem estado oculto). Termo ("Atlas") casa título/aliases/entidades e notas
  relacionadas; mais de uma → `AMBIGUOUS_MATCH`; `date` desambigua.
- Correções da ata: `replaces` + `reason` obrigatório (também em `memory.correct`/`mode: replace` sobre reuniões).
- `summarize` só devolve o que está registrado (`notice` quando não há decisões/ata); para um compromisso sem nota,
  devolve o compromisso e "não há ata".

## D32 — Exclusão e encerramento com registros operacionais

`memory.delete` remove o ID excluído de `related_ids`, `blocked_by`, `assignee_id`, `source_meeting_id`
(tarefas) e `related_ids`, `participant_ids`, `meeting_id` (compromissos) na mesma transação, com entrada no
`history`; os nomes são mantidos. Projeto que passa a `completed`/`cancelled`/`archived` com tarefas abertas
gera aviso — as tarefas nunca são concluídas automaticamente.


## D33 — Relações tipadas validadas

`services/graph.py` define, para cada tipo da spec §16.2, quais tipos de nota podem ser origem e alvo
(ex.: `owned_by` só de domínio/projeto/arquitetura/ADR para pessoa/time; `decided_in`/`discussed_in` só para
reunião; `supersedes` entre notas do mesmo tipo; `part_of` pessoa → time, arquitetura → domínio/projeto...).
`memory.create`/`memory.relate`/`memory.upsert` recusam combinações inválidas com `VALIDATION_ERROR`
(`allowed_targets`, `allowed_sources`); `validate` acusa `INVALID_RELATION` (aviso) em notas editadas à mão.
`related_to` vale entre quaisquer notas. `remove_relations` (em `memory.relate`) remove uma relação por
tipo + alvo e registra a remoção em `## Histórico` (com `reason`), para que vínculos antigos — como o responsável
anterior — continuem rastreáveis (CV-053/CV-054).

## D34 — Grafo derivado, consultado nos dois sentidos

Tarefas e compromissos continuam com `related_ids` sem tipo (decisão da Etapa 4 mantida): o grafo deriva arestas
tipadas de todos os campos com IDs — `relations`/`related_ids`, participações (`memberships`, com `current`),
`team_ids`/`member_ids`, `supersedes`/`superseded_by`, participantes, bloqueios abertos (`blocks`), `owner` do
projeto (quando o nome identifica exatamente uma pessoa), responsável da tarefa (`owned_by`), reunião de origem
(`discussed_in`), `blocked_by` (`blocks`). Uma aresta recebida aparece com o nome inverso (`owned_by` → `owns`,
`part_of` → `has_part`). Participações encerradas continuam no grafo com `current: false` (`--current` as omite).
`related <ref>` faz busca em largura (profundidade 1–5, `--type`, `--kind`, `--direction`); referências para IDs
inexistentes saem em `broken`.

## D35 — `context <termo>`

Resolve o assunto como `read` (ID/prefixo/caminho) ou `resolve` (título/alias/entidade); homônimos →
`AMBIGUOUS_MATCH`; nada → sucesso com `found: false`, `notice` e menções da busca (o agente responde "não encontrei",
nunca inventa). A síntese agrupa os vizinhos do grafo por categoria (domínios, sistemas, integrações — notas de
arquitetura com "integração" no título/tags/aliases —, projetos, decisões vigentes x anteriores x registradas em
reuniões, pessoas atuais x anteriores, times, reuniões passadas x futuras, agenda futura, pendências **abertas**,
bloqueios, marcos, lacunas, histórico). Fatos do estado atual vêm por seção; hipóteses/inferências em `unconfirmed`.
`responsibility.claims` reúne `owner`, `owned_by` e `responsibilities` de pessoas/times que citam o assunto; mais de
uma pessoa → `divergent: true` (CV-057: apresentar as fontes, não escolher). `empty_categories` lista o que não tem
registro; `sources` lista os arquivos usados.

## D36 — Briefings

`meetings brief [ref] [--date]` aceita reunião, compromisso, assunto (ID ou termo) ou nada. Sem referência usa a
reunião em andamento ou a próxima da agenda (`selected_by: next`, com aviso para confirmar); por termo, mais de uma
reunião futura → `AMBIGUOUS_MATCH`. `daily brief [--date]` é de um único dia (período → `VALIDATION_ERROR`).
Ambos separam `recorded` (com fontes) de `suggestions` (perguntas e pontos de atenção derivados de registros:
pendência atrasada/sem responsável/vencendo, dúvida em aberto de reunião anterior, lacuna `unknown`, bloqueio
aberto, hipótese, objetivo não registrado, conflito de horário), cada sugestão com `basis`. Decisões vêm apenas de
seções `Decisões` e ADRs — nunca da pauta. O objetivo vem da seção `Objetivo` da nota ou da descrição do compromisso.


## D37 — Skill canônica única e pastas de descoberta

`skills/context-vault/` é a única fonte do contrato (spec §24.1); os adaptadores só copiam essa pasta para onde
cada agente a descobre (documentação oficial consultada em 2026-10-20):

| Agente | Usuário | Projeto |
|--------|---------|---------|
| Claude Code | `~/.claude/skills` | `.claude/skills` |
| OpenAI Codex | `~/.agents/skills` | `.agents/skills` (da pasta atual até a raiz do repositório) |
| Gemini CLI | `~/.agents/skills` (alias de `~/.gemini/skills`, com precedência) | `.agents/skills` |
| Devin | `~/.agents/skills` (também `~/.config/devin/skills`) | `.agents/skills` (também `.devin/skills`) |

Codex, Gemini CLI e Devin compartilham `.agents/skills` (padrão Agent Skills), então `--agent all` instala só
duas cópias (Claude Code + `.agents/skills`); uma segunda cópia numa pasta específica faria o agente ver a skill
duas vezes (`skill status` avisa). O frontmatter tem só `name` e `description` (spec §18.1; `name` = pasta,
minúsculas com hífen, descrição ≤ 1024 caracteres). Plugin do Claude Code (`.claude-plugin/`) e extensão do
Gemini (`gemini-extension.json` + `GEMINI.md`) usam a própria raiz do repositório, cuja pasta `skills/` já é o
local esperado por ambos.

## D38 — Instalação segura e reversível

Cada cópia recebe `.context-vault-skill.json` com o sha256 de cada arquivo. Reinstalar igual → `unchanged`;
arquivo editado localmente ou pasta não criada pelo ContextVault → `CONFIRMATION_REQUIRED`
(`overwrite_modified_skill`, `foreign_skill_directory`, `replace_symlink`) até `--force`. Arquivos que saíram da
skill são removidos na atualização. `skill uninstall` apaga só arquivos gerenciados e intactos (arquivos do
usuário ficam em `kept`). `--link` cria link simbólico para a origem (desenvolvimento). A skill é embutida no
wheel (`context_vault/_skill/`), então `install-skill` funciona sem o checkout.

## D39 — Compartilhamento por zip, sem marketplace

`package-skill` gera um zip determinístico: `context-vault/` (a skill), `INSTALL.md`, `install.sh`,
`install.ps1` e, com `--wheel`, a CLI em `wheels/`. Os scripts usam `context-vault install-skill` quando a CLI
está no PATH; sem ela, copiam a pasta (recusam sobrescrever sem `--force`, exit 11) e avisam que a CLI é
necessária. `--skill-only` gera um zip só com `context-vault/` (upload de skill no app do Claude).
`install-skill --source <zip>` rejeita caminhos absolutos, `..` e links simbólicos no zip.


## D40 — Conteúdo é dado, nunca estrutura

Todo texto livre inserido numa seção passa por `neutralize()` (`storage/markdown.py`): linhas de título fora de
blocos de código viram texto (`\## Decisões`), um bloco de código não fechado é fechado (esconderia os títulos
seguintes) e, no conteúdo vindo de propostas, comentários de origem forjados (`<!-- cv:…`) ficam visíveis
(`&lt;!-- cv:`). O mesmo vale para o texto do usuário dentro de entradas do `## Histórico` (motivos, descrições).
Assim uma nota não consegue criar uma seção `Decisões` falsa, esconder seções nem falsificar proveniência (CV-062).

## D41 — Falhas de E/S e erros inesperados mantêm o envelope JSON

`OSError` (repositório somente leitura, sem permissão, disco cheio) → `REPOSITORY_UNAVAILABLE` (exit 8) com
`details.saved: false`; qualquer outra exceção → `INTERNAL_ERROR` (exit 1) com `details.saved: false`. A transação
já desfez o que tinha começado, então nada fica pela metade e o agente nunca recebe um traceback no lugar de JSON
(CV-063). `CONTEXT_VAULT_DEBUG=1` relança a exceção para depuração. `read` com algo que parece caminho (`/`, `\`,
`.md`, `C:`) passa pela checagem de caminho: fora do repositório → `PERMISSION_DENIED` em vez de `NOT_FOUND`.

## D42 — Portabilidade dos arquivos

- `init` cria `.gitattributes` com `* text=auto eol=lf`: a revisão é o sha256 dos bytes, então a mesma nota precisa
  ter os mesmos bytes em todas as máquinas e agentes. Leitura aceita CRLF e BOM UTF-8; escrita sempre em LF sem BOM.
- Nomes gerados são ASCII; títulos que virariam nomes reservados do Windows (`CON`, `NUL`, `COM1`…) ganham
  `-nota` (`con-nota.md`). `memory.move` recusa caminhos não portáveis (`<>:"|?*`, nomes reservados, final com
  ponto/espaço). `validate` avisa `NON_PORTABLE_PATH` e `CASE_COLLISION` (nomes que só diferem por maiúsculas,
  que colidem no macOS e no Windows) em arquivos criados à mão.
- Caminhos relativos no estilo Windows (`dominios\nota.md`) são aceitos em `read` e `memory.move`.

## D43 — "O que mudou no período" vem do diário

`context <termo> --since <período>` acrescenta `changes`: eventos do diário no período cujo alvo é o assunto ou um
vizinho do grafo (ou que alteraram a nota do assunto como arquivo secundário), em ordem, com `categories`
derivadas da operação, do tipo do alvo, das seções alteradas (`details.sections`, gravado no evento desde a
Etapa 7) e das mudanças estruturadas (bloqueios, marcos, participações). Um único dia significa "daquele dia até
hoje". `journal list --period` filtra o diário do mesmo jeito. Só eventos registrados são devolvidos (CV-036).
O `history` do `context` passou a trazer, além do rótulo, o estado anterior e o motivo de cada entrada.

## D44 — Mesma ação para outra pessoa ou em outro contexto

Uma tarefa aberta com o mesmo título só é "a mesma" (reconhecida, nada criado) quando o responsável também é o
mesmo **e** os `related_ids` não são disjuntos. Mesmo título para outro responsável (`different_assignee`,
CV-074) ou em contextos disjuntos (`different_context`, CV-075 — "Validar API" no Atlas e no Orion) → confirmação
`possible_duplicate`, nunca criação silenciosa nem fusão. O modelo continua com um responsável por tarefa;
co-responsáveis vão em `note` após o agente perguntar o responsável principal.

## D45 — Datas vagas não viram dia

Qualificadores como `começo`, `início`, `meados`, `meio`, `final`, `lá pelo`, `talvez` que sobram depois da
interpretação marcam a resolução como `ambiguous: true` com nota "Expressão vaga…". `due_date` já recusava
períodos ("mês que vem"); com isso "começo do mês que vem" nunca é convertido em 01/11 por conta própria (CV-073).

## D46 — Pessoa provisória

`PersonNote.identity_status` (`provisional` | `confirmed`, opcional): cadastro mínimo criado a partir de uma menção
("Pedi para o João…"), só com o nome dito (CV-008). Não afeta `resolve`: a pessoa provisória é reutilizada nas
menções seguintes.

## D47 — Índice inconsistente é detalhado, não descartado

`index check`/`validate` comparam o `index.json` versionado com as notas: `missing_files` (entrada cujo arquivo foi
apagado fora do Core — aviso `INDEX_MISSING_FILE` lembrando que o conteúdo pode estar no histórico Git),
`moved` e `unindexed`. `index rebuild` corrige e devolve `removed_entries`/`added_entries`, para o agente contar ao
usuário o que saiu do índice (CV-064).

## D48 — Testes de cenário e relatório

`tests/scenarios/` reproduz os fluxos A–G da spec e os cenários do catálogo pela CLI, verificando só o estado
persistido. Cada teste cita no próprio código os IDs que cobre (`CV-0xx`, intervalos, `R01`–`R12`, `Cenário X`);
`pytest --cv-report docs/RELATORIO_TESTES.md` (plugin `tests/cv_report.py`) gera o relatório no modelo do catálogo
§18. O nível agente (perguntas e respostas da conversa) fica em `tests/scenarios/agent_level.yaml` com status
próprio — `BLOQUEADO` enquanto não houver agente executável para rodar o catálogo §20.

## D49 — Dashboard: camada de apresentação sobre o Core

O módulo `src/context_vault/dashboard/` ([dashboard.md](dashboard.md), uso em [dashboard-uso.md](dashboard-uso.md))
não tem modelo próprio de tarefas, projetos ou pessoas: um `Snapshot` lê o catálogo (cache), as tarefas, a agenda e
o grafo **uma vez** por geração (`Graph.build` passou a aceitar `tasks`/`appointments` já carregados) e as regras
vêm do Core — `is_overdue` e `matches_person` foram expostos em `services/tasks.py` e são usados também por
`tasks list`. O resultado é um modelo Pydantic versionado (`schema_version: "1.0"`, envelope com `view`,
`generated_at`, `timezone`, `filters`, `metrics`, `data`, `sources`, `warnings`); os templates Jinja2 só imprimem
valores já formatados (datas, rótulos, "Não informado").

## D50 — Templates e assets dentro do pacote; relatórios em `reports/` da memória

A spec desenha `templates/` e `assets/` na raiz, mas o ContextVault separa o código (este repositório) da
memória (outro repositório). Templates e assets ficam em `src/context_vault/dashboard/` para funcionarem a partir
do wheel; os HTMLs vão para `<memória>/reports/` (`dashboard.output_dir`). `reports/.gitignore` (conteúdo `*`) é
criado na primeira geração e memórias novas têm `reports/` no `.gitignore`: o `status` continua limpo e nada
sensível é commitado. Saída fora do repositório só com `dashboard.allow_external_output: true`.

## D51 — HTML autossuficiente e à prova de injeção

CSS e JS são embutidos; a CSP (`default-src 'none'`, `script-src 'sha256-<hash do dashboard.js>'`,
`style-src 'unsafe-inline'`, `img-src data:`) impede rede e qualquer script que não seja o do pacote. Autoescape em
tudo; o manifesto vai em `<script type="application/json">` via `tojson`. Antes de gravar, `security.check_html`
valida a estrutura e recusa recursos externos, `javascript:`, atributos `on*`, `<iframe>/<form>/<base>` e
`<script>` a mais. Segredos (padrões de `services/privacy.py`) são ocultados em todo texto do modelo
(`SECRET_REDACTED`). O sucesso só é devolvido depois da escrita atômica e da releitura; falha de E/S →
`REPOSITORY_UNAVAILABLE` com `details.written: false` (CV-DASH-015).

## D52 — Envelope de resposta e códigos de erro do dashboard

A CLI mantém o envelope de sempre (`status`/`operation`) e acrescenta `success: true`, `output_path`, `uri`,
`generated_at`, `records_read`, `metrics` e `warnings` (spec §13). Ambiguidade usa o código existente
`AMBIGUOUS_MATCH` (exit 4) com `details.candidates` e `details.filter` ("projeto", "pessoa", "assunto") em vez de
um código novo `AMBIGUOUS_PROJECT`: a skill já trata esse código. `--json` é aceito (a saída já é JSON por padrão).

## D53 — Regras de indicadores

- Uma tarefa conta uma vez (IDs duplicados num arquivo editado à mão geram `DUPLICATE_ID` e são ignorados);
  em agrupamentos, uma tarefa ligada a dois projetos aparece nos dois grupos, mas o total geral a conta uma vez.
- Atraso = tarefa aberta (open/in_progress/blocked) com `due_date` anterior ao dia local no fuso configurado.
- Progresso = concluídas / (vinculadas − canceladas), rotulado "N de M tarefas concluídas · X% das tarefas
  concluídas"; sem tarefas → "Sem dados suficientes para calcular". Tarefas vinculadas a um projeto incluem as
  ligadas pela reunião de origem (mesma regra de `tasks list --related`).
- Projeto bloqueado = status `blocked` ou ativo/planejado com bloqueio em aberto.
- Participação atual × anterior vem de `memberships` (`end_date`); um projeto com vínculo vigente nunca aparece
  como anterior.
- Fonte indisponível (arquivo de tarefas ou agenda inválido) → indicadores `null` ("Sem dados") e aviso
  `TASKS_UNAVAILABLE`/`AGENDA_UNAVAILABLE`, nunca zero; nada é corrigido.

## D54 — Painel de atenção determinístico

Regras fixas com pesos em `dashboard.attention` (padrão da spec + `inconsistency: 70`). Um item por registro: se
várias regras atingem o mesmo registro, vale o maior peso e todos os motivos são listados. Empate → mais dias de
atraso, prazo mais próximo, horário mais cedo, título. "Risco crítico" é léxico nas seções `Riscos`; lacunas
"relevantes" são as em aberto de prioridade alta (adiadas nunca aparecem); compromissos entram de hoje até
`attention_days`.

## D55 — Regeneração por manifesto

O manifesto guarda a visão e as opções pedidas, com pessoa/projeto/assunto **resolvidos para o ID** (estável a
renomeações) e períodos **como pedidos** ("esta semana" é reavaliado no `refresh`). Fica embutido no HTML e num
registro derivado em `.context-vault/cache/dashboards/registry.json`, usado por `dashboard list`, `refresh` e
`open` sem `--output` (o mais recente). O registro é cache: apagá-lo não perde nada que o HTML não tenha.

## D56 — Fontes e ícones por CDN fixado, com degradação offline

Decisão do usuário: "rodar local" não exige rodar sem internet. Por padrão (`dashboard.external_assets: true`)
o relatório usa Google Fonts (Fira Sans/Fira Code, design system da skill ui-ux-pro-max) e a biblioteca Lucide
em versão exata (`lucide@0.460.0`, jsDelivr) com `integrity` (SRI). Isso substitui o "não depender de CDNs/fontes
remotas" da spec §3.4/§9.4 sem perder a garantia de funcionamento: cada ícone é um `<i data-lucide>` que já
contém o SVG embutido (trocado pelo oficial quando a biblioteca carrega) e a pilha de fontes cai para as do
sistema. A CSP e `check_html` aceitam apenas essas URLs; `external_assets: false` volta ao modo estritamente
offline (nenhum host liberado na CSP).
