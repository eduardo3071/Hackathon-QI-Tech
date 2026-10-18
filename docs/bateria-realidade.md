# Bateria de realidade — semente 2026

## 1. Dia a dia: 90 clientes legítimos, 60 dias de Pix

- Pix simulados: **4543** em 1225 s. Ticket P2P simulado: mediana R$ 55, média R$ 300, 26.0% acima de R$ 200 (referência BCB dez/2025: R$ 50, R$ 273, 21%).
- Inclui: aluguel todo dia 5, compras em lojistas, Pix para amigos, 15% à noite, 10% trocam de celular, 10% viajam ao Rio, 15% movem dinheiro entre contas próprias, 40% usam IP de operadora compartilhado, 8% com geolocalização desligada, 3% usam internet banking.

| Decisão (todo o período) | Pix | % |
|---|---|---|
| aprovado | 4062 | 89.4% |
| 2FA possible_scam/in_app_confirmation +aviso | 193 | 4.2% |
| aprovado c/ aviso | 187 | 4.1% |
| 2FA limit/in_app_confirmation | 53 | 1.2% |
| 2FA device_registration/face_liveness | 28 | 0.6% |
| 2FA account_takeover/face_liveness | 19 | 0.4% |
| 2FA account_takeover/face_liveness +aviso | 1 | 0.0% |

**Últimos 15 dias (motor já conhece os clientes):** aprovado: 92.6%; 2FA possible_scam/in_app_confirmation +aviso: 3.0%; aprovado c/ aviso: 2.7%; 2FA limit/in_app_confirmation: 1.5%; 2FA account_takeover/face_liveness +aviso: 0.1%

**Latência (HTTP de ponta a ponta, sem Docker):** caminho rápido p50 233 ms / p95 587 ms / p99 838 ms (1307 Pix); caminho profundo p50 197 ms / p95 534 ms / p99 798 ms (3353 Pix). Caminho rápido: 28.0% dos Pix.

## 2. Golpes reais encenados

| Golpe | Passo | Decisão do motor | Sinais | Esperado | Depois do 2FA |
|---|---|---|---|---|---|
| F1 Falsa central (aparelho e casa de sempre, 3 Pix altos p/ contas antigas) | R$ 4,800 | 2FA possible_scam/in_app_confirmation +aviso | PERFIL.valor | 2FA c/ aviso em todos | vítima confirma |
| F1 Falsa central (aparelho e casa de sempre, 3 Pix altos p/ contas antigas) | R$ 4,500 | 2FA possible_scam/in_app_confirmation +aviso | PERFIL.valor | 2FA c/ aviso em todos | vítima confirma |
| F1 Falsa central (aparelho e casa de sempre, 3 Pix altos p/ contas antigas) | R$ 3,900 | 2FA possible_scam/in_app_confirmation +aviso | CONTA_RECEBEDORA.suspeita_anterior, PERFIL.valor | 2FA c/ aviso em todos | vítima confirma |
| F2 Falso parente (conta de 15 dias, 2 Pix no mesmo dia) | R$ 1,890 às 11h | aprovado | CONTA_RECEBEDORA.conta_nova | 2FA c/ aviso; 2º também |  |
| F2 Falso parente (conta de 15 dias, 2 Pix no mesmo dia) | R$ 2,300 às 15h | aprovado | CONTA_RECEBEDORA.conta_nova | 2FA c/ aviso; 2º também |  |
| F3 Falso investimento (mesmo destino, valor crescente) | dia 0: R$ 500 | aprovado | — | aviso a partir do salto; repete |  |
| F3 Falso investimento (mesmo destino, valor crescente) | dia 2: R$ 1,000 | aprovado | — | aviso a partir do salto; repete |  |
| F3 Falso investimento (mesmo destino, valor crescente) | dia 5: R$ 3,000 | 2FA possible_scam/in_app_confirmation +aviso | PERFIL.valor | aviso a partir do salto; repete | vítima confirma |
| F3 Falso investimento (mesmo destino, valor crescente) | dia 8: R$ 8,000 | 2FA possible_scam/in_app_confirmation +aviso | CONTA_RECEBEDORA.suspeita_anterior, PERFIL.valor | aviso a partir do salto; repete | vítima confirma |
| F4 Falsa venda (6 compradores → vendedor com conta de 10 dias, 50 min) | comprador 1 | aprovado | CONTA_RECEBEDORA.conta_nova | barrar a partir do 5º |  |
| F4 Falsa venda (6 compradores → vendedor com conta de 10 dias, 50 min) | comprador 2 | aprovado | CONTA_RECEBEDORA.conta_nova | barrar a partir do 5º |  |
| F4 Falsa venda (6 compradores → vendedor com conta de 10 dias, 50 min) | comprador 3 | RECUSADO | CONTA_RECEBEDORA.conta_nova, CONTA_RECEBEDORA.fan_in | barrar a partir do 5º |  |
| F4 Falsa venda (6 compradores → vendedor com conta de 10 dias, 50 min) | comprador 4 | RECUSADO | CONTA_RECEBEDORA.conta_nova, CONTA_RECEBEDORA.fan_in | barrar a partir do 5º |  |
| F4 Falsa venda (6 compradores → vendedor com conta de 10 dias, 50 min) | comprador 5 | RECUSADO | CONTA_RECEBEDORA.conta_nova, CONTA_RECEBEDORA.fan_in | barrar a partir do 5º |  |
| F4 Falsa venda (6 compradores → vendedor com conta de 10 dias, 50 min) | comprador 6 | RECUSADO | CONTA_RECEBEDORA.conta_nova, CONTA_RECEBEDORA.fan_in | barrar a partir do 5º |  |
| F5 Mão fantasma (7 Pix em 6 min, aparelho de sempre) | Pix 1: R$ 1,503 | aprovado | — | travar a partir do 5º |  |
| F5 Mão fantasma (7 Pix em 6 min, aparelho de sempre) | Pix 2: R$ 1,272 | aprovado | — | travar a partir do 5º |  |
| F5 Mão fantasma (7 Pix em 6 min, aparelho de sempre) | Pix 3: R$ 903 | 2FA account_takeover/face_liveness | RITMO.destinos_novos | travar a partir do 5º | golpista não passa na biometria |
| F5 Mão fantasma (7 Pix em 6 min, aparelho de sempre) | Pix 4: R$ 1,534 | 2FA account_takeover/face_liveness | LIMITE.aparelho_nao_cadastrado, RITMO.destinos_novos | travar a partir do 5º | golpista não passa na biometria |
| F5 Mão fantasma (7 Pix em 6 min, aparelho de sempre) | Pix 5: R$ 944 | 2FA account_takeover/face_liveness | LIMITE.aparelho_nao_cadastrado, RITMO.destinos_novos, RITMO.velocidade | travar a partir do 5º | golpista não passa na biometria |
| F5 Mão fantasma (7 Pix em 6 min, aparelho de sempre) | Pix 6: R$ 1,484 | 2FA account_takeover/face_liveness | LIMITE.aparelho_nao_cadastrado, RITMO.destinos_novos, RITMO.velocidade | travar a partir do 5º | golpista não passa na biometria |
| F5 Mão fantasma (7 Pix em 6 min, aparelho de sempre) | Pix 7: R$ 1,727 | 2FA account_takeover/face_liveness | LIMITE.aparelho_nao_cadastrado, RITMO.destinos_novos, RITMO.velocidade | travar a partir do 5º | golpista não passa na biometria |
| F6 Celular roubado na rua, 23h (aparelho de sempre, 9 km de casa) | Pix 1: R$ 900 | aprovado | — | biometria (Modo Rua) |  |
| F6 Celular roubado na rua, 23h (aparelho de sempre, 9 km de casa) | Pix 2: R$ 950 | 2FA limit/in_app_confirmation | LIMITE.noturno | biometria (Modo Rua) | confirmação no app: LADRÃO CONFIRMA |
| F6 Celular roubado na rua, 23h (aparelho de sempre, 9 km de casa) | Pix 3: R$ 980 | 2FA account_takeover/face_liveness | LIMITE.noturno, RITMO.destinos_novos, RITMO.fracionamento | biometria (Modo Rua) | ladrão não passa na biometria |
| F6 Celular roubado na rua, 23h (aparelho de sempre, 9 km de casa) | Pix 4: R$ 3,000 | 2FA account_takeover/face_liveness | LIMITE.aparelho_nao_cadastrado, LIMITE.noturno, PERFIL.valor, RITMO.destinos_novos | biometria (Modo Rua) | ladrão não passa na biometria |
| F7 SIM swap: aparelho novo, Recife, 2h | R$ 7.000 | 2FA account_takeover/face_liveness | LIMITE.aparelho_nao_cadastrado, LIMITE.noturno, PERFIL.valor, QUEM_OPERA.fora_da_zona | 2FA biometria | invasor reprova |
| F7 SIM swap: aparelho novo, Recife, 2h | fraciona 1: R$ 190 | aprovado | — | parar perto de R$ 1.000/dia |  |
| F7 SIM swap: aparelho novo, Recife, 2h | fraciona 2: R$ 190 | aprovado | — | parar perto de R$ 1.000/dia |  |
| F7 SIM swap: aparelho novo, Recife, 2h | fraciona 3: R$ 190 | 2FA limit/face_liveness | RITMO.fracionamento | parar perto de R$ 1.000/dia |  |
| F7 SIM swap: aparelho novo, Recife, 2h | fraciona 4: R$ 190 | 2FA limit/face_liveness | RITMO.fracionamento | parar perto de R$ 1.000/dia |  |
| F7 SIM swap: aparelho novo, Recife, 2h | fraciona 5: R$ 190 | 2FA limit/face_liveness | RITMO.fracionamento | parar perto de R$ 1.000/dia |  |
| F7 SIM swap: aparelho novo, Recife, 2h | fraciona 6: R$ 190 | 2FA limit/face_liveness | RITMO.fracionamento | parar perto de R$ 1.000/dia |  |
| F7 SIM swap: aparelho novo, Recife, 2h | fraciona 7: R$ 190 | 2FA limit/face_liveness | RITMO.fracionamento | parar perto de R$ 1.000/dia |  |
| F8 Sequestro relâmpago (coação, 22h30, 3 Pix de R$ 1.000) | Pix 1 | aprovado | — | limite noturno segura |  |
| F8 Sequestro relâmpago (coação, 22h30, 3 Pix de R$ 1.000) | Pix 2 | 2FA limit/in_app_confirmation | LIMITE.noturno | limite noturno segura | vítima coagida passa no 2FA |
| F8 Sequestro relâmpago (coação, 22h30, 3 Pix de R$ 1.000) | Pix 3 | 2FA account_takeover/face_liveness | LIMITE.noturno, RITMO.destinos_novos, RITMO.fracionamento | limite noturno segura | vítima coagida passa no 2FA |
| F9 Conta laranja de passagem (conta de 20 dias) | vítima 1 paga R$ 700 | aprovado | CONTA_RECEBEDORA.conta_nova | barrar a partir do 5º |  |
| F9 Conta laranja de passagem (conta de 20 dias) | vítima 2 paga R$ 700 | aprovado | CONTA_RECEBEDORA.conta_nova | barrar a partir do 5º |  |
| F9 Conta laranja de passagem (conta de 20 dias) | vítima 3 paga R$ 700 | RECUSADO | CONTA_RECEBEDORA.conta_nova, CONTA_RECEBEDORA.fan_in | barrar a partir do 5º |  |
| F9 Conta laranja de passagem (conta de 20 dias) | vítima 4 paga R$ 700 | RECUSADO | CONTA_RECEBEDORA.conta_nova, CONTA_RECEBEDORA.fan_in | barrar a partir do 5º |  |
| F9 Conta laranja de passagem (conta de 20 dias) | vítima 5 paga R$ 700 | RECUSADO | CONTA_RECEBEDORA.conta_nova, CONTA_RECEBEDORA.fan_in | barrar a partir do 5º |  |
| F9 Conta laranja de passagem (conta de 20 dias) | laranja repassa R$ 3.300 (4 min depois) | RECUSADO | CONTA_RECEBEDORA.conta_nova, LIMITE.aparelho_nao_cadastrado, PERFIL.valor, RASTRO.conta_pagadora_recente, RASTRO.repasse_rapido | RECUSAR |  |
| F10 Fazenda de contas (4 CPFs, 1 aparelho) | CPF 1 | aprovado | — | sinalizar a partir do 3º |  |
| F10 Fazenda de contas (4 CPFs, 1 aparelho) | CPF 2 | aprovado | — | sinalizar a partir do 3º |  |
| F10 Fazenda de contas (4 CPFs, 1 aparelho) | CPF 3 | 2FA possible_scam/face_liveness +aviso | QUEM_OPERA.aparelho_compartilhado | sinalizar a partir do 3º |  |
| F10 Fazenda de contas (4 CPFs, 1 aparelho) | CPF 4 | 2FA possible_scam/face_liveness +aviso | QUEM_OPERA.aparelho_compartilhado | sinalizar a partir do 3º |  |
| F11 Teste de contas (25 Pix de R$ 0,01 a cada 20 min) | 25 Pix | {'aprovado': 25} | — | só o ML pegaria |  |
| F12 Marcação (Res. BCB 587) | recebedor com marcação própria | RECUSADO | MARCACAO.lista | RECUSAR |  |
| F12 Marcação (Res. BCB 587) | marcação de outro PSP há mais de 90 dias | aprovado | — | não recusar |  |

## 3. Cotidiano e normas

| Caso | Decisão | Sinais | Esperado |
|---|---|---|---|
| Racha da conta do bar: 6 Pix pequenos p/ amigos em 4 min, 23h (último) | aprovado | — | aprovar |
| Mecânico novo: R$ 1.200 p/ PF desconhecida, 14h | aprovado | — | aprovar ou aviso leve |
| TV na Black Friday: R$ 3.500 p/ loja PJ nova (CNPJ antigo), 10h | aprovado c/ aviso | PERFIL.valor | aprovar ou aviso |
| Farmácia de plantão: R$ 1.300 PF→PJ às 23h30 | aprovado | — | limite noturno NÃO se aplica a PJ |
| Mover o próprio dinheiro: R$ 20.000 p/ conta própria em outro banco, 22h | aprovado | — | aprovar (mesma titularidade) |
| Horário em UTC: Pix de R$ 1.500 enviado como 01:15Z (= 22h15 em Brasília) p/ amigo | aprovado | — | tratar como noturno |
| Viagem: jantar no Rio R$ 180 p/ restaurante PJ, 21h | aprovado | — | aprovar (viagem é rotina) |
| Vaquinha: 20 amigos mandam R$ 20 p/ PF com conta de 4 anos em 1h (20º) | aprovado | — | aprovar |
| Rifa da formatura: 8 amigos mandam R$ 20 p/ conta aberta há 12 dias (8º) | aprovado | CONTA_RECEBEDORA.conta_nova | zona cinzenta: aviso ou 2FA |
| Conta aberta ontem: 1º Pix R$ 150 | aprovado | — | aprovar (≤ R$ 200) |
| Conta aberta ontem: 2º Pix R$ 600 | 2FA device_registration/face_liveness | LIMITE.aparelho_nao_cadastrado | 2FA (aparelho não cadastrado, Res. BCB 403) |
| Cliente antigo do banco, desconhecido do motor, aparelho nunca visto: R$ 700 | 2FA device_registration/face_liveness | LIMITE.aparelho_nao_cadastrado | Res. BCB 403 diz R$ 200 por Pix em aparelho não cadastrado |