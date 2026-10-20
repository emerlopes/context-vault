# Recuperação de conhecimento

Responder perguntas **apenas** com o que está registrado, citando as fontes.

## Comandos

| Comando | Para quê |
|---|---|
| `search "<texto>" [--type T] [--kind note\|task\|appointment\|inbox\|journal] [-n N]` | Busca híbrida (título, alias, entidade, conteúdo, relações, agenda, pendências, diário) com `score`, `reasons` e trechos |
| `resolve "<nome>" [--type person]` | Identifica exatamente um registro; homônimos/siglas ambíguas → `AMBIGUOUS_MATCH` com `candidates` |
| `read <id\|prefixo\|caminho> [--history]` | Nota completa, relações, backlinks, pendências, compromissos, `unconfirmed`; `--history` traz commits e eventos |
| `context "<assunto>" [--depth N] [--since P]` | "Tudo que sabemos sobre X": síntese por categoria com `sources` e `empty_categories`; `--since "esta semana"` acrescenta `changes` (o que mudou no período) |
| `related <id> [--depth 1-5] [--type T] [--kind K] [--direction in\|out\|both] [--current]` | Navegação no grafo nos dois sentidos |
| `gaps list [<ref>]` | O que ainda falta esclarecer |
| `journal list [--date D \| --period P \| --all] [--target ID]` | Eventos registrados (o que mudou) |
| `projects list\|milestones\|blockers` | Status, marcos/entregas e bloqueios |

## Procedimento

1. Identifique entidades e intenção da pergunta.
2. `resolve`/`search` para achar o registro; `read` das melhores fontes (não responda só pelo trecho
   da busca quando o detalhe importa).
3. Se precisar de vínculos: `related` ou `context`.
4. Avalie datas e status: o estado vigente vem primeiro; itens arquivados, substituídos ou em
   `## Histórico` são passado.
5. Verifique divergências e hipóteses (`unconfirmed`, `responsibility.divergent`).
6. Responda e cite os arquivos (`path`/`sources`).

## Formato da resposta

> ABC é o serviço responsável pela simulação de financiamento de veículos, no domínio de
> Financiamento de Veículos.
>
> Fonte: `dominios/financiamento-veiculos.md`

- Nada encontrado (`NOT_FOUND`, busca vazia, `context` com `found: false`):
  **"Não encontrei essa informação no ContextVault."** Ofereça registrar, se fizer sentido.
- Encontrou só menções sem registro próprio: diga isso e mostre onde aparece.
- Hipóteses: "Há uma hipótese registrada (não confirmada) de que …".
- Mudanças: "Antes … ; desde <data> … (fonte)".
- Responsáveis divergentes: apresente cada afirmação com sua fonte e pergunte qual vale, se o usuário
  quiser corrigir.
- Decisões: "Por que decidimos X?" → ADR (`Decisão`, `Justificativa`) ou seção `Decisões` de reunião;
  se não houver justificativa registrada, diga que ela não foi informada.

## "Tudo sobre X"

`context X` agrupa: definição/estado atual, domínios, sistemas, integrações, projetos, decisões
(vigentes x anteriores x de reuniões), pessoas e times (atuais x anteriores), reuniões, agenda futura,
pendências abertas, bloqueios, marcos, lacunas e histórico. Monte a síntese **só com as categorias que
têm conteúdo**; se for útil, diga quais não têm registro (`empty_categories`). Termine com as fontes.

## "O que mudou em X nesta semana?"

`context X --since "esta semana"` (ou `hoje`, `ontem`, `AAAA-MM-DD` = daquele dia até hoje) devolve
`changes.events` — eventos do diário sobre X e seus vizinhos no período, em ordem, cada um com
`categories` (`decisions`, `risks`, `tasks`, `blockers`, `milestones`, `meetings`, `agenda`, `people`,
`status`, `updates`…), `summary`, `sections`, `source` e `path` — e `changes.by_category`. Resuma
separando decisões, riscos e pendências e cite as fontes. Sem eventos: `changes.notice` — diga que nada
foi registrado no período (não invente mudanças).

## Briefings

- "Me prepara para a reunião (do Atlas / de amanhã)" → `meetings brief [ref] [--date D]`.
- "O que tenho hoje/amanhã?" → `daily brief [--date amanhã]`.

Ambos devolvem `recorded` (fatos com fontes) e `suggestions` (perguntas e pontos de atenção derivados,
cada um com `basis`). Apresente em blocos separados: "Registrado" e "Sugestões para preparar". Nunca
transforme pauta em decisão. Se `selected_by: next`, confirme se é a reunião que o usuário queria.
