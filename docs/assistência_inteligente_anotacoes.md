# ContextVault — Assistência Inteligente às Anotações

**Versão:** 1.0  
**Módulo:** Captura assistida e enriquecimento contextual  
**Prioridade:** Obrigatória  
**Aplicação:** Todos os módulos do ContextVault

---

## 1. Objetivo

O ContextVault não deve funcionar apenas como um sistema de armazenamento de anotações.

Ele deve atuar como um **assistente inteligente de conhecimento**, capaz de identificar informações incompletas, reconhecer ambiguidades, aproveitar o contexto existente e ajudar o usuário a produzir registros mais úteis.

A IA deve colaborar ativamente com o usuário, fazendo perguntas quando necessário, mas sem transformar o processo de anotação em um formulário ou interrogatório.

**Princípio central:**

> A IA deve ajudar o usuário a registrar informações melhores, fazendo o mínimo de perguntas necessário e preservando tudo o que já foi informado.

---

## 2. Regras obrigatórias de comportamento

### Regra 1 — Perguntas obrigatórias somente quando necessário

A IA deve fazer perguntas obrigatórias apenas quando uma ambiguidade impedir uma classificação ou alteração segura.

Exemplos:

**Usuário:**

> O João assumiu a integração ABC.

**Contexto existente:** existem João Silva e João Pereira.

**Resposta esperada:**

> Você está falando do João Silva ou do João Pereira?

A IA não deve escolher arbitrariamente uma pessoa.

Outro exemplo:

**Usuário:**

> O ABC não utiliza mais aquele serviço.

**Resposta esperada:**

> Você está se referindo ao XYZ ou ao DEF?

Se a informação puder ser armazenada com segurança sem esclarecimento, a IA não deve interromper desnecessariamente.

### Regra 2 — Perguntas de enriquecimento contextual

A IA deve identificar quando uma informação adicional aumentaria significativamente o valor futuro da anotação.

Exemplos de informações importantes:

- Justificativa de uma decisão.
- Responsável por uma ação.
- Motivo de um impedimento.
- Contexto de um problema.
- Consequência de uma alteração.
- Relação entre sistemas.
- Critério de conclusão de uma entrega.

**Usuário:**

> Decidimos migrar o ABC para comunicação assíncrona.

**Resposta esperada:**

> Posso registrar essa decisão. Qual foi o principal motivo da mudança?

**Usuário:**

> Reduzir o acoplamento com o XYZ.

**Resultado esperado:**

Registrar a decisão e sua justificativa.

Caso o usuário não saiba responder, registrar a decisão com justificativa não informada.

**Importante:** perguntas de enriquecimento são opcionais e não devem impedir a captura de informações suficientes.

### Regra 3 — Fazer uma pergunta por vez

Quando existirem várias informações ausentes, a IA deve priorizar a pergunta de maior impacto.

**Usuário:**

> O João vai cuidar da documentação do ABC.

Possíveis lacunas:

- Qual João?
- Qual atividade?
- Qual prazo?
- Qual prioridade?
- Qual projeto?

A IA não deve apresentar todas essas perguntas simultaneamente.

Se João já estiver identificado, a primeira pergunta poderá ser:

> Ele vai criar o repositório, escrever a documentação ou cuidar de todo o processo?

Depois da resposta, a IA deve reavaliar se realmente precisa perguntar mais alguma coisa.

Não perguntar por prazo ou prioridade apenas para preencher campos opcionais.

### Regra 4 — Nunca bloquear desnecessariamente a captura

O usuário deve poder responder:

- "Não sei."
- "Depois eu vejo."
- "Só anota."
- "Ainda não foi definido."
- "Não precisa perguntar."
- "Deixa em aberto."

Nessas situações, o ContextVault deve registrar as informações disponíveis e preservar as lacunas.

**Exemplo:**

Usuário:

> Decidimos adiar a migração do ABC.

IA:

> Qual foi o motivo do adiamento?

Usuário:

> Não lembro agora, só anota.

**Comportamento esperado:**

- Registrar o adiamento.
- Marcar justificativa como não informada.
- Preservar a anotação original.
- Não insistir na pergunta.
- Não inventar uma justificativa.

Se a ambiguidade impedir uma alteração segura, o sistema poderá salvar a informação provisoriamente na inbox, sem realizar a alteração arriscada.

### Regra 5 — Utilizar o conhecimento existente

Antes de perguntar, a IA deve consultar o ContextVault.

Ela deve verificar:

- Pessoas cadastradas.
- Projetos existentes.
- Sistemas conhecidos.
- Responsabilidades atuais.
- Decisões anteriores.
- Reuniões relacionadas.
- Tarefas abertas.
- Histórico de alterações.
- Aliases e relacionamentos.

**Exemplo:**

O ContextVault já sabe que:

- ABC é um serviço de financiamento de veículos.
- João Silva é responsável pela integração ABC.
- XYZ é uma dependência do ABC.

**Usuário:**

> João precisa validar a integração do ABC até sexta.

**Comportamento esperado:**

- Identificar João Silva quando a correspondência for inequívoca.
- Identificar ABC.
- Relacionar a tarefa à integração existente.
- Resolver a data.
- Criar ou atualizar a pendência.

**Não deve perguntar:**

> Quem é João?

> O que é ABC?

> A qual domínio pertence ABC?

Essas informações já estão disponíveis.

### Regra 6 — Nunca inventar informações ausentes

A IA deve diferenciar:

- Informação confirmada.
- Informação relatada.
- Hipótese.
- Sugestão.
- Inferência.
- Informação desconhecida.

**Usuário:**

> O ABC está lento. Acho que o problema pode ser o XYZ.

**Registro esperado:**

**Problema relatado:** lentidão no ABC.

**Hipótese:** a integração com XYZ pode estar relacionada à lentidão.

**Causa confirmada:** não informada.

A IA não deve registrar:

> A lentidão do ABC é causada pelo XYZ.

Da mesma forma, não deve inventar:

- Prazos.
- Responsáveis.
- Cargos.
- Equipes.
- Tecnologias.
- Decisões.
- Justificativas.
- Conclusões.

Campos desconhecidos devem permanecer vazios ou explicitamente identificados como não informados.

### Regra 7 — Aprender com correções registradas

Quando o usuário corrigir uma informação, o ContextVault deve atualizar o conhecimento persistido e utilizar a informação corrigida nas interações futuras.

**Primeira interação:**

Usuário:

> O ABC faz simulações de financiamento.

IA:

> O ABC é um sistema, serviço ou módulo?

Usuário:

> É um serviço.

**Resultado:**

O ContextVault registra que ABC é um serviço.

**Interação posterior:**

Usuário:

> O ABC vai receber uma nova integração.

A IA deve reconhecer ABC como serviço sem repetir a pergunta anterior.

**Correção posterior:**

Usuário:

> Na verdade, o ABC é um módulo do sistema Financeiro, não um serviço independente.

**Comportamento esperado:**

- Identificar contradição.
- Confirmar a correção quando necessário.
- Atualizar a classificação vigente.
- Preservar histórico.
- Utilizar a nova classificação nas consultas futuras.

Esse aprendizado deve ocorrer por meio dos registros persistidos, e não depender exclusivamente do histórico da conversa ou da memória nativa de um fornecedor de IA.

---

## 3. Fluxo obrigatório de captura assistida

Para cada mensagem com intenção de anotação, executar:

1. **Interpretar:** identificar fatos, ações, decisões, problemas, pessoas e assuntos.
2. **Consultar:** recuperar conhecimento existente relevante.
3. **Comparar:** detectar registros equivalentes, informações novas e contradições.
4. **Avaliar lacunas:** determinar quais informações estão faltando.
5. **Priorizar:** distinguir lacunas obrigatórias de oportunidades de enriquecimento.
6. **Decidir:** registrar, perguntar, atualizar ou capturar provisoriamente.
7. **Persistir:** executar as operações por meio do Core.
8. **Confirmar:** informar o que foi realmente salvo.
9. **Enriquecer:** quando apropriado, fazer uma pergunta opcional de alto valor.

A IA não deve perguntar primeiro e consultar a memória depois.

---

## 4. Classificação das perguntas

### Tipo A — Obrigatória

Usar quando a resposta for necessária para evitar uma operação incorreta.

Exemplos:

- Dois profissionais com o mesmo nome.
- Duas tarefas semelhantes que poderiam ser atualizadas.
- Referência ambígua a um projeto.
- Alteração que contradiz uma decisão vigente.
- Exclusão de informação importante.

**Comportamento:** aguardar esclarecimento antes da operação ambígua.

### Tipo B — Enriquecimento

Usar quando a resposta melhorar significativamente o registro.

Exemplos:

- Por que uma decisão foi tomada?
- Qual foi a causa de um impedimento?
- Qual resultado se espera de uma atividade?
- Qual foi a consequência de uma mudança?

**Comportamento:** registrar as informações seguras e perguntar de maneira opcional.

### Tipo C — Desnecessária

Perguntas que apenas preencheriam campos opcionais sem benefício imediato.

Exemplos:

- Qual a prioridade de uma tarefa simples?
- Qual o sobrenome de uma pessoa provisória, quando não existe ambiguidade?
- Qual a duração de uma reunião já registrada como compromisso sem duração?
- Qual a tecnologia utilizada, quando isso não foi mencionado nem é necessário?

**Comportamento:** não perguntar.

---

## 5. Política de prioridade das perguntas

Quando houver múltiplas lacunas, priorizar:

1. Identificação correta de entidades.
2. Prevenção de alteração incorreta ou duplicação.
3. Esclarecimento de decisão ou responsabilidade ambígua.
4. Justificativa de decisões relevantes.
5. Identificação de ação concreta.
6. Contexto de problemas e impedimentos.
7. Informações complementares opcionais.

Essa ordem é orientativa. O contexto e o risco da operação devem prevalecer.

**Limite padrão:** uma pergunta por resposta do agente.

---

## 6. Exemplos de comportamento esperado

### Exemplo A — Anotação suficiente

**Usuário:**

> João precisa criar o repositório de documentação ABC até sexta.

**Esperado:**

- Buscar João.
- Buscar tarefa equivalente.
- Identificar ABC.
- Registrar ou atualizar tarefa.
- Resolver prazo no fuso configurado.
- Confirmar gravação.

Não perguntar por informações opcionais.

### Exemplo B — Anotação que pode ser enriquecida

**Usuário:**

> Decidimos não migrar o ABC.

**Esperado:**

- Identificar decisão.
- Verificar decisões existentes.
- Registrar o que for seguro.
- Perguntar:

> Qual foi o principal motivo para não migrar?

Se o usuário não responder, preservar a decisão sem justificativa.

### Exemplo C — Responsabilidade incompleta

**Usuário:**

> João ficou responsável pela documentação do ABC.

**Esperado:**

- Identificar João.
- Identificar ABC.
- Verificar tarefas existentes.
- Perguntar:

> Ele ficou responsável por criar o repositório, escrever a documentação ou ambos?

Não criar automaticamente duas tarefas.

### Exemplo D — Mudança de projeto

**Estado existente:** João participa do Atlas.

**Usuário:**

> João começou a trabalhar no Orion.

**Esperado:**

- Registrar nova participação quando seguro.
- Não encerrar Atlas automaticamente.
- Perguntar, se relevante:

> Ele continuará no Atlas também ou está deixando o projeto?

### Exemplo E — Problema sem responsável

**Usuário:**

> Nossas aplicações modernizadas estão sem documentação.

**Esperado:**

- Registrar como problema relatado.
- Não inventar responsável.
- Não criar tarefas específicas sem ações definidas.
- Poder perguntar opcionalmente:

> Existe alguma iniciativa em andamento para resolver isso?

Se a resposta for negativa ou desconhecida, manter o problema registrado.

### Exemplo F — Captura composta

**Usuário:**

> Pedi para João criar o repositório ABC porque estou sem acesso ao GitHub. Maria vai escrever a documentação depois.

**Esperado:**

- Buscar ou identificar João.
- Criar ou atualizar tarefa de criação do repositório.
- Registrar o contexto do acesso ao GitHub.
- Identificar Maria.
- Criar tarefa de escrita da documentação, se for uma ação efetivamente atribuída.
- Registrar dependência temporal entre as ações quando a mensagem sustentar essa relação.
- Não inventar prazo.
- Não duplicar tarefas.

Perguntar apenas se houver ambiguidade relevante.

### Exemplo G — Usuário não quer perguntas

**Usuário:**

> Anota que precisamos rever a arquitetura do ABC. Não quero detalhar agora.

**Esperado:**

- Registrar a necessidade de revisão.
- Utilizar assunto existente, se identificado.
- Preservar lacunas.
- Não fazer perguntas de enriquecimento nessa interação.

### Exemplo H — Correção aprendida

**Usuário:**

> ABC não é um sistema, é um serviço.

**Esperado:**

- Identificar nota existente.
- Corrigir classificação.
- Preservar histórico.
- Não repetir o erro em consultas posteriores.

---

## 7. Regras para não incomodar o usuário

A IA não deve:

- Perguntar o que já sabe.
- Fazer perguntas em sequência sem necessidade.
- Exigir preenchimento de todos os campos.
- Bloquear anotações simples.
- Repetir uma pergunta que o usuário decidiu adiar.
- Transformar hipóteses em fatos.
- Criar tarefas apenas porque existe um problema.
- Inventar responsáveis ou prazos.
- Solicitar confirmação para toda atualização segura de uma nota existente.

A IA deve:

- Fazer perguntas curtas e específicas.
- Explicar ambiguidades quando necessário.
- Aceitar respostas incompletas.
- Preservar informações provisórias.
- Retomar lacunas somente quando forem relevantes.
- Utilizar conhecimento existente.
- Respeitar a preferência expressa pelo usuário na interação.

---

## 8. Tratamento de informações pendentes

Quando uma pergunta opcional não for respondida, o ContextVault poderá registrar uma lacuna estruturada.

Exemplo:

```yaml
knowledge_gaps:
  - field: decision_reason
    status: unknown
    question: Qual foi o motivo da decisão?
    priority: medium
```

Essas lacunas devem ser associadas ao registro original.

Não criar automaticamente uma pendência operacional para cada lacuna de conhecimento.

Uma lacuna de conhecimento e uma tarefa são conceitos diferentes.

O usuário poderá perguntar:

> Quais informações ainda precisamos esclarecer sobre o ABC?

O ContextVault deverá recuperar as lacunas relevantes.

---

## 9. Critérios de aceite

A funcionalidade estará aprovada quando:

1. A IA fizer perguntas obrigatórias diante de ambiguidades reais.
2. Não fizer perguntas desnecessárias quando já possuir contexto.
3. Fizer perguntas de enriquecimento relevantes.
4. Respeitar o limite padrão de uma pergunta por vez.
5. Permitir "não sei", "depois" e "só anota".
6. Preservar informações mesmo quando incompletas.
7. Não inventar campos ausentes.
8. Reutilizar conhecimento persistido.
9. Aprender com correções armazenadas.
10. Não depender da conversa atual para recuperar correções anteriores.
11. Evitar duplicação de pessoas, tarefas e assuntos.
12. Não declarar sucesso sem persistência confirmada.
13. Distinguir perguntas obrigatórias de opcionais.
14. Não insistir em perguntas adiadas sem nova necessidade.
15. Manter a captura fluida e natural.

---

## 10. Instrução para implementação

Implemente a funcionalidade **Assistência Inteligente às Anotações** na skill ContextVault e integre-a aos fluxos existentes de classificação, captura, atualização e recuperação.

Essa funcionalidade deve operar em todos os módulos:

- `dominios/`
- `projetos/`
- `arquitetura/`
- `pessoas-times/`
- `reunioes/`
- `agenda/`
- `pendencias/`

Também deve utilizar o `INDEX.md`, os relacionamentos e o histórico persistido.

A implementação deve distinguir claramente:

- Perguntas obrigatórias.
- Perguntas opcionais de enriquecimento.
- Informações que podem ser registradas imediatamente.
- Informações que exigem confirmação.
- Informações que devem permanecer provisórias.

Adicione testes automatizados e cenários de aceitação para verificar todos os comportamentos descritos.

**Resultado esperado:** o ContextVault deve se comportar como um assistente que ajuda o usuário a pensar e registrar melhor, sem exigir que ele preencha formulários, repita informações ou conheça a estrutura interna da memória.

**Fim da especificação.**
