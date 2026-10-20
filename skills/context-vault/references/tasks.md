# Pendências

Tarefas ficam em `pendencias/tarefas.yaml`. Status: `open`, `in_progress`, `blocked`, `completed`,
`cancelled`. Prioridade: `low`, `normal`, `high`, `urgent`.

## Quando criar uma tarefa

Só quando há **ação concreta** atribuída ou combinada ("João precisa criar o repositório até sexta").
Problema relatado sem ação ("as aplicações estão sem documentação") é conhecimento, não tarefa:
registre o problema e, se fizer sentido, pergunte se existe iniciativa para resolvê-lo. Lacuna de
conhecimento também não é tarefa.

"João ficou responsável pela documentação do ABC" é vago: pergunte uma vez qual é a ação (criar o
repositório, escrever, ambos). Não crie duas tarefas por conta própria.

## Criar — `tasks add --input -`

```json
{
  "request_id": "req-20261020-repo-doc-abc",
  "title": "Criar repositório de documentação do ABC",
  "assignee_name": "João",
  "due_date": "sexta",
  "related_ids": ["<id do ABC>"],
  "note": "Pedido porque o usuário está sem acesso ao GitHub",
  "source": {"type": "user", "original_text": "Pedi para João criar o repositório ABC porque estou sem acesso ao GitHub"}
}
```

- **Responsável:** `assignee_id` (se resolvido) ou `assignee_name`. Nome que identifica exatamente uma
  pessoa é vinculado; homônimos → `AMBIGUOUS_MATCH` (pergunte); nome desconhecido fica só como nome.
  Nunca atribua ao usuário sem ele dizer.
- **Prazo:** só se informado; aceita expressão relativa. Nada de prazo ou prioridade inventados.
- **Contexto:** `note` (por que existe, de onde veio), `description`.
- **Dependência entre tarefas:** `blocked_by: [<id>]` quando a mensagem sustenta a ordem ("Maria escreve
  depois que João criar o repositório").
- `--dry-run` mostra duplicatas, prazo resolvido e responsável sem gravar.

## Duplicatas

- Mesma tarefa aberta (título igual, mesmo responsável) → reconhecida, nada criado: diga que já existia.
- Parecida → `possible_duplicate` com `candidates`: pergunte se é a mesma; se for, atualize a existente
  com `tasks update` (acrescente `note`, prazo…) em vez de criar.
- Igual a uma concluída → `repeats_completed_task`: se for nova execução, inclua a antiga em `related_ids`.

## Consultar — `tasks list`

Padrão: abertas, em andamento e bloqueadas. Filtros: `--assignee João`, `--project <id>` (inclui tarefas
de reuniões do projeto), `--status`, `--overdue`, `--due "esta semana"`, `--due-from/--due-to`,
`--meeting <id|last>`, `--query`, `--all`. `tasks read <id> [--history]`.

## Atualizar e concluir

- `tasks update --input -` com `{"request_id", "id", ...}`: `status`, `assignee_name`, `due_date`
  (`null` limpa), `priority`, `add_related_ids`, `add_blocked_by`, `note`, `reason`. Histórico preservado.
- "Concluí / o João terminou X" → localize (`tasks list --query`), confirme se houver mais de uma
  candidata, e `tasks complete <id> [--reason]`. Concluir de novo não gera segunda conclusão.
- Reabrir uma concluída → `reopen_completed_task` (pergunte).
- Concluir a tarefa **não** conclui o projeto nem a entrega relacionada; criar o repositório não é ter a
  documentação pronta.
