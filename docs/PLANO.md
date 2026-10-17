# Plano de desenvolvimento — Motor Antifraude Pix

Oct 17, 2026 · @Thomaz

O plano entrega até domingo, 18/10, às 12h um motor antifraude Pix que decide pelo tipo de fraude, enxerga a rede de contas a partir do próprio histórico e combina regras explicáveis com um modelo de Machine Learning que sinaliza o que as regras ainda não conhecem, sem prejudicar o cliente legítimo nem atrasar o Pix.

## A proposta

O motor responde duas perguntas antes de decidir: quem está apertando o botão e para onde vai o dinheiro. O critério que mais pesa é a profundidade antifraude, e o motor responde a ele com três compromissos ao mesmo tempo: pegar a fraude real, não prejudicar o cliente legítimo e não atrasar o Pix. A maioria dos grupos vai otimizar só o primeiro e entregar um motor de limites que barra a fraude e o cliente bom do mesmo jeito.

1. **Decisão pelo tipo de fraude.** Sinais de conta invadida levam a `two_factor_required`, porque o invasor não tem o segundo fator. Sinais de golpe e de conta laranja levam a `rejected`, porque a vítima manipulada passa no 2FA. O relatório conjunto da EBA e do BCE de 2025 sustenta essa divisão.
2. **O mesmo sinal muda de sentido com o contexto.** Valor alto, de aparelho conhecido, para um destino recorrente é o aluguel. O mesmo valor para um destino novo é risco de golpe. De um aparelho novo, é risco de invasão. Cada contexto tem a sua resposta.
3. **Erros reais previstos dos dois lados.** O motor é desenhado contra a fraude que passa e contra o cliente bom barrado. Cada caso real de fronteira, como aluguel, viagem, celular novo, racha de conta e lojista, vira cenário de teste com a resposta esperada.
4. **Esforço proporcional ao risco.** O Pix rotineiro sai pelo caminho rápido. Regras de rede e ML só entram quando aparece sinal de risco. A meta do grupo é p95 abaixo de 100 ms no caminho rápido.
5. **Quatro níveis de resposta em três status.** Além de aprovar, pedir 2FA e recusar, o motor aprova com aviso (`recommended_action: warn`) nos casos de golpe com sinal fraco, como o Alerta Pix do Itaú faz hoje.
6. **A rede vista do próprio histórico.** Como o banco guarda tudo o que chegou, o motor calcula sinais que só bancos grandes usam: aparelho compartilhado, muitos pagadores para uma conta, dinheiro que entra e sai em minutos e proximidade de conta marcada.
7. **Regras explicáveis com ML que pega o desconhecido.** As regras cobrem os padrões conhecidos, cada uma com um porquê citável. Um modelo de detecção de anomalia, treinado só com comportamento normal, sinaliza padrões que nenhuma regra descreve.
8. **Auditável e reproduzível.** Cada análise grava a versão da política, os valores observados, os limites usados e um hash encadeado com a análise anterior do mesmo pagador. Isso responde ao STJ, que em 2026 ligou a responsabilidade do banco à detecção de transação incompatível com o perfil.

Todos os parâmetros com origem regulatória são citados. Os demais são estimativas declaradas no README, configuráveis numa tabela versionada.

## Profundidade antifraude: contexto e erros reais

Profundidade, aqui, é o motor saber que o mesmo sinal significa coisas diferentes e prever os dois erros que custam caro: deixar a fraude passar e barrar o cliente bom.

**Polimorfismo no código.** Toda regra implementa a mesma interface, `evaluate(features, params, camada) → list[SignalResult]`, e o motor só conhece essa interface. Regra nova é uma classe nova e uma linha de parâmetro, sem mexer no motor. Cada tipologia (invasão, golpe, conta laranja) tem a sua estratégia de resposta, também atrás de uma interface comum. É o padrão Strategy, que também conta no critério de padrão de código.

**Polimorfismo na política.** O mesmo sinal pesa diferente conforme o contexto:

| Sinal | Contexto | Leitura | Resposta |
| --- | --- | --- | --- |
| Valor 5× a mediana do pagador | Aparelho conhecido, destino recorrente | Conta do mês: aluguel, escola | Aprova |
| Valor 5× a mediana do pagador | Aparelho conhecido, destino novo | Possível golpe, com a vítima autenticada | Aviso ou recusa, conforme a conta destino |
| Valor 5× a mediana do pagador | Aparelho novo ou fora da zona habitual | Possível invasão | 2FA |
| Muitos pagadores para uma conta | Recebedor PJ | Lojista | Não pontua |
| Muitos pagadores para uma conta | Recebedor PF com conta recente | Conta laranja | Recusa |
| Dinheiro entra e sai em minutos | Mesma titularidade | Cliente movendo o próprio saldo | Aprova |
| Dinheiro entra e sai em minutos | De terceiros para terceiros | Conta de passagem | Recusa |

**Matriz de erros reais.** Cada linha é um caso que acontece todo dia. As oito primeiras são clientes bons que um motor simples barraria; as cinco últimas são fraudes que um motor simples deixaria passar.

| Caso real | Erro de um motor simples | Como o nosso motor evita |
| --- | --- | --- |
| Aluguel de R$ 2.500 todo dia 5 | Recusa por valor fora do perfil | Destino já pago antes pelo pagador atenua o sinal de perfil (Regra 4) |
| Primeiro Pix do celular comprado ontem | Recusa por aparelho novo | Pede 2FA, que equivale ao cadastro do aparelho previsto pelo BCB; depois de aprovado, o aparelho vira conhecido |
| Viagem de férias | Recusa por localização | A zona habitual (Regra 5) pede 2FA e nunca recusa; viagem impossível só acima de 900 km/h |
| Racha da conta do bar: 6 Pix pequenos em 5 minutos | 2FA por velocidade | O sinal de velocidade (Regra 3) combina contagem com soma; rajada de valor baixo pesa menos |
| Lojista recebendo de 50 clientes por hora | Recusa por fan-in | O sinal de muitos pagadores (Regra 6) só vale para recebedor pessoa física |
| Salário que entra e vai para o investimento | Recusa por dinheiro em trânsito | O contexto de mesma titularidade tira o caso do sinal de repasse (Regra 7) |
| Cliente novo, sem histórico, pagando R$ 800 | 2FA por falta de perfil | Limite de partida ancorado no Pix médio entre pessoas (R$ 273) e no ticket médio de fraude (R$ 1.735) |
| Emergência às 23h acima de R$ 1.000 | Recusa pelo limite padrão, mesmo que o cliente tenha aumentado o próprio limite | O sinal noturno (Regra 2) compara com o histórico noturno do próprio pagador; fora dele, pede 2FA em vez de recusar |
| Falsa central: cliente no próprio celular | Aprova porque a autenticação está certa | O placar de golpe olha destino novo, valor fora do perfil e a conta destino; recusa com `hold_timer` |
| Conta laranja antiga e alugada | Aprova porque a conta tem anos | Os sinais de conta dormente (Regra 6) e de repasse rápido (Regra 7) olham comportamento, não idade |
| Fraudador que sobe valores aos poucos | Aprova porque o valor "virou perfil" | O perfil só usa Pix aprovados, e as tentativas recusadas contam na velocidade |
| Fracionamento em Pix de R$ 199 | Aprova cada um, abaixo do teto | Limites cumulativos da Regra 2 e o sinal de fracionamento da Regra 3 |
| Padrão nunca visto: Pix de centavos para muitos destinos | Nenhuma regra dispara | O modelo de anomalia sinaliza |

Cada linha vira um cenário do simulador e um teste HTTP com a resposta esperada. Na apresentação, a tabela aparece com o resultado real de cada caso.

## Esforço proporcional ao risco

Um Pix rotineiro não paga o custo de um Pix suspeito. O motor avalia em camadas e só aprofunda quando a camada anterior levanta sinal; sem sinal, aprova pelo caminho rápido.

| Camada | Quando roda | Regras | Custo |
| --- | --- | --- | --- |
| 0 — Obrigatória | Sempre; nunca é pulada | Regra 1; contexto de mesma titularidade; Regra 2 (aparelho não cadastrado, horário noturno); Regra 3 (velocidade) | Buscas por chave e contagens indexadas |
| 1 — Perfil | Sempre | Regra 2 (sem geolocalização); Regra 4; Regra 5 (viagem impossível); Regra 6 (conta nova, muitos pagadores) | Leituras diretas em tabelas agregadas |
| 2 — Profunda | Só com sinal: destino novo, valor fora do perfil, aparelho novo, conta destino recente ou horário atípico | Regra 3 (fracionamento); Regra 5 (aparelho compartilhado, zona habitual); Regra 6 (conta dormente, várias instituições); Regra 7; Regra 8 (ML) | Consultas de rede, consulta recursiva de saltos e inferência do modelo |

**Tabelas agregadas.** O perfil do pagador, os pares pagador-recebedor já vistos e os aparelhos de cada CPF são atualizados no mesmo commit de cada Pix. O motor grava um pouco mais em cada Pix e lê muito menos, em vez de recalcular 90 dias de histórico a cada requisição.

**Orçamento de tempo.** Os 40 segundos do SPI são o limite de ponta a ponta, e os cerca de 2 segundos que o cliente percebe incluem app, autenticação e rede. O antifraude é uma etapa dentro disso. A meta do grupo é p95 abaixo de 100 ms no caminho rápido, na linha do que o mercado busca para pontuar uma transação.

**Tempo limite com decisão segura.** Se a camada 2 passar de 300 ms (estimativa do grupo), o motor decide com o que já tem. Como ela só roda quando já havia sinal de risco, a decisão é pedir 2FA, nunca aprovar no escuro.

**Transparência.** O `metadata` traz `path: fast` ou `path: deep` e as camadas executadas. Uma regra que não precisou rodar aparece como `not_needed`, separada de `not_evaluated`, que é regra sem dado.

**Concorrência sem fila geral.** A trava só segura Pix que disputam a mesma contagem: mesmo pagador, mesmo recebedor pessoa física ou mesmo aparelho. Todo o resto segue em paralelo. Quem dispara dez Pix ao mesmo tempo, ou dez vítimas pagando a mesma conta, é justamente o caso suspeito, e nele a fila é o que garante a contagem certa.

**O que o simulador mede.** O percentual de Pix no caminho rápido, a latência p50, p95 e p99 de cada caminho, a taxa de 2FA e de recusa em clientes legítimos e a fraude pega por tipologia. A taxa de base justifica o cuidado: com cerca de 6,7 fraudes a cada 100 mil Pix, cada 1% de 2FA desnecessário incomoda uns 150 clientes bons para cada fraude.

## Linha do tempo

&#91;embedded content: linha do tempo · 6 fases e seus portões\]

A Fase 2 é o ponto de segurança: se algo der errado depois dela, o grupo já tem um motor completo para entregar. A Fase 4 começa junto com a Fase 2, tocada por uma pessoa só.

## Fase 0 — Alinhamento e repositório (sáb 13h30–14h30)

A fase termina com o escopo fechado e o repositório rodando com `docker compose up`. É o "processo de RFC" que o slide pede: trocar ideias e definir escopo, sem entregar documento.

- [ ] Fechar a lista de regras do MVP (Fase 2) e das que entram se der tempo (Fase 3)
- [ ] Fechar os parâmetros iniciais, separando os que vêm de norma dos que são estimativa
- [ ] Definir as frentes e quem fica com cada uma (seção Divisão do time)
- [ ] Criar o repositório a partir do Base Service e conferir que `docker compose up` e `pytest` passam na máquina de todos
- [ ] Renomear `sample_entity` para as entidades do motor, mantendo as camadas e o padrão de erros
- [ ] Escrever o esqueleto do README no modelo da banca, com as seções vazias
- [ ] Combinar as convenções: valores em centavos, `_key` em UUID na resposta, `id` interno nunca sai da API, fuso de Brasília nas regras de horário

**Portão:** API base de pé em todas as máquinas e lista de regras aprovada pelo grupo.

## Fase 1 — Banco de dados e esqueleto da API (sáb 14h30–17h30)

A fase termina com todo Pix recebido gravado e consultável, ainda sem regra: o motor aprova tudo. É o critério "solução funcional" garantido cedo, antes de qualquer risco.

- [ ] `database/database.sql` com as tabelas da seção Modelo de dados, os enumeradores e os índices
- [ ] Models na ordem certa no `src/models/__init__.py` (quem depende vem depois)
- [ ] Schema JSON `post_pix_transaction.json` com todos os campos do contrato; `geolocation` opcional; campo a mais vira 400
- [ ] Normalizar CPF e CNPJ só com dígitos e validar dígito verificador com o `utils/document_number.py` do Base Service (inválido vira 422)
- [ ] `POST /pix/transaction`: grava conta, aparelho, transação e análise numa única transação de banco; responde `{key, status, metadata}`
- [ ] `GET /pix/transaction/{id}`: devolve a análise gravada; `id` inexistente vira 404
- [ ] Idempotência: mesmo `id` com o mesmo conteúdo devolve a análise já gravada (200), sem reavaliar; mesmo `id` com conteúdo diferente vira 409 (comparação por hash do payload)
- [ ] Erros novos em `src/errors/custom_errors.py` com `title`, `description`, `translation` e código `QIT`
- [ ] Testes de caixa-preta por HTTP, escritos antes do código (vermelho, verde, refatora): criar, consultar, repetir, conflito, schema inválido, sem `INTERNAL-TOKEN`

**Portão:** os testes de contrato passam e um `docker compose down -v && docker compose up` sobe o banco do zero sem erro.

## Fase 2 — Motor de regras núcleo (sáb 17h30–23h)

A fase termina com o motor decidindo de verdade, com as regras do MVP, a lógica de decisão e o `metadata` explicável. Se o tempo acabar aqui, já existe uma entrega completa.

**Onde cada coisa mora no Base Service.** O controller orquestra e decide; ele é o único que pede a sessão. Um repositório de features (`pix_feature_repository.py`) faz as consultas em janela de tempo e devolve números, sem decidir nada. As regras ficam em `src/controllers/rules/`, uma classe por regra, cada uma recebendo as features e devolvendo um resultado. Os parâmetros vêm da tabela de política, nunca de constante no código.

**Regras compostas, sinais independentes.** Cada uma das 8 regras do catálogo é uma classe na interface comum e avalia os seus sinais um a um, cada sinal na sua camada, devolvendo um resultado por sinal com código, valor observado e limite. As três condições da seção Catálogo de regras valem para todas.

**Como uma requisição é avaliada:**

1. Trava por pagador, por recebedor pessoa física e por aparelho com `pg_advisory_xact_lock`, tomadas sempre em ordem crescente de chave, como as duas contas da transferência na fase 1, para não haver impasse. Dois Pix simultâneos do mesmo pagador, para o mesmo recebedor ou do mesmo aparelho são avaliados em fila, e nenhuma contagem é enganada: nem a velocidade, nem os pagadores distintos de uma conta, nem os CPFs de um aparelho. O recebedor PJ não é travado, porque o sinal de muitos pagadores não vale para ele e um lojista grande ficaria em fila. É a lição de concorrência da fase 1, aplicada ao antifraude.
2. Camada 0: regras obrigatórias e baratas. Marcação de fraude decide sozinha a recusa, e aparelho não cadastrado acima do limite decide sozinho o 2FA. O horário noturno entra como sinal.
3. Camada 1: lê as tabelas agregadas e roda as regras de perfil e de contraparte básica, sem chamada externa.
4. Gatilho: sem sinal de risco, o Pix sai pelo caminho rápido com `approved`. Com sinal, segue para a camada 2.
5. Camada 2: regras de rede e ML, com tempo limite. Estourou o tempo, a decisão é 2FA.
6. Decide pelos placares de conta invadida (`ato`), golpe (`app`) e conta laranja (`mule`): `rejected` vence `two_factor_required`, que vence `approved`. Placar de conta laranja ou de golpe acima do corte recusa; placar de conta invadida acima do corte pede 2FA. Placar de golpe na faixa de aviso aprova com `warn`.
7. Grava a transação, a análise, cada resultado de regra e as features usadas, atualiza as tabelas agregadas e faz o commit.

**Regras do MVP:** Regra 1 completa; Regra 2 com aparelho não cadastrado e horário noturno; Regra 3 com velocidade; Regra 4 completa; Regra 6 com conta nova e muitos pagadores; e o contexto de mesma titularidade. Elas cobrem as cinco famílias do slide: limite, velocity, montante, perfil e contraparte.

**Higiene do histórico.** O perfil do pagador usa só Pix aprovados dos últimos 90 dias, para que o fraudador não "eduque" a linha de base com tentativas. As tentativas recusadas contam para velocidade, porque insistência também é sinal. As janelas usam o `transaction_date` convertido para o fuso de Brasília, o que deixa os testes determinísticos.

**Testes:** um cenário HTTP por sinal, com o Pix que dispara e o que fica logo abaixo do limite. Mais um teste de concorrência: 10 Pix paralelos do mesmo pagador produzem a mesma decisão que em sequência, e 6 pagadores diferentes enviando ao mesmo tempo para a mesma conta pessoa física disparam o sinal de muitos pagadores exatamente como em sequência.

**Portão:** o payload do exemplo do slide (R$ 1.500 às 22h15 para conta aberta há 7 dias) sai com decisão e motivos coerentes, e todos os testes de regra passam.

## Fase 3 — Regras de rede, diferenciais e auditoria (sáb 23h–dom 3h)

A fase termina com o motor enxergando a rede de contas e com cada decisão imutável e verificável. É aqui que o critério "profundidade antifraude, sem parar no óbvio" se ganha.

- [ ] Regra 5 completa: aparelho compartilhado (CPFs distintos no mesmo `device_id` em 30 dias), viagem impossível e zona habitual, com a geolocalização opcional tratada como `not_evaluated` em vez de aprovar em silêncio
- [ ] Regra 2: sinal de geolocalização desligada
- [ ] Regra 3: sinal de fracionamento
- [ ] Regra 6 completa: conta dormente reativada e mesmo CPF em várias instituições
- [ ] Regra 7: repasse rápido (o CPF pagador recebeu de terceiros nos últimos 60 minutos e repassa a maior parte; o cruzamento é pelo documento, porque a conta de origem não traz ISPB no contrato) e proximidade de conta marcada (consulta recursiva de até 2 saltos em 24h)
- [ ] Faixa de aviso na decisão: aprovação com `recommended_action: warn`
- [ ] Política versionada: parâmetros por sinal na tabela `rule_parameter`, uma versão ativa, carregada por seed no `database.sql`. Sem endpoint de configuração, porque o escopo deixa outras APIs de fora
- [ ] Trilha encadeada por hash: cada análise grava o hash do seu conteúdo somado ao hash da análise anterior do mesmo pagador, gravado sob a mesma trava por pagador. A cadeia é por pagador, e não única para o sistema, porque uma cadeia global obrigaria todo Pix a esperar o último gravado e acabaria com o paralelismo entre clientes. Um teste altera uma linha antiga direto no banco e prova que a cadeia quebra. É a propriedade que a ideia de blockchain buscava, dentro do PostgreSQL
- [ ] Latência medida e gravada em cada análise (`latency_ms`)

**Portão:** cada sinal novo tem teste HTTP verde e o teste de integridade da cadeia passa.

## Fase 4 — Simulador e Machine Learning (em paralelo, sáb 17h30–dom 3h)

A fase termina com um número que nenhum outro grupo vai ter: quantas fraudes de cada tipo o motor pega e quantos clientes legítimos ele incomoda, com e sem o modelo. Uma pessoa toca esta frente desde o fim da Fase 1.

**Por que o ML é desenhado assim.** Não existem dados reais de fraude rotulados no hackathon. Um modelo supervisionado treinado com dados que nós mesmos inventamos só aprenderia as nossas regras. Por isso o modelo é de detecção de anomalia: aprende o comportamento normal e mede o quanto cada Pix foge dele. As regras pegam o que conhecemos; o modelo sinaliza o que ainda não conhecemos.

**Simulador (`scripts/simulator/`).** Gera algumas centenas de clientes com hábitos próprios e envia os Pix pela API, por HTTP, como um cliente qualquer. O cenário vai no prefixo do `id` (`sim-legit-`, `sim-ato-`, `sim-app-`, `sim-mule-`, `sim-novel-`), sem mudar o contrato. Cenários:

- Legítimos: rotina, salário, aluguel, racha de conta, Pix para lojista, viagem de férias
- Conta invadida: celular roubado, aparelho novo, fora da zona habitual, rajada de Pix
- Golpe: falsa central e falso parente, com aparelho conhecido, valor fora do perfil e destino novo
- Conta laranja: várias vítimas para uma conta nova e repasse em minutos
- Padrão novo, fora de qualquer regra: Pix de centavos espaçados para muitos destinos diferentes, como quem valida contas antes de um golpe

**Modelo.** Isolation Forest do scikit-learn, com versão exata fixada no `requirements.txt`. Treinado offline por `scripts/ml/train.py` apenas com os Pix legítimos do simulador. As features são as mesmas que as regras já calculam e que ficam gravadas em cada análise: valor em relação à mediana do pagador, hora local, idade das duas contas, primeira vez nesse destino, contagens em janela, pagadores distintos do destino, aparelho conhecido, distância da zona habitual e repasse recente. O arquivo do modelo entra versionado no repositório e é carregado quando a API sobe.

**Como o modelo entra na decisão (Regra 8).**

1. Primeiro em modo sombra: o escore vai para o `metadata` e não muda a decisão.
2. Se a avaliação mostrar ganho, passa a modo ativo pela política (`ml_mode`): soma pontos limitados por um teto e nunca recusa sozinho.
3. Cada análise mostra as três features que mais fugiram do normal, em português, para o modelo também ter motivo explicável.
4. Se o arquivo do modelo faltar ou falhar, a Regra 8 fica `not_evaluated` e o motor decide só com as regras.

**Avaliação (`scripts/ml/evaluate.py`).** Uma tabela por cenário, incluindo cada linha da matriz de erros reais, com taxa de fraude pega, taxa de 2FA e de recusa em clientes legítimos, percentual de Pix no caminho rápido e latência p50, p95 e p99 por caminho, comparando regras sozinhas e regras com ML. O slide da apresentação sai daqui.

**Portão:** o simulador roda de ponta a ponta contra o `docker compose`, o modelo carrega na API e a tabela de avaliação existe, mesmo que o ML fique em sombra.

## Fase 5 — README, testes finais e apresentação (dom 8h–12h)

A fase termina com o link do repositório no grupo da final, no Slack, antes das 12h. O código congela às 10h30; depois disso só entra correção de bug.

- [ ] README no modelo da banca: `# Nome do grupo`, `Integrantes`, `Como o motor de decisão funciona`, `Regras` (tabela Regra, Lógica, Parâmetros, Por quê), `Como as regras viram decisão` (ordem e quando pede 2FA) e `Como rodar e testar`
- [ ] Na tabela de regras, cada parâmetro marcado como "norma" (com a citação) ou "estimativa" (com o raciocínio)
- [ ] Teste de clone limpo numa máquina Linux: `git clone`, `docker compose up`, `pytest`, seguindo só o README. É assim que o jurado vai rodar
- [ ] README explica o `INTERNAL-TOKEN` padrão e traz exemplos de `curl` para o POST e o GET, para o jurado não tomar 403 na primeira chamada
- [ ] Rodar o simulador e a avaliação uma última vez e congelar a tabela de resultados
- [ ] Roteiro de 7 minutos, ensaiado com cronômetro, e respostas preparadas para os 3 minutos de perguntas
- [ ] Enviar o link do repositório até 11h45, com folga

**Roteiro da apresentação (7 min):**

1. O problema em um número: o MED recuperou só 9,3% do valor contestado em 2025, então a decisão tem que acontecer antes do Pix sair (40 s)
2. A tese: 2FA para o invasor, recusa para o golpe (1 min)
3. Demo ao vivo com quatro Pix: cliente normal, celular roubado, falsa central e conta laranja, mostrando o `metadata` de cada um (2 min)
4. A rede: como o histórico próprio vira fan-in, repasse rápido e aparelho compartilhado (1 min)
5. O resultado do simulador: fraude pega por tipo e fricção em cliente bom, com e sem ML (1 min 20 s)
6. Limites e próximos passos: sinais que o contrato não traz (ligação ativa, app de acesso remoto) e calibração com o resultado real do 2FA e do MED (1 min)

**Portão:** clone limpo funcionando e link enviado.

## Catálogo de regras

São 8 regras compostas. Cada uma responde uma pergunta e combina sinais: ao todo, 17 sinais, mais o contexto de mesma titularidade e a faixa de aviso da decisão. Valores em centavos no código (R$ 200 = 20.000).

| Regra | Pergunta | Família do slide | Sinais | Saída típica |
| --- | --- | --- | --- | --- |
| 1. Lista de marcação | Alguém já marcou esta pessoa? | Contraparte | 1 | Recusa |
| 2. Limite por contexto | O valor cabe no limite deste contexto? | Limite e montante | 3 | 2FA |
| 3. Ritmo | Rápido demais ou somou demais? | Velocity e montante | 2 | 2FA ou recusa |
| 4. Perfil do pagador | Está no padrão deste cliente? | Perfil | 1 | Pontua golpe ou invasão |
| 5. Quem está operando | É o dono da conta? | Perfil | 3 | 2FA |
| 6. Conta recebedora | Quem recebe é confiável? | Contraparte | 4 | Pontua conta laranja |
| 7. Rastro do dinheiro | O dinheiro está só de passagem? | Contraparte | 2 | Recusa |
| 8. Anomalia (ML) | É diferente de tudo que é normal? | Perfil | 1 | Pontua; nunca recusa sozinha |

**Sinais.** Cada sinal tem código próprio, parâmetro, saída e camada. A coluna "Antes" liga cada sinal à numeração antiga do plano, como prova de que nada se perdeu na condensação.

| Sinal | Antes | Lógica | Parâmetro inicial | Saída | Camada | Fase |
| --- | --- | --- | --- | --- | --- | --- |
| `MARCACAO.lista` | R12 | Pagador ou recebedor na tabela local que simula o DICT | — (norma, Res. BCB 587/2026) | Recusa | 0 | 2 |
| `LIMITE.aparelho_nao_cadastrado` | R2 | Aparelho sem Pix aprovado desse pagador | R$ 200 por Pix, R$ 1.000 por dia (norma, Res. BCB 402/2024) | 2FA | 0 | 2 |
| `LIMITE.noturno` | R5 | Soma PF→PF entre 20h e 6h (Brasília) acima do padrão do BCB e acima do maior Pix noturno aprovado do pagador | R$ 1.000 (padrão da Res. BCB 142/2021); o motor não recebe o limite configurado do cliente, então é sinal, não teto | 2FA; com sinal de golpe ou laranja, recusa | 0 | 2 |
| `LIMITE.sem_geolocalizacao` | R15 | Sem `geolocation` e valor acima de um limite reduzido | faculdade da IN BCB 669; valor estimado | 2FA | 1 | 3 |
| `RITMO.velocidade` | R4 | Tentativas do pagador em janela deslizante, incluindo recusadas, combinando contagem e soma | 5 em 10 min → 2FA; 10 → recusa (estimativa) | 2FA ou recusa | 0 | 2 |
| `RITMO.fracionamento` | R11 | Vários Pix logo abaixo de R$ 200 ou do padrão noturno | 3 em 1h (estimativa) | 2FA | 2 | 3 |
| `PERFIL.valor` | R6 | Valor acima do P95 e de 5× a mediana dos Pix aprovados; destino recorrente atenua | mínimo de 5 Pix; sem histórico, valor de partida (estimativa) | Pontua golpe ou invasão, conforme o contexto | 1 | 2 |
| `QUEM_OPERA.aparelho_compartilhado` | R3 | CPFs distintos no mesmo aparelho | 3 em 30 dias (estimativa) | 2FA; com sinal da Regra 6 ou 7, recusa | 2 | 3 |
| `QUEM_OPERA.viagem_impossivel` | R10 | Distância ÷ tempo desde o último Pix | 900 km/h (estimativa) | 2FA | 1 | 3 |
| `QUEM_OPERA.fora_da_zona` | R17 | Longe dos locais dos Pix aprovados, acima de limite reduzido | raio e limite estimados; inspiração no Modo Rua do Nubank | 2FA | 2 | 3 |
| `CONTA_RECEBEDORA.conta_nova` | R7 | Conta destino recente, primeiro crédito e valor fora do perfil | 30 dias (estimativa; fator citado no art. 39-B da Res. 147) | Pontua laranja; combinada, recusa | 1 | 2 |
| `CONTA_RECEBEDORA.fan_in` | R8 | Pagadores distintos para um recebedor pessoa física | 5 em 1h (estimativa) | Pontua laranja; combinada, recusa | 1 | 2 |
| `CONTA_RECEBEDORA.dormente` | R13 | Conta parada recebe e repassa na mesma hora | 60 a 90 dias parada (estimativa) | Pontua laranja; com repasse, recusa | 2 | 3 |
| `CONTA_RECEBEDORA.varias_instituicoes` | R16 | Mesmo CPF recebedor com contas novas em ISPBs diferentes | 2 ISPBs (estimativa) | Pontua laranja | 2 | 3 |
| `RASTRO.repasse_rapido` | R9 | CPF pagador recebeu de terceiros e repassa a maior parte; cruzamento pelo documento | 60 min (com dado), 80% (estimativa) | Recusa | 2 | 3 |
| `RASTRO.proximidade_marcada` | R14 | Recebedor recebeu de conta marcada | 1 salto → recusa; 2 saltos em 24h → pontua (estimativa) | Recusa ou pontua | 2 | 3 |
| `ANOMALIA.ml` | R19 | Escore do Isolation Forest sobre as features da análise | modo sombra ou ativo, com teto de pontos | Pontua; nunca recusa sozinho | 2 | 4 |

**Fora do catálogo, mas preservados.** A mesma titularidade (antes R1) virou contexto que todas as regras consultam: isenta dos sinais de golpe, de conta laranja e do horário noturno. A faixa de aviso (antes R18) virou parte da decisão final: placar de golpe entre o corte de aviso e o de recusa aprova com `warn`.

**Três condições para a condensação não perder qualidade:**

1. Cada sinal mantém o próprio código de motivo no `metadata`, com valor observado e limite. Nunca só "conta recebedora suspeita".
2. Cada sinal mantém a própria saída e a própria camada. Uma regra composta avalia sinal por sinal e só roda os sinais caros na camada 2.
3. Combinações entre regras, como aparelho compartilhado com repasse rápido, ficam explícitas na camada de decisão, pelos placares.

**No README**, cada regra é uma linha da tabela Regra / Lógica / Parâmetros / Por quê, e os sinais aparecem como subitens com o parâmetro e a fonte. Assim a profundidade continua visível no documento por onde a correção começa.

## Modelo de dados

O banco guarda tudo o que chegou, inclusive o que foi recusado, e cada decisão com o seu porquê. Segue o padrão do Base Service: tabela de enumerador para status, `_key` em UUID para fora e `id` só interno.

| Tabela | O que guarda | Chaves e restrições |
| --- | --- | --- |
| `account` | Conta de origem ou destino: ISPB, agência, número, data de abertura, documento do titular e tipo (PF ou PJ) | UNIQUE (ispb, agência, número); ISPB nulo na origem, que o contrato não informa |
| `device` | Aparelho visto pelo motor e quando apareceu pela primeira vez | UNIQUE no `device_id` recebido |
| `pix_transaction` | O Pix como chegou: `id` externo, valor, data com fuso, contas, aparelho, canal, IP, geolocalização e o payload bruto | UNIQUE no `id` externo; hash do payload para idempotência; CHECK valor > 0; documentos de pagador e recebedor copiados para indexar |
| `analysis_status` | Enumerador: `approved`, `two_factor_required`, `rejected` | UNIQUE no enumerador |
| `analysis` | A decisão: `analysis_key`, status, tipologia, ação recomendada, placares, features usadas, escore e versão do ML, versão da política, latência e hashes da cadeia | UNIQUE em `analysis_key`, em `pix_transaction_id` e no hash; append-only |
| `analysis_rule_result` | Uma linha por sinal avaliado, com a regra e o código do sinal: resultado (`pass`, `warn`, `two_factor`, `reject`, `not_evaluated`), pontos, valor observado, limite e mensagem em português | FK para `analysis` |
| `policy_version` | Versão da política e o modo do ML (`shadow` ou `active`) | Uma única versão ativa, por índice único parcial |
| `rule_parameter` | Parâmetros de cada sinal numa versão, em JSONB, e se o sinal está ligado | UNIQUE (versão, código do sinal) |
| `fraud_marker` | Marcações que simulam o DICT e a Res. 587: documento, tipo (própria, conta laranja, conta de golpista), origem e validade | Carregada por seed |

**Tabelas agregadas do caminho rápido**, atualizadas no mesmo commit de cada Pix:

| Tabela | O que guarda | Para qual regra |
| --- | --- | --- |
| `payer_profile` | Por documento do pagador: últimos 50 valores aprovados, mediana e P95 recalculados na escrita, quantidade de Pix aprovados, última geolocalização e data, maior Pix noturno aprovado | Regras 2, 4 e 5 |
| `payer_payee_pair` | Por par pagador-recebedor: primeira e última vez, quantidade e soma aprovadas | Regra 4 (destino recorrente), Regra 6 (primeiro crédito) |
| `device_owner` | Por aparelho e documento: primeira vez visto e se já teve Pix aprovado | Regras 2 e 5 |

**Índices que as regras exigem:** `pix_transaction` por (documento do pagador, data), (documento do recebedor, data), (aparelho, data) e (conta de origem, data). Cada regra é uma consulta em janela sobre um desses índices.

**Por que a análise não tem trilha de eventos de status.** No Base Service, a trilha registra mudanças de estado. A análise do motor nasce final e nunca muda, porque o contrato não tem retorno do 2FA. A garantia de que ela não foi alterada vem da cadeia de hashes.

## Contrato da API

Duas rotas do desafio, mais as do Base Service. Toda rota, menos `/` e `/health_check`, exige `INTERNAL-TOKEN`. Uma recusa antifraude não é erro HTTP: o Pix foi analisado com sucesso e a resposta é 201 com `status: rejected`.

| Método e rota | Quando | HTTP |
| --- | --- | --- |
| `POST /pix/transaction` | Pix novo, analisado e gravado | 201 com `{key, status, metadata}` |
| `POST /pix/transaction` | Mesmo `id` e mesmo conteúdo | 200 com a análise já gravada, sem reavaliar |
| `POST /pix/transaction` | Mesmo `id` com conteúdo diferente | 409 |
| `POST /pix/transaction` | JSON fora do schema (campo faltando, tipo errado, campo a mais) | 400 |
| `POST /pix/transaction` | CPF ou CNPJ com dígito verificador inválido | 422 |
| `GET /pix/transaction/{id}` | Análise encontrada pelo `id` do Pix | 200 com a mesma resposta do POST |
| `GET /pix/transaction/{id}` | `id` desconhecido | 404 |
| Qualquer rota protegida | Sem `INTERNAL-TOKEN` ou token errado | 403 |

A resposta tem só os três campos do slide. O `metadata` é livre e carrega a explicação:

```json
{
  "key": "b3f1c2e0-7d4a-4c1e-9a52-1f0e6c9d2a77",
  "status": "rejected",
  "metadata": {
    "policy_version": "2026.10.1",
    "typology": "mule_account",
    "recommended_action": "block",
    "scores": {"ato": 0, "app": 35, "mule": 80},
    "reasons": [
      {"signal": "CONTA_RECEBEDORA.conta_nova", "outcome": "reject", "observed": {"account_age_days": 7}, "threshold": {"days": 30},
       "message": "Conta recebedora aberta há 7 dias recebendo o primeiro Pix, fora do perfil do pagador"},
      {"signal": "CONTA_RECEBEDORA.fan_in", "outcome": "reject", "observed": {"distinct_payers_1h": 6}, "threshold": {"payers": 5},
       "message": "6 pagadores diferentes enviaram para esta conta na última hora"}
    ],
    "not_evaluated": [{"signal": "QUEM_OPERA.viagem_impossivel", "reason": "sem geolocalização"}],
    "ml": {"mode": "shadow", "model_version": "iforest-v1", "anomaly_score": 0.81,
           "top_features": ["valor 6× a mediana do pagador", "destino novo", "hora fora do habitual"]},
    "latency_ms": 41,
    "audit": {"record_hash": "…", "prev_hash": "…"}
  }
}
```

Os valores `recommended_action` possíveis são `none`, `warn`, `step_up` (2FA), `hold_timer` (golpe com suspeita, que em produção viraria a retenção de 30 a 60 minutos do BCB) e `block`.

## Checklist de conformidade

Toda exigência do material do desafio, do Base Service e das aulas tem um lugar no plano. Antes de enviar o link, o grupo confere esta tabela linha a linha.

| Exigência | Origem | Onde o plano cumpre |
| --- | --- | --- |
| `POST /pix/transaction` com o payload definido (id, amount em centavos, transaction\_date com fuso, contas com abertura e documento, ISPB do destino, device\_id, canal, IP, geolocalização opcional) | Slide "Payload de entrada" e "Campos da entrada" | Fase 1, schema JSON |
| Resposta só com `key`, `status` e `metadata` | Slide "Payload de saída" | Contrato da API |
| Status é `approved`, `rejected` ou `two_factor_required` | Slides "As três decisões" e "Payload de saída" | Fase 2, lógica de decisão |
| `GET /pix/transaction/{id}` devolve a análise gravada | Slide "Payload de saída" | Fase 1 |
| Banco próprio com o histórico de tudo que chegou | Slide "Escopo" | Fase 1 e Modelo de dados (recusados também são gravados) |
| As regras e os testes | Slide "Escopo" | Fases 2, 3 e 4, um teste HTTP por sinal |
| Partir do Base Service, seguindo os padrões de código do bootcamp | Slides "Escopo" e "Entregáveis" | Fases 0 e 1 |
| Fora do escopo: onboarding e cadastro de contas, front-end, outras APIs | Slide "Escopo" | Contas nascem do próprio Pix; política e marcações por seed, sem endpoint extra; sem front |
| Política livre, desde que expliquem o porquê | Slide "Escopo" | Catálogo de regras e coluna "Por quê" do README |
| Regras de limite, velocity, montante, perfil e contraparte | Slide "Exemplos de regras" | Catálogo de regras, coluna Família |
| Decisão em poucos segundos, sem consulta externa pesada | Slide "O que muda no Pix" (tempo) | Fase 2: avaliação em camadas com caminho rápido, nenhum connector, consultas indexadas, `latency_ms` gravado e p95 medido no simulador |
| Comparar com o que o pagador e o destino já fizeram | Slide "O que muda no Pix" (histórico) | Features em janela; perfil só com aprovados |
| Não travar quem só quer pagar o aluguel | Slide "O que muda no Pix" (fricção) | Matriz de erros reais, faixa de aviso, contexto de mesma titularidade, taxa de fricção medida no simulador |
| Toda decisão sai com motivo explicável | Slide "As três decisões" | `reasons` com valor observado, limite e mensagem; motivos também para o ML |
| Sem análise manual: o cliente está esperando | Slide "As três decisões" | Decisão síncrona; nenhum status "em análise" |
| README no modelo: nome do grupo, integrantes, como o motor funciona, tabela Regra / Lógica / Parâmetros / Por quê, como as regras viram decisão (ordem, quando pede 2FA), como rodar e testar | Slide "Modelo do README" | Fase 5 |
| Explicar o porquê de cada parâmetro | Slide "Modelo do README" | Parâmetros marcados como norma ou estimativa |
| Apresentação de até 7 min + 3 min de perguntas | Slide "Entregáveis" | Fase 5, roteiro cronometrado |
| Processo de RFC: trocar ideias e definir escopo, sem entregar documento | Slide "Entregáveis" | Fase 0 |
| Seis critérios: profundidade antifraude, padrão de código, modelagem de dados, solução funcional, documentação, apresentação | Slide "Critérios de avaliação" | Fases 3 e 4; Fases 1 e 2; Modelo de dados; portão da Fase 1; Fase 5; roteiro |
| O projeto roda seguindo o README e as decisões batem com as regras descritas | Slide "Critérios de avaliação" | Teste de clone limpo e testes por regra |
| Link do repositório até domingo 12h no grupo da final, no Slack | Slide "Agenda do hackathon" | Fase 5, envio até 11h45 |
| Camadas resource → controller → repository → model, seta num sentido só | Base Service, `docs/como-o-projeto-e-organizado.md` | Fase 2: regras no controller, consultas no repositório de features |
| Entrada validada por JSON Schema em `src/schemas/`; saída montada em `src/dtos/` | Base Service | Fase 1 |
| Erros em `src/errors/` com título, descrição, tradução e código | Base Service | Fase 1 |
| Só o controller pede a sessão e faz o commit | Base Service | Fase 2, passo 6 |
| Middleware de `INTERNAL-TOKEN` em toda rota | Base Service | Contrato da API |
| `database.sql` versionado; roda só quando o banco nasce | Base Service | Fase 1, portão com `down -v` |
| Dependências com versão exata; reconstruir a imagem ao mudar | Base Service | Fase 4 (scikit-learn fixado) |
| `docker compose up` em um comando, com healthcheck | Base Service | Fase 5, clone limpo |
| Testes de caixa-preta: só HTTP, nenhum import do código da aplicação | Autoestudo da Aula 3 | Todos os testes e o simulador falam por HTTP |
| TDD: ver o teste falhar antes do código | Autoestudo da Aula 3 | Fases 1 e 2 |
| Na RFC, banco antes das rotas; decisões e trade-offs com o motivo | Aula 2 | Modelo de dados antes do contrato; "considerado e descartado" no README |

## Divisão do time

Quatro frentes que mexem em arquivos diferentes, como o Base Service prevê, para ninguém pisar no código do outro. Os nomes ficam para o grupo decidir na Fase 0.

| Frente | Responsabilidade | Arquivos principais | Fases |
| --- | --- | --- | --- |
| A — API e banco | Schema, models, rotas, idempotência, erros, testes de contrato, cadeia de hashes | `database.sql`, `models/`, `schemas/`, `resources/`, `dtos/`, `errors/` | 1, 3 |
| B — Regras de perfil e limite | Regras 2, 3, 4 e 5, o contexto de mesma titularidade e a lógica de decisão com a faixa de aviso | `controllers/rules/`, controller da análise | 2, 3 |
| C — Regras de rede e contraparte | Regras 1, 6 e 7, trava por pagador e repositório de features | `repositories/pix_feature_repository.py`, `controllers/rules/` | 2, 3 |
| D — Simulador e ML | Gerador de cenários, treino, integração da Regra 8, avaliação | `scripts/simulator/`, `scripts/ml/`, `src/ml/` | 4 |
| Proposta e narrativa | Parâmetros e seus porquês, README, roteiro e ensaio da apresentação | `README.md` | 0, 5 (e acompanha todas) |

Se o grupo tiver quatro pessoas, a frente de proposta fica com quem não está no código mais pesado. Pelo que você disse, essa é a sua.

## Riscos e plano B

| Risco | Sinal de alerta | Plano B |
| --- | --- | --- |
| Tempo não dá para todas as regras | Fase 2 não fechou até domingo 1h | Entregar só o MVP bem testado; Fase 3 vira "próximos passos" na apresentação |
| ML não fica pronto ou não mostra ganho | Avaliação sem diferença entre regras e regras com ML | A Regra 8 fica em modo sombra e a apresentação mostra isso com honestidade: o desenho está pronto, falta rótulo real |
| Imagem Docker com scikit-learn pesa ou demora | Build acima de 5 minutos | Fixar versão com wheel pronto; em último caso, o modelo sai da API e a Regra 8 vira `not_evaluated` |
| Mudança no `database.sql` não aparece | Erro de tabela inexistente | `docker compose down -v` e subir de novo; avisar o grupo antes |
| Teste de concorrência instável | Falha intermitente no CI local | Datas fixas no payload e trava por pagador; repetir o teste 20 vezes antes de confiar |
| Jurado não consegue rodar | 403, porta ocupada ou passo faltando | Teste de clone limpo na Fase 5 e README com `curl` prontos |
| Parâmetro estimado questionado na banca | Pergunta "de onde veio esse número?" | Resposta pronta: estimativa declarada, configurável na tabela, e o que calibraria (resultado do 2FA e do MED) |
| Camada profunda deixa o Pix lento | p95 do caminho profundo acima da meta no simulador | Tempo limite que decide 2FA com o que já tem; revisar índices com EXPLAIN; tirar do caminho profundo a regra mais cara |
| Fricção alta em clientes bons | Taxa de 2FA ou recusa nos cenários legítimos acima do aceitável para o grupo | Ajustar os parâmetros na tabela de política, sem mudar código, e rodar o simulador de novo |

## Fontes

- Material do desafio: *Hackathon Antifraude Pix* (QI Tech, Risk Solutions, 17 e 18/10/2026), *bootcamp-base-api* e `docs/como-o-projeto-e-organizado.md`, slides da Aula 2 e autoestudo da Aula 3
- Pesquisa de apoio: relatório *Fraude no Pix para motor antifraude* (enviado nesta conversa), com as citações de cada parâmetro
- [Res. BCB 142/2021, limite noturno](https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?numero=142&tipo=Resolu%C3%A7%C3%A3o+BCB)
- [BCB: dispositivos não cadastrados, R$ 200 e R$ 1.000](https://www.bcb.gov.br/detalhenoticia/20231/noticia)
- [Res. BCB 587/2026, fundada suspeita de fraude](https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?tipo=Resolu%C3%A7%C3%A3o%20BCB&numero=587)
- [EBA-ECB, relatório de fraude em pagamentos 2025](https://www.ecb.europa.eu/press/intro/publications/pdf/ecb.ebaecb202512.en.pdf)
- [STJ: sem transação incompatível com o perfil, banco não responde (2026)](https://www.stj.jus.br/sites/portalp/Paginas/Comunicacao/Noticias/2026/15072026-Sem-transacoes-incompativeis-com-perfil-de-cliente--banco-nao-responde-por-golpe-da-falsa-central.aspx)
- [Nubank: Modo Rua](https://international.nubank.com.br/pt-br/consumidores/carnaval-seguro-pioneiro-modo-rua-do-nubank-ja-protege-mais-de-5-milhoes-de-clientes/)
- [Itaú: Alerta Pix (ago/2026)](https://www.itau.com.br/media/dam/m/f25db6299e3c944/original/10-08-2026-golpe-da-falsa-central-avanca-com-estrategias-mais-sofisticadas-para-abordar-clientes-reforca-itau-unibanco.pdf)
