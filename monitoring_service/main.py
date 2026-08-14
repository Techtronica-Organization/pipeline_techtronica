import time
import random
import sys
import uuid
from datetime import datetime, timedelta
from monitoring_service.config import Config
from monitoring_service.equipment_types import simulator_tipo_to_slug
from monitoring_service.utils import logger
from monitoring_service.kafka.producer import KafkaProducerWrapper
from monitoring_service.persistence import db
from monitoring_service.simulators.equipments import atualizar_estado_temporal, formatar_parametros
from monitoring_service.simulators.base import ciclo_uso_hospitalar, detectar_falha, escolher_modo_de_falha

def run_simulation():
    # 1. Initialize simulation database
    try:
        db.init_db()
    except Exception as e:
        print(f"Erro ao inicializar o banco de dados: {e}")
        sys.exit(1)

    # 2. Connect to Kafka
    producer = KafkaProducerWrapper(Config.KAFKA_BOOTSTRAP_SERVERS)

    # 3. Initialize virtual clock (starts at current time)
    sim_time = datetime.now()
    print(f"\nIniciando simulação em tempo real para os Hospitais {Config.HOSPITAL_IDS}.")
    print(f"Intervalo de ciclo: {Config.SIMULATION_INTERVAL_SEC} segundos por hora simulada.")
    print("Pressione Ctrl+C para encerrar.\n")
    try:
        while True:
            t_start = time.time()
            
            # Load all equipments from persistence
            equipments = db.get_all_equipments()
            sim_time_str = sim_time.isoformat()
            
            for eq in equipments:
                eq_id = eq["equipamento_id"]
                h_id = eq["hospital_id"]
                tipo_eq = eq["tipo"]
                desgaste = eq["desgaste"]
                estado_op = eq["estado_operacional_interno"]
                modo_falha = eq["modo_falha_ativo"]
                intensidade_falha = eq["intensidade_falha"]
                horas_restantes = eq["horas_falha_restantes"]
                estado_fisico = eq["ultimo_estado_temporal"]
                
                # Check for state transitions and maintenance
                if estado_op == "EM_MANUTENCAO":
                    horas_restantes -= 1
                    if horas_restantes <= 0:
                        # Maintenance completed: recover health
                        estado_op = "NORMAL"
                        desgaste = max(0.01, desgaste - 0.10)
                        modo_falha = None
                        intensidade_falha = 0.0
                        eq["ultima_manutencao"] = sim_time.strftime("%Y-%m-%d")
                    else:
                        eq["horas_falha_restantes"] = horas_restantes
 
                elif estado_op == "FALHA":
                    horas_restantes -= 1
                    if horas_restantes <= 0:
                        # Start maintenance
                        estado_op = "EM_MANUTENCAO"
                        horas_restantes = random.randint(2, 6) # Maintenance duration
                        eq["horas_falha_restantes"] = horas_restantes
                    else:
                        eq["horas_falha_restantes"] = horas_restantes
 
                elif estado_op == "PRE_FALHA":
                    # Pre-failure ramp progression
                    horas_restantes -= 1
                    if horas_restantes <= 0:
                        # Reached physical failure
                        estado_op = "FALHA"
                        intensidade_falha = 1.0
                        horas_restantes = random.randint(1, 3) # Wait for tech
                        eq["horas_falha_restantes"] = horas_restantes
                    else:
                        # Progress intensity linearly
                        total_horas_rampa = estado_fisico.get("_total_horas_rampa", 24)
                        passado = total_horas_rampa - horas_restantes
                        intensidade_falha = min(1.0, passado / max(1, total_horas_rampa))
                        eq["horas_falha_restantes"] = horas_restantes
                        eq["intensidade_falha"] = intensidade_falha
 
                else: # NORMAL or DEGRADANDO
                    # Check if a new degradation path starts (3% chance per hour)
                    if random.random() < Config.ANOMALY_CHANCE:
                        estado_op = "PRE_FALHA"
                        modo_falha = escolher_modo_de_falha(tipo_eq)
                        rampa_duration = random.randint(12, 36) # hours of pre-failure ramp
                        horas_restantes = rampa_duration
                        intensidade_falha = 0.0
                        estado_fisico["_total_horas_rampa"] = rampa_duration
                        
                        eq["horas_falha_restantes"] = horas_restantes
                        eq["modo_falha_ativo"] = modo_falha
                        eq["intensidade_falha"] = intensidade_falha
                    else:
                        # Standard state based on wear
                        estado_op = "DEGRADANDO" if desgaste >= 0.55 else "NORMAL"
                
                # Calculate hourly utilization index
                uso = ciclo_uso_hospitalar(sim_time, tipo_eq)
                
                # Run simulator equation to update parameters
                estado_fisico, desgaste = atualizar_estado_temporal(
                    tipo_eq=tipo_eq,
                    estado=estado_fisico,
                    desgaste=desgaste,
                    uso=uso,
                    operational_state=estado_op,
                    modo_falha=modo_falha,
                    intensidade_falha=intensidade_falha
                )
                
                # Check for unexpected physical failure based on limits (safety check)
                if estado_op not in ("FALHA", "EM_MANUTENCAO"):
                    falha_fisica = detectar_falha(tipo_eq, estado_fisico)
                    if falha_fisica:
                        # Exceeded operational limits -> immediate breakdown
                        estado_op = "FALHA"
                        horas_restantes = random.randint(1, 3)
                        eq["horas_falha_restantes"] = horas_restantes
                        intensidade_falha = 1.0
                
                # Update counters/cumulative usage
                if "scan_count" in estado_fisico:
                    eq["carga_acumulada"] = estado_fisico["scan_count"]
                elif "exposure_count" in estado_fisico:
                    eq["carga_acumulada"] = estado_fisico["exposure_count"]
                else:
                    eq["carga_acumulada"] = round(eq["carga_acumulada"] + uso * 10, 1)
 
                # Update age (increment by 1/24 day)
                if sim_time.hour == 0:
                    eq["idade_dias"] += 1
                
                # Save state changes
                eq["desgaste"] = desgaste
                eq["estado_operacional_interno"] = estado_op
                eq["ultimo_estado_temporal"] = estado_fisico
                db.update_equipment(eq)
                
                # Format clean telemetry for Kafka (only observable sensors)
                telemetry_payload = formatar_parametros(tipo_eq, estado_fisico)
                
                telemetry_msg = {
                    "event_id": str(uuid.uuid4()),
                    "timestamp": sim_time_str,
                    "hospital_id": h_id,
                    "equipamento_id": eq_id,
                    "numero_serie": eq.get("numero_serie") or f"SN-{eq_id}",
                    "tipo": tipo_eq,
                    "tipo_slug": simulator_tipo_to_slug(tipo_eq),
                    "telemetria": telemetry_payload,
                }
                producer.send_message(Config.TELEMETRY_TOPIC, telemetry_msg)
                
                # Output standard telemetry log
                logger.info(eq_id, f"publicando_telemetria_hospital_{h_id}")
            
            # Flush Kafka producer buffer
            producer.flush()
            
            # Increment virtual clock by 1 hour
            sim_time += timedelta(hours=1)
            
            # Sleep management
            elapsed = time.time() - t_start
            sleep_time = max(0.01, Config.SIMULATION_INTERVAL_SEC - elapsed)
            time.sleep(sleep_time)
            
    except KeyboardInterrupt:
        print("\nSimulação finalizada pelo usuário.")
    finally:
        producer.close()

if __name__ == "__main__":
    run_simulation()
