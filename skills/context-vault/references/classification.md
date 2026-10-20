# Classificação e escrita de conhecimento

Como decidir **onde** registrar e **como** montar a proposta. A escrita é sempre
`context-vault propose --input -` (plano, sem gravar) seguido de `context-vault apply --proposal -`.
Os dois aceitam o mesmo JSON pela entrada padrão (`-`).

## Onde registrar

| Assunto | Tipo (`note.type`) | Pasta |
|---|---|---|
| Negócio, sistema, serviço, processo, conceito | `domain` | `dominios/` |
| Projeto ou iniciativa com objetivo/status | `project` | `projetos/` |
| Desenho técnico, integração, componente | `architecture` | `arquitetura/` |
| Decisão arquitetural (com justificativa) | `architecture_decision` | `arquitetura/decisoes/` |
| Pessoa (contexto profissional) | `person` | `pessoas-times/pessoas/` |
| Equipe | `team` | `pessoas-times/times/` |
| Reunião | `meeting` (use `meetings create`) | `reunioes/AAAA/MM/` |

Compromissos e pendências **não** são notas: use `agenda …` e `tasks …`.

Uma informação com vários assuntos tem **um local principal** e relações para os demais
("Atlas depende do ABC" → registre no projeto Atlas e relacione ao ABC com `depends_on`). Não copie
o mesmo texto em várias notas.

## Nível de confiança

| Nível | Quando | Ação |
|---|---|---|
| `high` | Uma nota existente representa claramente o assunto | Atualize (`memory.upsert`) sem perguntar |
| `medium` | Dois ou mais destinos plausíveis | Mostre os candidatos e pergunte qual |
| `low` | Sem contexto suficiente (sigla desconhecida, sem domínio) | Pergunte o contexto; se o usuário não quiser responder, `inbox add` |

O Core exige confirmação para `medium`/`low`; envie `classification.level` honestamente.

Antes de criar: `search "<termo>"`, `resolve "<nome>"` e `read` dos melhores candidatos. Crie uma nota
nova só se o assunto tem identidade própria, há contexto para situá-lo e nenhuma nota existente serve.
O Core pede confirmação de tópico novo (`new_topic`): pergunte "Crio um novo registro para X em Y?".

## Operações

| Operação | Uso | Campos principais |
|---|---|---|
| `memory.create` | Nova nota | `note` {type, title, description, aliases, entities, tags, relations, extra}, `change`/`changes` |
| `memory.upsert` | Acrescentar a uma nota | `target_id`, `change`/`changes`, `milestones`, `blockers`, `memberships` |
| `memory.correct` | Corrigir conteúdo (substitui seção; anterior vai ao histórico) | `target_id`, `change` com `mode: replace`, `reason` |
| `memory.relate` | Criar/remover relações | `target_id`, `relations`, `remove_relations`, `reason` |
| `memory.update_meta` | Metadados, lacunas, marcos, bloqueios | `meta`, `add_gaps`, `resolve_gaps`, `milestones`, `blockers` |
| `memory.rename` / `memory.move` | Renomear / mover (links atualizados) | `new_title` / `new_path` |
| `memory.archive` | Arquivar (pede confirmação) | `target_id`, `reason` |
| `memory.delete` | Excluir (só se habilitado; sempre confirma) | `target_id`, `reason` |

Campos comuns: `request_id` (único por pedido — ver [conventions](conventions.md)), `expected_revision`
(a `revision` lida no `read`; protege contra alteração concorrente), `classification`, `source`
(`type`: `user`, `meeting`, `document`, `agent_inference`, `import`; `original_text` com a frase do
usuário), `confirmed`.

`change`: `section` (nome da seção do template; ver [conventions](conventions.md)), `content`,
`mode` (`merge` padrão — não duplica; `append`; `replace`), `certainty` (`fact` | `hypothesis`),
`replaces` (frase atual que deixa de valer).

### Exemplo — nova informação em nota existente

```json
{
  "request_id": "req-20261020-abc-def",
  "operation": "memory.upsert",
  "target_id": "<id do domínio>",
  "expected_revision": "<revision do read>",
  "classification": {"level": "high", "reason": "ABC é alias registrado no domínio"},
  "change": {"section": "Integrações", "content": "ABC utiliza o DEF para validação."},
  "source": {"type": "user", "original_text": "Anota que o ABC agora utiliza o DEF para validação."}
}
```

### Exemplo — nova nota após o usuário informar o contexto

```json
{
  "request_id": "req-20261020-fin-veic",
  "operation": "memory.create",
  "classification": {"level": "high", "reason": "usuário informou o domínio"},
  "note": {"type": "domain", "title": "Financiamento de Veículos", "entities": ["ABC"]},
  "change": {"section": "Sistemas e serviços", "content": "ABC realiza simulações de financiamento."},
  "source": {"type": "user", "original_text": "Anota que ABC faz simulação de financiamento."}
}
```

## Duplicação

Se o conteúdo já está na seção, `merge` não altera o arquivo e registra só a nova evidência
(`duplicate: true`). Diga ao usuário que a informação **já estava registrada**. Equivalência semântica
com palavras diferentes é decisão sua: leia a nota e, se for o mesmo fato, não reenvie.

## Contradições e mudanças

O plano traz `contradictions` (e a confirmação `possible_contradiction`) quando a frase nova contradiz
o estado atual. `temporal: true` sugere mudança no tempo ("não usa **mais**"). Faça assim:

- Mudança real ("ABC não consulta mais XYZ") → `change` com `replaces: "ABC consulta XYZ."` e o
  conteúdo novo: o estado vigente é atualizado e o antigo vai para `## Histórico`.
- Não está claro se é correção ou mudança, ou se contraria decisão vigente → pergunte (Tipo A).
- Correção de classificação ("ABC não é sistema, é serviço") → `replaces` com a frase antiga ou
  `memory.correct` na seção; a nova versão vale nas próximas consultas.

## Hipóteses e inferências

- "Acho que o problema é o XYZ" → registre o problema como fato relatado e a causa com
  `certainty: hypothesis`. Nunca grave "a lentidão é causada pelo XYZ".
- Para confirmar depois: `replaces` com o texto da hipótese e `certainty: fact`.
- Conclusões suas → `source.type: agent_inference` (o Core marca como não confirmadas).

## Decisões (ADR)

Decisão arquitetural → `memory.create` com `note.type: architecture_decision` (o número ADR é
automático), `extra.status` (`proposed`/`accepted`/…), `extra.decision_date` se informada, seções
`Contexto`, `Decisão`, `Justificativa`, `Alternativas consideradas`, `Consequências`. Relacione à
reunião com `decided_in`. Nova decisão que substitui outra: `extra.supersedes: [<id antigo>]` (o Core
marca a anterior como `superseded` e pede `supersede_decision`). Sem justificativa: registre e pergunte
o motivo uma vez; se o usuário não souber, `add_gaps` com `field: decision_reason`, `status: deferred`.

## Projetos, pessoas e times

- Marcos/entregas: `milestones: [{kind, title, due_date, status}]` (mudança de data preserva histórico).
- Bloqueios: `blockers: [{description, status: "open"}]`; resolver: `{description|id, status: "resolved", resolution}`.
  O Core avisa sobre status x bloqueios mas não muda o status do projeto: mude só se o usuário disser.
- Participação: `memberships: [{action: "start"|"end", kind: "project"|"team", target_id, role, on}]` na nota
  da **pessoa**. "João começou no Orion" não encerra o Atlas — pergunte se ele continua lá.
- Responsável: relação `owned_by` (do assunto para a pessoa/time). Troca de responsável: `remove_relations`
  do antigo + `relations` do novo, com `reason`.

## Relações tipadas

| Tipo | De → para |
|---|---|
| `related_to` | qualquer nota → qualquer nota |
| `depends_on`, `blocks` | domínio/projeto/arquitetura/ADR → domínio/projeto/arquitetura/ADR |
| `owned_by` | domínio/projeto/arquitetura/ADR → pessoa/time |
| `participates_in` | pessoa/time → projeto/reunião/domínio/arquitetura |
| `discussed_in` | qualquer nota (exceto reunião) → reunião |
| `decided_in` | domínio/projeto/arquitetura/ADR → reunião |
| `supersedes` | nota → nota do mesmo tipo |
| `part_of` | pessoa → time; time → time/domínio/projeto; domínio → domínio; projeto → projeto/domínio; arquitetura/ADR → arquitetura/domínio/projeto; reunião → projeto |

Combinação inválida → `VALIDATION_ERROR` com `allowed_targets`: escolha outro tipo ou `related_to`.

## Inbox (captura provisória)

Sem contexto e o usuário não quer responder agora: `inbox add --text "<texto original>" --entity ABC
--question "A qual domínio o ABC pertence?"`. Diga que ficou guardado sem classificação. Depois:
`inbox list`, e `inbox classify <id> --proposal -` (proposta completa) ou `--target <id>`, ou
`inbox discard <id>`.

## Lacunas de conhecimento

`suggested_gaps` no plano/resultado indicam o que enriqueceria o registro (já filtradas: nunca repetem
o que está registrado, adiado ou resolvido). Use no máximo uma, como pergunta Tipo B. Quando o usuário
adia ou não sabe: `memory.update_meta` com `add_gaps: [{field, question, status: "deferred", priority}]`.
Quando responde depois: grave a resposta e `resolve_gaps: [{gap: "<field ou id>", answer}]`. Lacuna
não é tarefa: não crie pendência para ela.

## Confirmações

| Motivo (`reasons`) | Pergunta típica |
|---|---|
| `new_topic` | "Crio um novo registro para X em <módulo>?" |
| `possible_duplicate` | "Já existe 'Y'. É o mesmo assunto/tarefa?" (se sim, atualize o existente) |
| `conflicting_update` | "Isso substitui o que está registrado (…). Confirma a correção?" |
| `possible_contradiction` | "Antes estava registrado que … . Isso mudou ou é uma correção?" |
| `supersede_decision` | "Essa decisão substitui a ADR-000N?" |
| `archive` / `destructive` | "Confirma arquivar/excluir X? O histórico Git mantém versões anteriores." |
| `medium_confidence` / `low_confidence` | Mostre os candidatos e pergunte qual é o destino |
| `sensitive_content` | "Isso parece pessoal/sensível. Quer mesmo registrar?" |
| `conservative_mode` | O repositório pede confirmação para tudo: resuma a alteração e pergunte |
| `ambiguous_date` | Mostre as `alternatives` e pergunte qual data |
| `schedule_conflict` | "Conflita com … às HHh. Marco mesmo assim?" |
| `missing_time` | "Qual horário?" (ou `all_day: true` se for o dia todo) |
| `repeats_completed_task` | "Já existe essa tarefa concluída. É uma nova execução?" (se sim, `related_ids` com a antiga) |
| `reopen_completed_task` | "A tarefa está concluída. Reabro?" |

Com o "sim", reenvie com `"confirmed": true`. Com "não", ajuste (outro destino, atualizar o existente)
ou desista — e diga que nada foi gravado.
