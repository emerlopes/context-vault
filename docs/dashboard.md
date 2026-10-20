# ContextVault Dashboard — Especificação Funcional e Técnica Completa

**Versão:** 1.0  
**Status:** Especificação para implementação  
**Produto:** ContextVault  
**Módulo:** Dashboard e relatórios visuais  
**Prioridade:** Obrigatória na versão 1.0 do módulo  
**Idioma:** Português brasileiro  
**Arquitetura:** Local-first, offline-first, multiagente  
**Tecnologia principal:** Python, Jinja2, HTML, CSS e JavaScript  
**Persistência:** Repositório local Git com Markdown/YAML

---

# 1. Objetivo

Implementar no ContextVault a capacidade de gerar **dashboards HTML locais, visuais, interativos e reutilizáveis** a partir das informações armazenadas em sua memória profissional.

O usuário deve conseguir solicitar visualizações utilizando linguagem natural, sem precisar conhecer comandos, templates ou a estrutura dos arquivos.

Exemplos:

- "Quero ver um resumo visual do meu ContextVault."
- "Monte um dashboard com minhas tarefas."
- "Mostre visualmente tudo que precisa da minha atenção."
- "Crie um painel do projeto Orion."
- "Quero visualizar as responsabilidades do João."
- "Gere um resumo visual das decisões arquiteturais."
- "Monte um HTML com o que está pendente nesta semana."
- "Atualize meu dashboard."

A IA deve interpretar a intenção, selecionar os dados necessários, escolher o template apropriado e solicitar ao Core Python a geração do HTML.

**Princípio central:**

> O ContextVault é responsável pela verdade dos dados. A IA interpreta a intenção do usuário. O Dashboard transforma os dados validados em uma apresentação visual.

A geração do dashboard não deve alterar registros de conhecimento, tarefas, projetos ou decisões.

---

# 2. Escopo funcional

O módulo deve oferecer:

1. Dashboard geral do ContextVault.
2. Dashboard de tarefas e pendências.
3. Dashboard de projetos.
4. Dashboard de pessoas e responsabilidades.
5. Dashboard de agenda.
6. Dashboard de arquitetura e decisões.
7. Dashboard de conhecimento e domínios.
8. Dashboard inteligente de itens que precisam de atenção.
9. Dashboards filtrados por projeto, pessoa, assunto ou período.
10. Regeneração de dashboards existentes.
11. Exportação para arquivo HTML autossuficiente.
12. Rastreabilidade dos dados apresentados.
13. Filtros e busca dentro do HTML.
14. Funcionamento offline.
15. Compatibilidade com múltiplos agentes.

O módulo deve consumir os dados dos oito módulos obrigatórios do ContextVault:

```text
context-vault/
├── INDEX.md
├── dominios/
├── projetos/
├── arquitetura/
├── pessoas-times/
├── reunioes/
├── agenda/
└── pendencias/
```

---

# 3. Princípios arquiteturais

## 3.1 Fonte única da verdade

Os registros Markdown/YAML do ContextVault continuam sendo a fonte canônica.

O HTML é apenas uma representação derivada.

Não manter uma segunda base de tarefas, projetos ou pessoas dentro do módulo de dashboard.

## 3.2 Separação de responsabilidades

A arquitetura deve separar quatro camadas:

**Camada 1 — Interpretação da IA**

Identifica o objetivo da solicitação e os filtros relevantes.

**Camada 2 — Consulta e agregação**

O Core Python consulta registros, resolve relacionamentos e calcula indicadores.

**Camada 3 — Modelo de apresentação**

Os resultados são transformados em estruturas de dados validadas.

**Camada 4 — Renderização**

Templates Jinja2 produzem HTML, CSS e JavaScript.

Fluxo:

```text
Usuário
   |
   v
Agente de IA
   |
   | Interpreta intenção
   v
Skill ContextVault
   |
   | Invoca operação estruturada
   v
Core Python
   |
   | Consulta e valida
   v
Registros Markdown/YAML
   |
   | Agregação
   v
View Model JSON
   |
   | Renderização Jinja2
   v
Dashboard HTML
   |
   v
Navegador local
```

## 3.3 Templates não interpretam Markdown

Os templates HTML não devem:

- Ler diretamente os arquivos Markdown.
- Resolver entidades.
- Calcular status de tarefas.
- Interpretar datas.
- Executar consultas semânticas.
- Decidir quais registros são duplicados.

Essas responsabilidades pertencem ao Core.

## 3.4 Funcionamento offline

A geração e a visualização devem funcionar sem internet.

Não depender de:

- CDNs.
- APIs externas.
- Fontes remotas.
- Serviços de autenticação online.
- Bancos de dados externos.
- Servidores obrigatórios.

## 3.5 Compatibilidade multiagente

Claude Code, Codex, Gemini e outros agentes compatíveis devem utilizar a mesma interface determinística do Core.

Nenhum agente deve implementar sua própria lógica de leitura e agregação para dashboards.

---

# 4. Estrutura de diretórios

Adicionar ao projeto:

```text
context-vault/
├── INDEX.md
├── dominios/
├── projetos/
├── arquitetura/
├── pessoas-times/
├── reunioes/
├── agenda/
├── pendencias/
│
├── templates/
│   └── dashboards/
│       ├── base.html
│       ├── overview.html
│       ├── tasks.html
│       ├── projects.html
│       ├── project-detail.html
│       ├── people.html
│       ├── person-detail.html
│       ├── agenda.html
│       ├── architecture.html
│       ├── knowledge.html
│       ├── attention.html
│       └── components/
│           ├── metric-card.html
│           ├── task-table.html
│           ├── project-card.html
│           ├── status-badge.html
│           ├── source-link.html
│           ├── empty-state.html
│           └── section-header.html
│
├── assets/
│   └── dashboards/
│       ├── dashboard.css
│       └── dashboard.js
│
├── reports/
│   └── .gitkeep
│
├── .context-vault/
│   └── cache/
│       └── dashboards/
│
├── src/
│   └── context_vault/
│       └── dashboard/
│           ├── models.py
│           ├── queries.py
│           ├── aggregations.py
│           ├── filters.py
│           ├── attention.py
│           ├── renderer.py
│           ├── security.py
│           └── service.py
│
└── tests/
    └── dashboard/
        ├── test_queries.py
        ├── test_aggregations.py
        ├── test_renderer.py
        ├── test_security.py
        ├── test_cli.py
        └── test_acceptance.py
```

Os templates e assets devem ser versionados no Git.

Os HTMLs gerados devem ser ignorados pelo Git por padrão, pois podem conter informações profissionais sensíveis.

---

# 5. Comportamento esperado da IA

A IA deve reconhecer pedidos de visualização, mesmo quando o usuário não mencionar HTML ou dashboard.

## 5.1 Exemplos de intenções

| Pedido                            | Intenção                       |
| --------------------------------- | ------------------------------ |
| "Quero um resumo visual"          | Dashboard geral                |
| "Mostre minhas pendências"        | Dashboard de tarefas           |
| "Como estão meus projetos?"       | Dashboard de projetos          |
| "Quem está fazendo o quê?"        | Dashboard de responsabilidades |
| "O que precisa da minha atenção?" | Dashboard de atenção           |
| "Monte uma visão do ABC"          | Dashboard filtrado por assunto |
| "Mostre a semana"                 | Dashboard de agenda            |
| "Atualize o painel"               | Regeneração                    |
| "Crie um HTML das decisões"       | Dashboard de arquitetura       |

## 5.2 Seleção automática de template

A IA deve selecionar o template mais adequado à intenção.

Não é necessário perguntar qual template utilizar quando a intenção estiver clara.

Exemplo:

**Usuário:**

> Quero ver minhas tarefas atrasadas.

**Esperado:**

- Selecionar template de tarefas.
- Aplicar filtro de tarefas atrasadas.
- Gerar HTML.
- Informar o caminho do arquivo.

## 5.3 Perguntas somente quando necessárias

**Usuário:**

> Monte um painel do Atlas.

Se existirem dois projetos chamados Atlas, perguntar qual deles.

Se houver apenas um projeto inequívoco, gerar diretamente.

Não perguntar sobre cores, fontes ou organização visual para cada solicitação.

## 5.4 Não inventar indicadores

Se o ContextVault não possuir uma informação, o dashboard deve apresentar:

- "Não informado".
- "Sem dados".
- "Não registrado".

Não estimar progresso, orçamento ou prazos sem regra explícita.

---

# 6. Tipos de dashboard

## 6.1 Dashboard geral — Overview

Comando:

```bash
context-vault dashboard build --view overview
```

Objetivo: oferecer uma visão executiva do estado atual da memória.

### Indicadores principais

- Total de tarefas abertas.
- Total de tarefas atrasadas.
- Total de tarefas em andamento.
- Total de tarefas concluídas no período.
- Projetos ativos.
- Projetos bloqueados.
- Compromissos próximos.
- Decisões pendentes.
- Problemas conhecidos em aberto.
- Lacunas de conhecimento relevantes.

### Seções

**Resumo executivo**

Indicadores principais.

**O que precisa de atenção**

Tarefas atrasadas, projetos bloqueados e decisões pendentes.

**Projetos ativos**

Lista de projetos e situação atual.

**Próximos compromissos**

Agenda dos próximos sete dias.

**Atividades recentes**

Alterações registradas no período.

**Pessoas e responsabilidades**

Resumo das principais atribuições em andamento.

**Conhecimento**

Assuntos recentes ou atualizados.

O dashboard geral não precisa apresentar todos os registros integralmente.

Deve priorizar informação útil e permitir identificar fontes e detalhes.

---

## 6.2 Dashboard de tarefas

Comando:

```bash
context-vault dashboard build --view tasks
```

### Indicadores

- Abertas.
- Em andamento.
- Bloqueadas.
- Atrasadas.
- Concluídas.
- Sem responsável.
- Sem prazo.

### Tabela de tarefas

Campos:

- Título.
- Status.
- Responsável.
- Projeto ou assunto.
- Prazo.
- Prioridade, quando informada.
- Data de atualização.
- Link para origem.

### Filtros

- Status.
- Responsável.
- Projeto.
- Prazo.
- Prioridade.
- Atrasadas.
- Sem responsável.
- Sem prazo.

### Ordenação

- Prazo.
- Responsável.
- Projeto.
- Status.
- Atualização mais recente.

### Regras

Tarefas concluídas não devem ser contadas como atrasadas atualmente.

Tarefas sem prazo não devem ser classificadas como atrasadas.

Uma tarefa atribuída a duas pessoas deve ser contada uma única vez no total de tarefas.

---

## 6.3 Dashboard de projetos

Comando:

```bash
context-vault dashboard build --view projects
```

### Informações

- Projetos ativos.
- Projetos concluídos.
- Projetos bloqueados.
- Projetos pausados.
- Responsáveis.
- Pendências relacionadas.
- Riscos.
- Bloqueios.
- Decisões.
- Próximas entregas.

### Indicador de progresso

O progresso poderá ser calculado por quantidade de tarefas concluídas sobre tarefas totais vinculadas ao projeto.

Entretanto, esse indicador deve ser identificado como:

**"Percentual de tarefas concluídas"**

Não apresentar automaticamente como:

**"Percentual de conclusão do projeto"**

Essas métricas não são equivalentes.

Exemplo:

```text
Projeto Atlas

7 de 10 tarefas concluídas
70% das tarefas concluídas
```

Se não houver tarefas relacionadas, apresentar "Sem dados suficientes para calcular".

Não inventar progresso.

---

## 6.4 Dashboard de projeto específico

Comando:

```bash
context-vault dashboard build \
  --view project-detail \
  --project project-orion
```

### Seções

- Identificação do projeto.
- Objetivo.
- Status.
- Responsáveis atuais.
- Histórico de participantes.
- Tarefas abertas.
- Tarefas concluídas.
- Riscos.
- Bloqueios.
- Dependências.
- Decisões arquiteturais.
- Reuniões relacionadas.
- Compromissos futuros.
- Histórico de alterações.
- Fontes.

O dashboard deve distinguir responsabilidades atuais de participações históricas.

---

## 6.5 Dashboard de pessoas e responsabilidades

Comando:

```bash
context-vault dashboard build --view people
```

### Informações

- Pessoas cadastradas.
- Equipes.
- Responsabilidades atuais.
- Tarefas abertas por pessoa.
- Projetos atuais.
- Tarefas concluídas no período.
- Pessoas com tarefas atrasadas.
- Responsabilidades sem identificação clara.

### Histórico

A pessoa deve possuir identidade estável.

Vínculos com projetos e equipes devem considerar períodos de início e término.

Exemplo:

```text
João Silva

Projeto atual:
- Orion — Integração de pagamentos

Participação anterior:
- Atlas — Backend

Tarefas:
- 2 abertas
- 1 atrasada
- 8 concluídas
```

Não interpretar o encerramento da participação em um projeto como desligamento da empresa.

---

## 6.6 Dashboard de pessoa específica

Comando:

```bash
context-vault dashboard build \
  --view person-detail \
  --person person-001
```

### Seções

- Nome.
- Equipe atual, quando conhecida.
- Responsabilidades atuais.
- Projetos atuais.
- Projetos anteriores.
- Tarefas abertas.
- Tarefas concluídas.
- Histórico de mudanças.
- Relações com assuntos e sistemas.
- Fontes.

Não apresentar informações pessoais sensíveis desnecessárias.

---

## 6.7 Dashboard de agenda

Comando:

```bash
context-vault dashboard build --view agenda
```

### Informações

- Compromissos de hoje.
- Compromissos da semana.
- Próximas reuniões.
- Reuniões canceladas, quando filtro solicitado.
- Projetos relacionados.
- Pendências relevantes para reuniões.
- Decisões anteriores relacionadas.

### Regras

A agenda do MVP é mantida manualmente no ContextVault.

Não presumir sincronização com Google Calendar, Outlook ou outros serviços.

Utilizar o fuso horário configurado.

Compromissos cancelados não devem aparecer como eventos futuros ativos.

---

## 6.8 Dashboard de arquitetura

Comando:

```bash
context-vault dashboard build --view architecture
```

### Informações

- Decisões aceitas.
- Decisões propostas.
- Decisões substituídas.
- Decisões pendentes.
- Integrações entre sistemas.
- Dependências.
- Riscos arquiteturais.
- Problemas conhecidos.

### Regras

Distinguir:

- Decisão aceita.
- Proposta.
- Hipótese.
- Discussão sem decisão.
- Decisão substituída.

Não apresentar uma decisão histórica substituída como vigente.

---

## 6.9 Dashboard de conhecimento

Comando:

```bash
context-vault dashboard build --view knowledge
```

### Informações

- Domínios.
- Sistemas.
- Serviços.
- Conceitos.
- Integrações.
- Assuntos mais relacionados.
- Assuntos atualizados recentemente.
- Lacunas de conhecimento.
- Registros provisórios.

### Objetivo

Permitir uma visão organizada da memória acumulada.

Na primeira versão, utilizar listas, cartões e agrupamentos.

Grafos interativos de conhecimento podem ser uma evolução futura, desde que os relacionamentos estejam disponíveis no Core.

---

## 6.10 Dashboard de atenção

Comando:

```bash
context-vault dashboard build --view attention
```

Esse dashboard deve responder a pedidos como:

> "O que precisa da minha atenção?"

### Fontes de atenção

- Tarefas atrasadas.
- Tarefas bloqueadas.
- Projetos bloqueados.
- Riscos críticos registrados.
- Decisões aguardando definição.
- Compromissos próximos.
- Pendências sem responsável.
- Lacunas de conhecimento relevantes.
- Inconsistências detectadas.

### Priorização

Utilizar regras determinísticas configuráveis.

Exemplo:

```yaml
attention:
  overdue_task: 100
  blocked_project: 90
  blocked_task: 85
  critical_risk: 80
  pending_decision: 65
  upcoming_meeting: 50
  unassigned_task: 45
  knowledge_gap: 20
```

Os valores são pesos de ordenação, não probabilidades.

A IA pode sugerir agrupamentos e explicações, mas não deve alterar arbitrariamente os pesos durante a renderização.

### Explicabilidade

Cada item destacado deve informar por que precisa de atenção.

Exemplo:

```text
Validar integração Orion

Motivo:
- Tarefa aberta
- Prazo vencido há 3 dias
- Projeto Orion ativo
```

---

# 7. Modelo de dados para renderização

O Core deve produzir um modelo estruturado independente do HTML.

Exemplo simplificado:

```json
{
  "schema_version": "1.0",
  "view": "overview",
  "generated_at": "2026-10-20T09:00:00-03:00",
  "timezone": "America/Sao_Paulo",
  "filters": {},
  "metrics": {
    "open_tasks": 12,
    "overdue_tasks": 3,
    "active_projects": 4,
    "blocked_projects": 1,
    "upcoming_events": 6
  },
  "tasks": [
    {
      "id": "task-001",
      "title": "Criar repositório ABC",
      "status": "open",
      "responsible_ids": ["person-001"],
      "responsible_names": ["João"],
      "project_id": null,
      "due_date": null,
      "overdue": false,
      "source_path": "pendencias/tarefas.yaml"
    }
  ],
  "projects": [],
  "events": [],
  "attention_items": [],
  "warnings": []
}
```

Esse JSON é ilustrativo.

A implementação deve definir modelos Pydantic completos e versionados.

## 7.1 Campos obrigatórios do envelope

- `schema_version`
- `view`
- `generated_at`
- `timezone`
- `filters`
- `metrics`
- `data`
- `sources`
- `warnings`

A estrutura interna pode ser especializada por tipo de dashboard.

## 7.2 IDs estáveis

Todas as referências devem utilizar IDs canônicos.

Não utilizar o título do arquivo como identidade definitiva.

## 7.3 Rastreabilidade

Cada entidade apresentada deve manter referência à sua origem.

Exemplo:

```json
{
  "id": "task-001",
  "source": {
    "path": "pendencias/tarefas.yaml",
    "record_id": "task-001"
  }
}
```

---

# 8. Consultas e agregações

O módulo deve reutilizar as consultas oficiais do Core.

Não duplicar lógica de negócio.

## 8.1 Consulta de tarefas

A consulta deve permitir:

```text
status
responsible_id
project_id
topic_id
due_before
due_after
updated_after
include_completed
```

## 8.2 Consulta de projetos

Filtros:

```text
status
responsible_id
has_blockers
has_risks
updated_after
```

## 8.3 Consulta de pessoas

Filtros:

```text
team_id
project_id
active_only
has_open_tasks
```

## 8.4 Consulta de agenda

Filtros:

```text
starts_after
starts_before
project_id
person_id
include_cancelled
```

## 8.5 Datas

Todas as comparações devem respeitar o fuso configurado.

A classificação de atraso deve considerar a data local e as regras do tipo de prazo.

Não tratar datas sem horário como instantes UTC arbitrários.

## 8.6 Duplicações

As agregações devem operar sobre entidades canônicas.

Uma tarefa com múltiplas referências não deve ser contada várias vezes.

---

# 9. Interface visual

## 9.1 Diretrizes de design

O dashboard deve ter aparência profissional, limpa e legível.

Priorizar:

- Boa hierarquia visual.
- Espaçamento consistente.
- Tipografia legível.
- Cores discretas.
- Indicadores claros.
- Navegação simples.
- Responsividade.
- Estados vazios bem tratados.

Evitar excesso de gráficos e elementos decorativos.

## 9.2 Estrutura padrão

Cabeçalho:

```text
ContextVault
Visão geral

Gerado em: 20/10/2026 às 09h
Dados locais
```

Corpo:

```text
[Indicadores principais]

[Itens que precisam de atenção]

[Projetos]

[Pendências]

[Agenda]

[Atividade recente]
```

Rodapé:

```text
Gerado pelo ContextVault
Fonte: repositório local
Relatório somente leitura
```

## 9.3 Responsividade

O HTML deve funcionar em:

- Desktop.
- Notebook.
- Tablet.
- Smartphone.

Em telas pequenas:

- Cartões devem reorganizar-se.
- Tabelas devem permitir rolagem horizontal ou apresentação alternativa.
- Textos não devem ser cortados.
- Filtros devem continuar utilizáveis.

## 9.4 Tema

Suportar:

- Claro.
- Escuro.
- Automático, conforme preferência do navegador.

Sem dependência de fontes remotas.

## 9.5 Acessibilidade

Incluir:

- HTML semântico.
- Contraste adequado.
- Navegação por teclado.
- Rótulos em filtros.
- Estados de foco visíveis.
- Indicadores de status que não dependam apenas de cor.
- Cabeçalhos adequados em tabelas.

---

# 10. Interatividade no HTML

O HTML poderá conter JavaScript local para:

- Busca textual.
- Filtros.
- Ordenação.
- Expansão de detalhes.
- Alternância de tema.
- Navegação entre seções.
- Exibição de fontes.

Essas interações devem funcionar sem servidor.

O JavaScript não deve:

- Alterar arquivos Markdown.
- Modificar tarefas no repositório.
- Executar comandos locais.
- Fazer chamadas externas.
- Enviar dados para serviços remotos.

O dashboard é somente leitura.

---

# 11. HTML autossuficiente

O formato padrão deve ser um único arquivo HTML.

Exemplo:

```text
reports/dashboard.html
```

O arquivo deve conter os estilos e scripts necessários para funcionar offline.

Não depender de caminhos absolutos para CSS ou JavaScript.

A geração pode utilizar arquivos de desenvolvimento separados, mas deve incorporá-los ao HTML final.

## 11.1 Vantagens

- Fácil abertura no navegador.
- Fácil compartilhamento controlado.
- Independência de servidor.
- Simplicidade de armazenamento.
- Compatibilidade entre sistemas operacionais.

## 11.2 Limitação importante

O HTML representa um retrato dos dados no momento da geração.

Alterações posteriores no ContextVault não aparecem automaticamente.

O dashboard deve mostrar claramente a data e a hora de geração.

---

# 12. Geração e atualização

## 12.1 Geração padrão

```bash
context-vault dashboard build --view overview
```

Saída esperada:

```text
reports/dashboard.html
```

## 12.2 Arquivo de saída personalizado

```bash
context-vault dashboard build \
  --view tasks \
  --output reports/minhas-tarefas.html
```

## 12.3 Filtro por pessoa

```bash
context-vault dashboard build \
  --view tasks \
  --person person-001
```

## 12.4 Filtro por projeto

```bash
context-vault dashboard build \
  --view project-detail \
  --project project-orion
```

## 12.5 Filtro por período

```bash
context-vault dashboard build \
  --view agenda \
  --from 2026-10-20 \
  --to 2026-10-27
```

## 12.6 Regeneração

```bash
context-vault dashboard refresh \
  --output reports/dashboard.html
```

A implementação deve preservar metadados suficientes para recuperar a visualização e os filtros utilizados.

Esses metadados podem ser armazenados em manifesto separado ou incorporados ao relatório.

## 12.7 Abrir no navegador

Opcionalmente:

```bash
context-vault dashboard open \
  --output reports/dashboard.html
```

O comando deve respeitar o sistema operacional e não exigir navegador específico.

---

# 13. Interface JSON para agentes

A CLI deve suportar saída estruturada.

Exemplo:

```bash
context-vault dashboard build \
  --view overview \
  --json
```

Resposta esperada:

```json
{
  "success": true,
  "view": "overview",
  "output_path": "reports/dashboard.html",
  "generated_at": "2026-10-20T09:00:00-03:00",
  "records_read": 124,
  "warnings": []
}
```

Em caso de erro:

```json
{
  "success": false,
  "error": {
    "code": "AMBIGUOUS_PROJECT",
    "message": "Mais de um projeto corresponde a Atlas.",
    "candidates": ["project-001", "project-008"]
  }
}
```

Não retornar sucesso antes de o arquivo ter sido gerado e validado.

---

# 14. Segurança

## 14.1 Escape de conteúdo

Todo conteúdo proveniente das notas deve ser tratado como dado não confiável.

Utilizar autoescape no Jinja2.

Não utilizar renderização HTML não escapada em campos de conteúdo do usuário.

## 14.2 Prevenção de injeção

Anotações não podem:

- Inserir scripts executáveis.
- Alterar a estrutura de segurança do template.
- Executar instruções da IA.
- Incluir conteúdo remoto automaticamente.
- Acessar arquivos arbitrários.

## 14.3 Caminhos

Validar caminhos de entrada e saída.

Não permitir escrita fora das áreas autorizadas, salvo autorização explícita do usuário e política do Core.

## 14.4 Privacidade

Os relatórios podem conter informações sensíveis.

Por padrão:

- Gerar localmente.
- Não publicar.
- Não enviar para serviços externos.
- Não fazer push automático.
- Ignorar HTMLs gerados no Git.
- Não incluir segredos detectados.

## 14.5 Dados sensíveis

Credenciais, tokens, senhas e segredos não devem aparecer no dashboard.

Aplicar as políticas de proteção já existentes no Core.

## 14.6 Compartilhamento

O usuário poderá compartilhar manualmente um HTML, mas o ContextVault não deve presumir que esse compartilhamento é seguro.

Uma futura evolução poderá oferecer exportação com anonimização.

---

# 15. Desempenho

O dashboard deve evitar ler e processar repetidamente os mesmos arquivos durante uma geração.

Utilizar:

- Índice existente.
- Consultas estruturadas.
- Cache derivado quando apropriado.
- Agregações eficientes.
- Renderização única.

O cache não deve ser fonte da verdade.

## 15.1 Invalidação

O cache deve ser invalidado quando registros relevantes forem alterados.

## 15.2 Volume de dados

O sistema deve funcionar com centenas ou milhares de registros sem depender de serviços externos.

Tabelas grandes podem usar paginação ou filtros locais.

---

# 16. Tratamento de ausência de dados

O dashboard deve funcionar mesmo quando a memória estiver vazia.

Exemplo:

```text
Nenhuma tarefa registrada.

As tarefas aparecerão aqui quando forem
adicionadas ao ContextVault.
```

Não apresentar números fictícios.

Não criar registros apenas para preencher o dashboard.

## 16.1 Dados incompletos

Exemplo:

```text
Projeto Orion

Responsável: Não informado
Prazo: Não informado
Status: Ativo
```

## 16.2 Registros inconsistentes

Quando o Core detectar problemas:

- Exibir aviso.
- Identificar registros afetados.
- Evitar métricas incorretas.
- Não corrigir silenciosamente os dados durante a renderização.

---

# 17. Integração com a skill

Adicionar à skill instruções para reconhecer solicitações de visualização.

## 17.1 Fluxo da IA

Quando o usuário pedir um resumo visual:

1. Identificar intenção.
2. Determinar visualização.
3. Identificar filtros.
4. Resolver entidades.
5. Consultar o Core.
6. Invocar geração.
7. Confirmar sucesso.
8. Informar caminho do HTML.
9. Disponibilizar abertura ou link quando o ambiente permitir.

## 17.2 Exemplo

**Usuário:**

> Quero ver um resumo visual do meu ContextVault.

**Ação esperada:**

```bash
context-vault dashboard build \
  --view overview \
  --json
```

**Resposta após sucesso:**

> Gereei o dashboard geral do ContextVault em `reports/dashboard.html`. Ele contém indicadores de tarefas, projetos, agenda e itens que precisam de atenção.

A resposta deve refletir o resultado real da operação.

## 17.3 Outro exemplo

**Usuário:**

> Monte um painel com as pendências do João.

**Esperado:**

- Identificar João.
- Resolver ID.
- Selecionar template de tarefas.
- Aplicar filtro de responsável.
- Gerar HTML.
- Não criar tarefas novas.

---

# 18. Exemplos de uso e comportamento esperado

## CV-DASH-001 — Dashboard geral

**Usuário:**

> Quero um resumo visual de tudo que tenho anotado.

**Esperado:**

- Gerar overview.
- Incluir indicadores.
- Incluir itens de atenção.
- Incluir projetos e pendências.
- Incluir agenda e alterações recentes quando disponíveis.
- Não inventar dados.

---

## CV-DASH-002 — Tarefas atrasadas

**Usuário:**

> Mostre visualmente minhas tarefas atrasadas.

**Esperado:**

- Consultar tarefas abertas com prazo vencido.
- Excluir concluídas.
- Excluir tarefas sem prazo.
- Gerar HTML filtrado.

---

## CV-DASH-003 — Tarefas por responsável

**Usuário:**

> Monte um HTML das tarefas agrupadas por responsável.

**Esperado:**

- Agrupar por pessoa.
- Exibir tarefas sem responsável separadamente.
- Não duplicar tarefas compartilhadas no total geral.

---

## CV-DASH-004 — Projeto específico

**Usuário:**

> Quero um dashboard do Orion.

**Esperado:**

- Localizar Orion.
- Gerar visão de projeto.
- Incluir tarefas, riscos, bloqueios, decisões e responsáveis.

---

## CV-DASH-005 — Pessoa específica

**Usuário:**

> Quero ver o que o João está fazendo.

**Esperado:**

- Identificar João.
- Mostrar responsabilidades atuais.
- Mostrar projetos atuais.
- Mostrar tarefas abertas.
- Distinguir histórico de situação atual.

---

## CV-DASH-006 — Itens de atenção

**Usuário:**

> Mostre o que precisa da minha atenção.

**Esperado:**

- Gerar dashboard de atenção.
- Ordenar itens por regras configuradas.
- Explicar motivo de cada destaque.

---

## CV-DASH-007 — Agenda semanal

**Usuário:**

> Monte um painel da minha semana.

**Esperado:**

- Consultar agenda manual.
- Resolver período.
- Apresentar compromissos.
- Relacionar pendências relevantes.

---

## CV-DASH-008 — Dashboard sem dados

**Estado inicial:** repositório vazio.

**Usuário:**

> Gere o dashboard.

**Esperado:**

- Gerar HTML válido.
- Exibir estados vazios.
- Não criar dados fictícios.

---

## CV-DASH-009 — Regeneração

**Estado inicial:** dashboard gerado anteriormente.

**Usuário:**

> Atualize meu dashboard.

**Esperado:**

- Reutilizar configuração anterior quando identificável.
- Consultar dados atuais.
- Regenerar HTML.
- Atualizar data de geração.
- Não alterar registros canônicos.

---

## CV-DASH-010 — Dados inconsistentes

**Estado inicial:** tarefa referencia pessoa inexistente.

**Usuário:**

> Gere o dashboard de tarefas.

**Esperado:**

- Detectar inconsistência.
- Não inventar nome de pessoa.
- Exibir aviso.
- Gerar relatório parcial apenas quando seguro.

---

## CV-DASH-011 — Conteúdo malicioso

**Estado inicial:** nota contém código HTML e JavaScript.

**Usuário:**

> Gere o dashboard de conhecimento.

**Esperado:**

- Escapar conteúdo.
- Não executar JavaScript da nota.
- Não carregar recursos externos.

---

## CV-DASH-012 — Multiagente

**Preparação:** dois agentes usam o mesmo repositório.

**Agente A:** registra novas tarefas.

**Agente B:** gera dashboard.

**Esperado:**

- Dashboard contém tarefas persistidas pelo agente A.
- Não depende do histórico de conversa do agente A.

---

## CV-DASH-013 — Responsabilidade histórica

**Estado inicial:**

- João participou do Atlas.
- João encerrou participação no Atlas.
- João iniciou participação no Orion.

**Usuário:**

> Gere o painel de responsabilidades do João.

**Esperado:**

- Orion aparece como projeto atual.
- Atlas aparece como participação anterior.
- Não apresentar Atlas como responsabilidade atual.

---

## CV-DASH-014 — Métrica de progresso

**Estado inicial:** projeto com dez tarefas, sete concluídas.

**Usuário:**

> Gere o dashboard do projeto.

**Esperado:**

Mostrar:

> 70% das tarefas concluídas.

Não afirmar:

> Projeto 70% concluído.

---

## CV-DASH-015 — Falha de gravação

**Estado inicial:** diretório de saída sem permissão.

**Usuário:**

> Gere meu dashboard.

**Esperado:**

- Retornar erro estruturado.
- Não declarar sucesso.
- Não apresentar caminho inexistente como arquivo gerado.

---

# 19. Testes automatizados obrigatórios

Criar testes para:

### Consultas

- Tarefas abertas.
- Tarefas atrasadas.
- Projetos ativos.
- Pessoas atuais.
- Participações históricas.
- Agenda por período.
- Decisões vigentes.
- Relacionamentos.

### Agregações

- Contagem correta.
- Deduplicação.
- Tarefas compartilhadas.
- Datas e fusos.
- Indicadores de progresso.
- Ordenação de atenção.

### Renderização

- HTML válido.
- Escape de conteúdo.
- Estados vazios.
- Dados incompletos.
- Inclusão de fontes.
- CSS e JavaScript locais.
- Responsividade básica.

### Segurança

- Injeção de scripts.
- Caminhos inválidos.
- Segredos.
- Ausência de chamadas externas.
- Conteúdo não confiável.

### CLI

- Parâmetros válidos.
- Parâmetros inválidos.
- Saída JSON.
- Erros estruturados.
- Regeneração.
- Filtros.
- Arquivo de saída.

### Integração

- Geração a partir de fixtures reais.
- Atualização de registros seguida de regeneração.
- Compatibilidade entre agentes.
- Preservação dos dados canônicos.

---

# 20. Critérios de aceite

O módulo estará aprovado quando:

1. Gerar dashboard geral em HTML.
2. Gerar dashboard de tarefas.
3. Gerar dashboard de projetos.
4. Gerar dashboard de pessoas.
5. Gerar dashboard de agenda.
6. Gerar dashboard de arquitetura.
7. Gerar dashboard de conhecimento.
8. Gerar dashboard de atenção.
9. Suportar filtros por entidade.
10. Funcionar offline.
11. Não exigir servidor.
12. Produzir HTML autossuficiente.
13. Utilizar templates reutilizáveis.
14. Consultar dados pelo Core.
15. Não duplicar lógica de negócio.
16. Não alterar registros canônicos.
17. Exibir fontes.
18. Exibir data de geração.
19. Tratar dados ausentes.
20. Não inventar métricas.
21. Respeitar histórico temporal.
22. Evitar contagens duplicadas.
23. Proteger contra injeção.
24. Não expor segredos.
25. Gerar saída JSON para agentes.
26. Retornar erros estruturados.
27. Suportar regeneração.
28. Funcionar em múltiplos agentes.
29. Possuir testes automatizados.
30. Passar pelos cenários de aceitação.

---

# 21. Ordem recomendada de implementação

## Etapa 1 — Infraestrutura

- Criar pacote Python do dashboard.
- Definir modelos Pydantic.
- Integrar consultas existentes.
- Implementar agregações.
- Implementar renderizador Jinja2.

## Etapa 2 — Templates fundamentais

- Base.
- Componentes reutilizáveis.
- Dashboard geral.
- Dashboard de tarefas.
- Dashboard de projetos.

## Etapa 3 — Demais visualizações

- Pessoas.
- Agenda.
- Arquitetura.
- Conhecimento.
- Atenção.
- Detalhes por projeto e pessoa.

## Etapa 4 — Interatividade

- Filtros.
- Busca.
- Ordenação.
- Tema.
- Responsividade.

## Etapa 5 — Integração com IA

- Detecção de intenção.
- Seleção automática de template.
- Resolução de filtros.
- Invocação do Core.
- Resposta com caminho do arquivo.

## Etapa 6 — Qualidade

- Testes.
- Segurança.
- Validação de HTML.
- Casos de ausência de dados.
- Testes multiagente.
- Documentação de uso.

---

# 22. Restrições e decisões de projeto

As seguintes decisões são obrigatórias para a primeira versão:

- Não criar aplicação web com backend obrigatório.
- Não introduzir banco de dados externo.
- Não utilizar React ou Node.js como dependências obrigatórias.
- Não depender de serviços online.
- Não gerar um template completamente novo para cada pedido.
- Não permitir que HTML altere diretamente os dados.
- Não calcular métricas por interpretação livre do agente.
- Não executar código proveniente das notas.
- Não publicar dashboards automaticamente.
- Não fazer push automático.
- Não substituir o sistema de consultas do Core.
- Não tratar o HTML como fonte da verdade.

O dashboard deve ser uma camada de apresentação sobre a memória existente.

---

# 23. Instrução final para o agente implementador

Implemente o módulo **ContextVault Dashboard** conforme esta especificação.

Antes de começar:

1. Inspecione a arquitetura atual do ContextVault.
2. Identifique modelos, índices, consultas e relacionamentos existentes.
3. Reutilize as abstrações já implementadas.
4. Evite criar modelos paralelos para tarefas, pessoas e projetos.
5. Identifique eventuais lacunas no Core necessárias para suportar os dashboards.

Durante a implementação:

- Utilize Python 3.11+.
- Utilize Jinja2 para templates.
- Utilize Pydantic para modelos estruturados.
- Mantenha HTML, CSS e JavaScript organizados.
- Gere arquivos autossuficientes.
- Preserve funcionamento offline.
- Utilize dados reais do repositório.
- Garanta rastreabilidade.
- Implemente proteção contra conteúdo malicioso.
- Adicione testes automatizados.

Ao finalizar, entregue:

1. Código-fonte completo.
2. Templates HTML.
3. Estilos CSS.
4. JavaScript local.
5. Comandos CLI.
6. Integração com a skill.
7. Testes automatizados.
8. Documentação de instalação.
9. Exemplos de uso.
10. Um dashboard gerado a partir de dados de teste.
11. Resultado dos testes.
12. Limitações conhecidas.

**Não considere a implementação concluída apenas porque um HTML está visualmente bonito.**

A solução deve demonstrar que os indicadores são calculados corretamente, que os registros são relacionados de forma consistente e que o HTML reflete fielmente a memória persistida.

---

# 24. Resultado esperado

Após a implementação, o usuário poderá conversar normalmente com qualquer agente compatível e solicitar:

> "Quero ver um resumo visual do meu ContextVault."

O agente deverá interpretar a solicitação, consultar o Core e gerar um HTML local com os principais indicadores, projetos, tarefas, agenda e itens que precisam de atenção.

Também deverá entender pedidos como:

> "Mostre só as pendências do João."

> "Quero um painel do projeto Orion."

> "Monte uma visão da minha semana."

> "Quais decisões arquiteturais ainda estão pendentes?"

> "Atualize o dashboard que geramos ontem."

Tudo isso sem exigir que o usuário conheça a estrutura de diretórios, os nomes dos templates ou os comandos internos.

**Visão final:** o ContextVault deve combinar memória profissional estruturada, assistência inteligente por IA e visualização local confiável, permitindo ao usuário registrar conhecimento em linguagem natural e acompanhar visualmente o estado de suas atividades, projetos, responsabilidades e decisões.

---

**Fim da especificação — ContextVault Dashboard v1.0**
