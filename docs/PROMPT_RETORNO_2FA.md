Substituí de novo o CLAUDE.md da raiz (versão de 17/10, 15h15). A diferença para a anterior é a seção nova "Retorno do 2FA", mais ajustes no Contrato, na "Confiança do aparelho", na tabela de cenários e no "Fora do escopo". Leia essas partes antes de começar.

Contexto: o slide da QI Tech define só o POST e o GET. Hoje, um Pix que pediu 2FA fica gravado como `two_factor_required` para sempre, mesmo que o cliente tenha confirmado, e o motor nunca aprende com ele. Vamos acrescentar o retorno do 2FA de forma ISOLADA (método próprio no controller e arquivo de teste próprio), para poder remover sem quebrar nada se a QI Tech disser que está fora do escopo.

Faça isto como a tarefa 9, depois das 8 anteriores e com a suíte toda verde. Siga o mesmo método: teste primeiro, vendo falhar; implementação; suíte inteira verde; um commit por etapa.

9a. **Trilha de status.** Crie a tabela `analysis_status_event` no padrão do `sample_entity_status_event` do Base Service: `analysis_id`, `from_status_id` (pode ser nulo), `to_status_id`, `event_datetime` e `created_at`. Toda análise grava um evento ao nascer (`null → status inicial`). Ajuste o comentário do `database.sql` que diz que a análise "nasce final e nunca muda". Agora a análise muda de status uma única vez, por evento, e a linha original continua lá. Se a cadeia de hashes da Fase 3 entrar, ela cobre a análise original, e os eventos só são acrescentados.

9b. **Rota `PATCH /pix/transaction/{id}`.**
- Schema: `src/schemas/patch_pix_transaction.json`, com `two_factor_result` (`passed` ou `failed`) e `completed_at` (data e hora com fuso); campo a mais → 400.
- Fluxo: resource → um método novo no controller → repositories, com a mesma trava do POST.
- Respostas: 200 com a análise atualizada (mesmo DTO do GET). Mesmo resultado de novo → 200 sem gravar nada. Resultado diferente, ou análise que não estava em `two_factor_required` → 409. `completed_at` anterior ao `transaction_date` → 422. `id` desconhecido → 404.
- Erros novos em `errors/custom_errors.py`, com código QIT.

9c. **O que o motor aprende com o resultado**, exatamente como a seção "Retorno do 2FA" do CLAUDE.md descreve:
- `passed` com `face_liveness` cadastra o aparelho na hora.
- `passed` por `limit` entra no perfil, na soma noturna e no par, mas não cadastra o aparelho.
- `passed` por `possible_scam` entra no perfil e na soma noturna, mas NÃO torna o destino recorrente. Use a coluna `scam_step_up_count` no par; o atenuante de destino recorrente do `PERFIL.valor` não vale para esse destino.
- `failed` vira `rejected`. Se o motivo era `account_takeover`, o aparelho fica bloqueado para confiança por 24 h (coluna `step_up_failed_at` em `device_owner`).
- O retorno não reavalia regras e não conta como tentativa na velocidade.

9d. **DTO.** O GET e o PATCH devolvem o `status` atual. O `metadata` ganha `initial_status`, `two_factor` (`result` e `completed_at`, ou nulo) e `status_history`. O POST continua igual.

9e. **Testes.**
- Os 4 cenários novos da tabela do CLAUDE.md.
- Os casos de contrato da rota: 200, repetição idempotente, 409 nos dois casos, 422, 404, 400 e 403 sem token.
- Um teste de concorrência: dois PATCH simultâneos com resultados diferentes para o mesmo `id`. Um recebe 200 e o outro 409, e só um evento é gravado.

9f. **README.** Escreva a seção "O que acontece depois do 2FA":
- por que a rota existe e que ela é isolada e removível;
- a trilha de status;
- o que cada resultado ensina ao motor, com o porquê do caso de golpe;
- um exemplo de `curl` do PATCH.

No fim, me devolva:
- a tabela de todos os cenários de ponta a ponta, os antigos e os 4 novos, com o status devolvido;
- a contagem final da suíte;
- qualquer ponto em que o CLAUDE.md tenha ficado ambíguo e como você resolveu.

Se encontrar conflito com o que já foi feito nas tarefas 1 a 8, pare e pergunte.
