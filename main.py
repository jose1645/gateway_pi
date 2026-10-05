import sys
import time
import signal
import logging
from core.config import load_config
from core.logger import setup_logger
from core.buffer import LocalBuffer
from core.rule_engine import RuleEngine
from core.observability import SystemMonitor
from northbound.aws_iot_bridge import AwsIotBridge

logger = setup_logger("GatewayPi")

class GatewayApp:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.running = False

        # 1. Almacenamiento local resiliente
        buf_cfg = self.config.get("store_and_forward", {})
        self.buffer = LocalBuffer(
            db_path=buf_cfg.get("db_path", "data/buffer.db"),
            max_records=buf_cfg.get("max_records", 200000),
            wal_mode=buf_cfg.get("wal_mode", True)
        )

        # 2. Motor de reglas y alarmas de borde
        self.rule_engine = RuleEngine(self.config.get("rule_engine", {}))

        # 3. Monitor de salud y observabilidad de hardware
        self.monitor = SystemMonitor()

        # 4. Puente seguro hacia AWS IoT Core (Puerto 443 + ALPN x-amzn-mqtt-ca)
        self.bridge = AwsIotBridge(
            config=self.config,
            command_callback=self.on_downlink_command
        )

        self.last_health_publish = 0
        self.last_buffer_flush = 0
        self.obs_interval = self.config.get("observability", {}).get("publish_interval_sec", 60)
        self.flush_interval = buf_cfg.get("flush_interval_sec", 2.0)
        self.batch_size = buf_cfg.get("batch_size", 50)

    def on_downlink_command(self, command: dict):
        """Maneja comandos recibidos desde el SCADA o Nube vía AWS IoT Core."""
        action = command.get("action", "")
        target = command.get("target", "")
        value = command.get("value", None)
        logger.info(f"⚙️ [COMANDO RECIBIDO] Acción: '{action}', Target: '{target}', Valor: {value}")

        # Aquí los drivers responderán a comandos de escritura en PLCs o GPIO
        if action == "PING":
            logger.info("📡 Respondiendo a Ping desde AWS...")
            self.bridge.publish_telemetry({"response": "PONG", "echo_time": time.time()})

    def run(self):
        self.running = True
        logger.info("=" * 60)
        logger.info(f"🚀 INICIANDO SYNTECK INDUSTRIAL EDGE GATEWAY")
        logger.info(f"   ID Dispositivo : {self.config.get('gateway', {}).get('id')}")
        logger.info(f"   Planta         : {self.config.get('gateway', {}).get('plant_slug')}")
        logger.info(f"   Puerto AWS IoT : {self.bridge.port} (ALPN: {'x-amzn-mqtt-ca' if self.bridge.port == 443 else 'Standard'})")
        logger.info("=" * 60)

        # Conectar a AWS IoT Core
        self.bridge.start()

        while self.running:
            try:
                now = time.time()

                # ── OBSERVABILIDAD: REPORTE PERIÓDICO DE SALUD ──────────────────
                if now - self.last_health_publish >= self.obs_interval:
                    metrics = self.monitor.collect_metrics()
                    buf_stats = self.buffer.get_stats()
                    health_payload = {
                        "type": "HEALTH_OBSERVABILITY",
                        "metrics": metrics,
                        "buffer_stats": buf_stats,
                        "connection_port": self.bridge.port,
                        "uptime": metrics["uptime_seconds"],
                    }

                    # Publicar por AWS IoT si está online, o guardar en buffer
                    if self.bridge.is_connected:
                        success = self.bridge.publish_telemetry(health_payload)
                        if success:
                            temp_str = f"{metrics['cpu_temp_celsius']}°C" if metrics['cpu_temp_celsius'] else "N/A"
                            logger.info(f"🩺 [HEALTH] Telemetría enviada a AWS: CPU={metrics['cpu_percent']}%, Temp={temp_str}, RAM={metrics['ram']['percent']}%, Buffer={buf_stats['pending_telemetry']} pnd")
                    else:
                        logger.warning("⚠️ AWS IoT Offline. Guardando métricas en buffer local...")
                        self.buffer.enqueue(health_payload)

                    self.last_health_publish = now

                # ── STORE & FORWARD: VACIAR BUFFER LOCAL HACIA AWS IOT ──────────
                if self.bridge.is_connected and (now - self.last_buffer_flush >= self.flush_interval):
                    batch = self.buffer.peek_batch(limit=self.batch_size)
                    if batch:
                        logger.info(f"📦 [STORE & FORWARD] Vaciando {len(batch)} paquetes acumulados hacia AWS IoT...")
                        sent_ids = []
                        for record_id, payload in batch:
                            if self.bridge.publish_telemetry(payload):
                                sent_ids.append(record_id)
                            else:
                                break  # Detener ráfaga si hay error de transmisión
                        
                        if sent_ids:
                            self.buffer.ack_batch(sent_ids)
                            logger.info(f"✅ [STORE & FORWARD] {len(sent_ids)} registros entregados y liberados del buffer.")
                    
                    self.last_buffer_flush = now

                time.sleep(0.5)

            except Exception as e:
                logger.error(f"Error en bucle principal: {e}")
                time.sleep(2)

    def stop(self):
        logger.info("Deteniendo Gateway y cerrando enlaces...")
        self.running = False
        self.bridge.stop()
        logger.info("Gateway detenido limpiamente.")

def main():
    app = GatewayApp()

    def signal_handler(sig, frame):
        app.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    app.run()

if __name__ == "__main__":
    main()
