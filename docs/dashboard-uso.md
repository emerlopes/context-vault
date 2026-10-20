# Dashboards do ContextVault — uso, arquitetura e limitações

Implementação da especificação [dashboard.md](dashboard.md). Os dashboards são arquivos HTML **locais,
autossuficientes e somente leitura**, gerados pelo Core a partir dos registros canônicos
(Markdown/YAML). O HTML é uma representação derivada: nunca é fonte da verdade e nunca altera a memória.

## Instalação

Nada além da CLI: `uv sync` (desenvolvimento) ou `uv tool install .` instala o Jinja2, única dependência
nova. Não há servidor nem banco de dados. Por padrão o relatório carrega as fontes Fira Sans/Fira Code
(Google Fonts) e a biblioteca de ícones Lucide (`lucide@0.460.0`, jsDelivr, com SRI); sem internet ele
continua funcionando com fontes do sistema e os ícones SVG embutidos. `dashboard.external_assets: false`
desliga qualquer requisição externa. Os templates e os assets vão dentro do pacote
(`src/context_vault/dashboard/templates` e `assets`), então funcionam também a partir do wheel.

Para o agente reconhecer pedidos de visualização, reinstale/atualize a skill:
`context-vault install-skill --agent <claude-code|codex|gemini|devin|all> --force`.

## Uso

```bash
context-vault dashboard build                                   # visão geral → reports/dashboard.html
context-vault dashboard build --view tasks --overdue            # tarefas atrasadas
context-vault dashboard build --view tasks --group-by assignee  # agrupadas por responsável
context-vault dashboard build --view tasks --person "João" --output reports/joao.html
context-vault dashboard build --view project-detail --project Orion
context-vault dashboard build --view person-detail --person "João Silva"
context-vault dashboard build --view agenda --from 2026-10-20 --to 2026-10-27
context-vault dashboard build --view overview --topic ABC       # visão filtrada por assunto
context-vault dashboard build --view attention --json           # "o que precisa da minha atenção?"
context-vault dashboard list                                    # relatórios gerados + visões disponíveis
context-vault dashboard refresh --output reports/joao.html      # mesma visão e filtros, dados atuais
context-vault dashboard open --output reports/dashboard.html    # navegador padrão do sistema
```

Visões: `overview`, `tasks`, `projects`, `project-detail`, `people`, `person-detail`, `agenda`,
`architecture`, `knowledge`, `attention`. Filtros: `--person`, `--project`, `--topic` (nome, sigla, alias,
ID ou prefixo — resolvidos pelo Core; homônimos → `AMBIGUOUS_MATCH` com `candidates`), `--from/--to`
(ISO ou relativo), `--status`, `--priority`, `--overdue`, `--unassigned`, `--no-due`,
`--include-cancelled`, `--group-by`. `--include-model` devolve o modelo de dados junto com a resposta.

Pelo agente, basta pedir: "Quero ver um resumo visual do meu ContextVault", "Monte um painel do Orion",
"Mostre só as pendências do João", "Monte uma visão da minha semana", "Atualize o dashboard que geramos
ontem". O roteamento está em [skills/context-vault/references/dashboard.md](../skills/context-vault/references/dashboard.md).

Exemplos gerados a partir dos dados de teste (fictícios): [examples/dashboard/](examples/dashboard/)
— regenere com `uv run python scripts/dashboard_demo.py`.

## Configuração (`config.yaml` da memória)

```yaml
dashboard:
  output_dir: reports            # pasta dos relatórios dentro do repositório (ignorada pelo Git)
  allow_external_output: false   # true permite --output fora do repositório de memória
  external_assets: true          # Google Fonts + Lucide fixados (SRI); false = nenhuma requisição externa
  upcoming_days: 7               # janela de "próximos compromissos"
  recent_days: 7                 # janela de "concluídas no período" e "atividades recentes"
  attention_days: 2              # compromissos que entram no painel de atenção (hoje + N dias)
  attention:                     # pesos de ordenação (não são probabilidades)
    overdue_task: 100
    blocked_project: 90
    blocked_task: 85
    critical_risk: 80
    inconsistency: 70
    pending_decision: 65
    upcoming_meeting: 50
    unassigned_task: 45
    knowledge_gap: 20
```

Repositórios criados antes desta versão não precisam de alteração: os valores acima são o padrão.

## Design (skill ui-ux-pro-max)

Design system "Data-Dense Dashboard": primária `#1E40AF`, secundária `#3B82F6`, destaque âmbar `#F59E0B`,
fundo `#F8FAFC`, texto `#0F172A`, secundário `#475569` (contraste AA); tipografia Fira Sans (texto) e Fira
Code (números, contadores e IDs). Ícones Lucide (SVG, nunca emoji ou símbolos Unicode), status sempre com
ícone + texto. Alvos de toque de 44px, foco visível, transições de 200ms só em cor/borda/sombra (sem
deslocar layout), `prefers-reduced-motion`, escala de z-index (`--z-sticky`, `--z-skip`), corpo de 16px,
linhas de apoio limitadas a 75 caracteres, destaque de linha nas tabelas, temas claro/escuro/automático e
quebras em 375/768/1024/1440px. Os headings usam Fira Sans em vez de Fira Code, por legibilidade em
português; Fira Code fica para os dados numéricos.

## Arquitetura

```text
CLI (cli/dashboard.py)
  └─ service.build ── Snapshot.load (queries.py) ── catálogo (cache), tarefas, agenda, grafo: 1 leitura cada
        ├─ filters.resolve_options ── resolve_ref / resolver do Core (IDs canônicos)
        ├─ aggregations.py / attention.py ── indicadores e itens (regras do Core: is_overdue, matches_person,
        │                                    memberships, grafo, section_items, history_entries)
        ├─ models.Dashboard (Pydantic, schema_version "1.0") ── security.redact_tree (segredos)
        ├─ renderer.render ── Jinja2 (autoescape) + CSS/JS embutidos + CSP com hash do script
        ├─ security.check_html ── HTML bem formado, sem recursos externos, sem script injetado
        └─ escrita atômica → releitura → registro em .context-vault/cache/dashboards/registry.json
```

- **Templates não interpretam dados**: datas, status, rótulos ("Não informado", "Atrasada há 3 dias") e
  contagens chegam prontos no modelo; os templates só imprimem.
- **Rastreabilidade**: cada item tem `source` (`path` + `record_id`) e o HTML liga para o arquivo canônico
  (link relativo, funciona com `file://`); a seção "Fontes" lista todos os arquivos usados.
- **Regeneração**: o manifesto (visão + filtros com entidades por ID e períodos como pedidos) vai embutido
  no HTML e no registro em cache; `refresh` o lê e gera de novo com os dados atuais.
- **Interatividade** (`assets/dashboard.js`): busca textual, filtros e ordenação de tabelas, tema
  claro/escuro/automático, navegação entre seções, detalhes expansíveis. Sem rede, sem acesso a arquivos.

## Segurança

- Autoescape do Jinja2 em todo conteúdo; nenhum `|safe` em dado de nota (só nos assets do pacote).
- `Content-Security-Policy`: `default-src 'none'`; scripts só o `dashboard.js` (por sha256) e a URL exata da
  Lucide (com `integrity`); fontes só de `fonts.googleapis.com`/`fonts.gstatic.com`. Mesmo que marcação
  passasse pelo escape, não executaria nem carregaria nada fora disso. Com `external_assets: false` a CSP
  não libera nenhum host.
- Antes de gravar, o HTML é verificado (tags balanceadas, nenhum `src`/`href` remoto fora da lista fixada,
  script remoto sem `integrity` recusado, nenhum `javascript:`,
  nenhum atributo `on*`, nenhum `<iframe>`/`<form>`/`<base>`, número exato de `<script>`); falha → erro e
  nada é gravado.
- Segredos: todo texto do modelo passa pelos mesmos padrões de credencial do Core e é substituído por
  "[conteúdo sensível ocultado]" (aviso `SECRET_REDACTED`, sem repetir o valor).
- Caminhos: saída só em `reports/` do repositório (ou fora dele com `allow_external_output: true`);
  traversal, `.git`, links simbólicos para fora e extensões diferentes de `.html` são recusados.
- `reports/.gitignore` (e a regra `reports/` no `.gitignore` de memórias novas) mantém os HTMLs fora do Git.
  Nada é publicado, enviado nem commitado.

## Resultado dos testes

`uv run pytest tests/dashboard` — 81 testes (consultas, agregações, renderização, segurança, CLI e os 15
cenários de aceitação CV-DASH-001…015 em `test_acceptance.py`). Suíte completa: 422 testes (421 passam, 1 ignorado
— colisão de maiúsculas exige sistema de arquivos sensível a caixa).

## Limitações conhecidas

- **Risco "crítico"** é detectado de forma léxica nas seções `Riscos` ("crítico", "grave", "alto risco",
  "bloqueante"); o Core não tem um campo estruturado de severidade.
- **Um responsável por tarefa** (limitação do modelo de tarefas): co-responsáveis registrados em `note`
  não entram nos agrupamentos.
- **Hipóteses e discussões sem decisão** vêm das marcações de hipótese do Core e das seções `Dúvidas
  conhecidas`/`Dúvidas em aberto`/`Problema`; uma discussão registrada fora dessas seções não aparece.
- **Atividade recente** depende do diário (`.context-vault/journal`); edições manuais fora do Core não
  aparecem ali.
- A visão de conhecimento usa listas e cartões; grafo interativo fica para uma evolução.
- Tabelas grandes usam filtros e busca locais, sem paginação; centenas a poucos milhares de registros são
  confortáveis, volumes muito maiores deixam o HTML pesado.
- `dashboard open` usa o navegador padrão via `webbrowser`; em ambientes sem interface gráfica devolve
  `opened: false` e o caminho para abrir manualmente.
- Exportação com anonimização para compartilhamento não foi implementada (spec §14.6, evolução futura).
