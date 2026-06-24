import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from a .env file if it exists
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

class Config:
    # Kafka Settings
    KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")
    TELEMETRY_TOPIC = os.getenv("TELEMETRY_TOPIC", "telemetry")
    
    # Database Settings
    SIMULATION_DB_PATH = os.getenv("SIMULATION_DB_PATH", str(BASE_DIR / "persistence" / "simulation.db"))
    CSV_PATH = os.getenv("CSV_PATH", "c:/Dev/database/csv_export/equipamentos.csv")
    
    # Simulation Settings
    SIMULATION_INTERVAL_SEC = float(os.getenv("SIMULATION_INTERVAL_SEC", "5.0"))
    
    # Support multiple hospitals
    HOSPITAL_ID = int(os.getenv("HOSPITAL_ID", "1"))
    
    num_hospitals_env = os.getenv("NUM_HOSPITALS")
    hospital_ids_env = os.getenv("HOSPITAL_IDS")
    
    if hospital_ids_env:
        HOSPITAL_IDS = [int(x.strip()) for x in hospital_ids_env.split(",") if x.strip()]
    elif num_hospitals_env:
        HOSPITAL_IDS = list(range(1, int(num_hospitals_env) + 1))
    else:
        HOSPITAL_IDS = list(range(1, 11))
    
    # Other settings
    ANOMALY_CHANCE = float(os.getenv("ANOMALY_CHANCE", "0.03"))
