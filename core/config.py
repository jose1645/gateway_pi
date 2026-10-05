import os
import yaml
from typing import Dict, Any

DEFAULT_CONFIG: Dict[str, Any] = {
    "gateway": {
        "id": "GW-PI-001",
        "name": "Gateway Edge Raspberry Pi",
        "plant_id": "DEFAULT-PLANT",
        "description": "Gateway inteligente Synteck",
        "heartbeat_interval_sec": 10,
        "log_level": "INFO",
    },
    "northbound": {
        "mqtt": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 1883,
            "username": "",
            "password": "",
            "keepalive": 30,
            "use_tls": False,
            "topic_telemetry": "v1/gateways/{id}/telemetry",
            "topic_presence": "v1/gateways/{id}/presence",
            "topic_alarms": "v1/gateways/{id}/alarms",
            "topic_commands": "v1/gateways/{id}/commands",
            "topic_ack": "v1/gateways/{id}/ack",
        },
        "http_fallback": {
            "enabled": False,
            "url": "",
            "auth_token": "",
            "timeout_sec": 5,
        },
    },
    "store_and_forward": {
        "db_path": "data/buffer.db",
        "max_records": 200000,
        "batch_size": 50,
        "flush_interval_sec": 2.0,
        "wal_mode": True,
    },
    "rule_engine": {
        "deadband_percent": 0.2,
        "force_publish_sec": 30,
        "alarms": [],
    },
    "drivers": {
        "modbus_tcp": [],
        "modbus_rtu": [],
        "mqtt_sub": [],
        "rpi_gpio": {
            "enabled": False,
            "pins": [],
        },
    },
    "web": {
        "enabled": True,
        "host": "0.0.0.0",
        "port": 5000,
        "title": "Synteck Intelligent Edge Gateway",
    },
}

def deep_merge(base: dict, update: dict) -> dict:
    """Combina recursivamente dos diccionarios conservando valores por defecto."""
    result = base.copy()
    for key, value in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """Carga configuración desde archivo YAML con fallback a valores por defecto."""
    config = DEFAULT_CONFIG.copy()

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if loaded and isinstance(loaded, dict):
                    config = deep_merge(config, loaded)
        except Exception as e:
            print(f"[CONFIG] Error leyendo {config_path}: {e}. Usando defaults.")
    else:
        print(f"[CONFIG] Archivo {config_path} no encontrado. Creando plantilla...")
        try:
            os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(DEFAULT_CONFIG, f, sort_keys=False)
        except Exception as e:
            print(f"[CONFIG] No se pudo crear {config_path}: {e}")

    # Sobrescrituras por variables de entorno (útil para despliegues desatendidos)
    if "GATEWAY_ID" in os.environ:
        config["gateway"]["id"] = os.environ["GATEWAY_ID"]
    if "MQTT_HOST" in os.environ:
        config["northbound"]["mqtt"]["host"] = os.environ["MQTT_HOST"]
    if "MQTT_PORT" in os.environ:
        config["northbound"]["mqtt"]["port"] = int(os.environ["MQTT_PORT"])
    if "MQTT_USER" in os.environ:
        config["northbound"]["mqtt"]["username"] = os.environ["MQTT_USER"]
    if "MQTT_PASS" in os.environ:
        config["northbound"]["mqtt"]["password"] = os.environ["MQTT_PASS"]

    return config
