# Serviço de Monitoramento Hospitalar em Tempo Real

Este é um serviço independente em Python desenvolvido para simular a sensorização e telemetria física em tempo real de equipamentos médicos, baseando-se nas fórmulas físicas e limites operacionais definidos no gerador histórico de dados do hospital.

O serviço simula especificamente os **16 equipamentos do Hospital ID 1** ("Hospital de Base Dr. Ary Pinheiro", Porto Velho, RO) registrados no banco de dados histórico do projeto.

---

## 🏗️ Arquitetura

O serviço foi estruturado em módulos independentes da seguinte forma:

```text
monitoring_service/
├── config.py                 # Carregamento de variáveis de ambiente (.env / defaults)
├── main.py                   # Orquestrador e loop principal do relógio virtual da simulação
├── requirements.txt          # Dependências do serviço (numpy, kafka-python, python-dotenv)
├── Dockerfile                # Configuração para empacotar o serviço em um contêiner
├── docker-compose.yml        # Orquestração local do Kafka (modo KRaft) e do Simulador
├── kafka/
│   └── producer.py           # Produtor Kafka resiliente com fallback automático para modo Mock (offline)
├── persistence/
│   ├── db.py                 # Inicializador e persistência SQLite local da simulação (simulation.db)
│   └── simulation.db         # Banco SQLite local contendo o estado físico dinâmico atual dos ativos
├── simulators/
│   ├── base.py               # Constantes de limites, thresholds de falha física e equações gerais
│   └── equipments.py         # Atualização temporal e formatação dos parâmetros específicos por ativo
└── utils/
    └── logger.py             # Logging estruturado conforme o formato especificado
```

### 🧠 Decisões Arquiteturais

1. **Separação de Papéis (Simulador vs. Modelo ML)**:
   O simulador é estritamente um **motor de física e gerador de sinais**. Ele **não** realiza predições ou classificações inteligentes. O objetivo é simular as leituras dos sensores que serão expostas via Kafka. O modelo de Machine Learning externo (consumidor) será o único responsável por prever ou classificar anomalias e falhas a partir desses sinais limpos.
2. **Ausência de Estados Artificiais na Telemetria**:
   O payload enviado para o tópico Kafka `telemetry` contém apenas dados observáveis (ex. `tube_temp`, `vibration`, `voltages`). Estados operacionais de simulação (como `NORMAL`, `DEGRADANDO`, `PRE_FALHA`, `FALHA`) não são enviados nas mensagens, sendo inferidos dinamicamente pelos logs ou mantidos internamente apenas para cálculo da física das equações de desgaste.
3. **Continuidade Temporal com SQLite Local**:
   Para garantir que as leituras não sejam independentes no tempo (e.g., $Temp(t+1) = Temp(t) + delta$), o simulador armazena o último vetor de dados físicos medidos em um banco de dados SQLite local (`simulation.db`). No próximo ciclo de simulação, os valores são recarregados como ponto de partida da equação física.
4. **Produtor Kafka Resiliente (Mock Fallback)**:
   Se o cluster Kafka estiver offline durante a execução local, o produtor intercepta a falha e entra em **modo offline (Mock)** automaticamente. Em vez de quebrar a simulação, ele prossegue computando a física do hospital e emitindo logs detalhados, facilitando testes rápidos locais.

---

## 🔧 Configuração (.env)

O serviço pode ser parametrizado pelas seguintes variáveis de ambiente:

| Variável | Descrição | Padrão |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | Endereço do broker Kafka | `localhost:9092` |
| `TELEMETRY_TOPIC` | Tópico Kafka para telemetria dos sensores | `telemetry` |
| `FAILURES_TOPIC` | Tópico Kafka para eventos de falha física crítica | `failures` |
| `HISTORICAL_DB_PATH` | Caminho do banco de dados histórico para carga inicial | `../sistema_manutencao.db` |
| `SIMULATION_INTERVAL_SEC` | Segundos reais correspondentes a 1 hora na simulação | `5.0` (teste) / `3600.0` (tempo real) |
| `HOSPITAL_ID` | ID do hospital cujos equipamentos serão simulados | `1` |
| `NUM_HOSPITALS` | Quantidade de hospitais que serão simulados concorrentemente (IDs de 1 a NUM_HOSPITALS) | `10` |
| `HOSPITAL_IDS` | Lista explícita de IDs de hospitais para simular (tem precedência sobre `NUM_HOSPITALS`) | `1,2,3,4,5,6,7,8,9,10` |
| `ANOMALY_CHANCE` | Probabilidade por hora de um ativo saudável sofrer anomalia física | `0.13` (13%) |

---

## 🚀 Como Executar

### Pré-requisitos
Certifique-se de que a base histórica do projeto já foi gerada executando `criar_banco_dados.py` no diretório raiz do projeto para criar a base SQLite de origem:
```powershell
python criar_banco_dados.py
```

### 1. Execução Local (Python)

Instale as dependências:
```powershell
pip install -r monitoring_service/requirements.txt
```

Execute o loop de simulação principal:
```powershell
# Executar a partir da raiz do repositório
python -m monitoring_service.main
```
*Dica*: O simulador iniciará e, caso não ache o Kafka local na porta 9092, entrará em modo Offline Mock automaticamente, imprimindo a telemetria e a evolução do desgaste de cada equipamento no console.

### 2. Execução via Docker (Com Kafka local)

O arquivo `docker-compose.yml` instala um ambiente completo contendo o Kafka (modo KRaft) e o contêiner do simulador já configurados.

Para subir o cluster e o monitoramento em tempo real:
```powershell
cd monitoring_service
docker-compose up --build
```
Isso criará o cluster e começará a simular os ativos em tempo real publicando no broker local na rede do Docker.

---

## 📊 Formato dos Dados

### Telemetria (`telemetry`)
Mensagens enviadas a cada hora simulada por equipamento:
```json
{
  "timestamp": "2026-06-06T17:30:00.000000",
  "hospital_id": 1,
  "equipamento_id": 1,
  "telemetria": {
    "scan_count": 45583,
    "tube_temp": 42.105,
    "tube_current": 332.84,
    "anode_rotation_speed": 9780.4,
    "detector_temp_drift": 0.085,
    "slip_ring_error_rate": 0.003,
    "gantry_vibration_fft": 0.284,
    "gantry_rotation": 0.392
  }
}
```

### Evento de Parada / Falha Física (`failures`)
Publicado apenas quando um sensor excede fisicamente seu limite operacional crítico:
```json
{
  "timestamp": "2026-06-06T21:30:00.000000",
  "equipamento_id": 1,
  "tipo": "TC",
  "evento": "falha",
  "tipo_falha": "superaquecimento do tubo",
  "severidade": "Alta"
}
```

---

## 🔍 Observabilidade (Logs Estruturados)

A saída padrão segue o formato de logs estruturados pedido:
```text
INFO equipamento=1 publicando_telemetria
INFO equipamento=1 desgaste=0.0441
WARN equipamento=3 degradacao_detectada
ERROR equipamento=1 falha_detectada
```
