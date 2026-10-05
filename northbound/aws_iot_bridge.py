import os
import ssl
import json
import time
import logging
import urllib.request
from typing import Dict, Any, Optional, Callable
import paho.mqtt.client as mqtt

logger = logging.getLogger("gateway.aws_bridge")

AWS_ROOT_CA_URL = "https://www.amazontrust.com/repository/AmazonRootCA1.pem"

class AwsIotBridge:
    """
    Puente de enlace Northbound industrial hacia AWS IoT Core.
    Soporta conexión TLS segura por el puerto 443 (ALPN x-amzn-mqtt-ca)
    para atravesar firewalls corporativos/industriales que bloquean el puerto 8883.
    """

    def __init__(self, config: Dict[str, Any], command_callback: Optional[Callable] = None):
        self.config = config
        self.gateway_id = config.get("gateway", {}).get("id", "GW-PI-001")
        self.partner = config.get("gateway", {}).get("partner", "inmapro")
        self.client_slug = config.get("gateway", {}).get("client", "admin")
        self.plant_slug = config.get("gateway", {}).get("plant_slug", "eficienciaenergeticahome")

        # Configuración AWS
        aws_cfg = config.get("northbound", {}).get("aws_iot", {})
        self.endpoint = aws_cfg.get("endpoint", "")
        self.port = int(aws_cfg.get("port", 443))  # 443 por defecto para firewalls industriales
        self.certs_dir = aws_cfg.get("certs_dir", "certs")
        self.cert_file = aws_cfg.get("cert_file", f"{self.gateway_id}-cert.pem.crt")
        self.key_file = aws_cfg.get("key_file", f"{self.gateway_id}-private.pem.key")
        self.root_ca_file = aws_cfg.get("root_ca_file", "AmazonRootCA1.pem")
        self.keepalive = int(aws_cfg.get("keepalive", 30))

        # Tópicos estructurados
        # Formato: {partner}/{client}/{plant}/{device_id}/[telemetry|presence|alarms|commands]
        self.base_topic = f"{self.partner}/{self.client_slug}/{self.plant_slug}/{self.gateway_id}"
        self.topic_telemetry = f"{self.base_topic}/telemetry"
        self.topic_presence = f"{self.base_topic}/presence"
        self.topic_alarms = f"{self.base_topic}/alarms"
        self.topic_commands = f"{self.base_topic}/commands"
        self.topic_sub = f"{self.base_topic}/#"

        self.command_callback = command_callback
        self.is_connected = False
        self._client: Optional[mqtt.Client] = None

    def _ensure_root_ca(self) -> str:
        os.makedirs(self.certs_dir, exist_ok=True)
        ca_path = os.path.join(self.certs_dir, self.root_ca_file)
        if not os.path.exists(ca_path):
            logger.info(f"Descargando Root CA de Amazon desde {AWS_ROOT_CA_URL}...")
            try:
                urllib.request.urlretrieve(AWS_ROOT_CA_URL, ca_path)
                logger.info(f"Root CA guardado exitosamente en: {ca_path}")
            except Exception as e:
                logger.error(f"Error descargando AmazonRootCA1.pem: {e}")
        return ca_path

    def _create_ssl_context(self) -> ssl.SSLContext:
        """
        Crea contexto SSL para AWS IoT.
        Si se usa el puerto 443, configura ALPN con 'x-amzn-mqtt-ca'
        permitiendo autenticación mutua por certificados X.509 en puerto HTTPS.
        """
        ca_path = self._ensure_root_ca()
        cert_path = os.path.join(self.certs_dir, self.cert_file)
        key_path = os.path.join(self.certs_dir, self.key_file)

        if not os.path.exists(cert_path):
            logger.warning(f"Certificado no encontrado en: {cert_path}")
        if not os.path.exists(key_path):
            logger.warning(f"Llave privada no encontrada en: {key_path}")

        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_path)
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED

        if os.path.exists(cert_path) and os.path.exists(key_path):
            context.load_cert_chain(certfile=cert_path, keyfile=key_path)

        # ── ALPN EN PUERTO 443: TRUCO CLAVE PARA REDES INDUSTRIALES ────────
        # AWS IoT Core escucha en el puerto 443 y mediante ALPN 'x-amzn-mqtt-ca'
        # negocia MQTT con certificados cliente X.509 atravesando cualquier firewall.
        if self.port == 443:
            logger.info("Configurando TLS ALPN ['x-amzn-mqtt-ca'] en puerto 443 (Firewall Bypass)")
            context.set_alpn_protocols(["x-amzn-mqtt-ca"])

        return context

    def start(self):
        """Inicia el cliente MQTT y conecta a AWS IoT Core."""
        if not self.endpoint:
            logger.error("No se ha configurado 'endpoint' de AWS IoT Core en config.yaml")
            return

        logger.info(f"Conectando a AWS IoT Core en {self.endpoint}:{self.port} (Client ID: {self.gateway_id})...")

        try:
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=self.gateway_id
            )
        except AttributeError:
            self._client = mqtt.Client(client_id=self.gateway_id)

        # Callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # Configurar Last Will and Testament (LWT)
        # Si la Pi pierde energía o cable, AWS IoT emite automáticamente este mensaje de presencia
        lwt_payload = json.dumps({
            "device_id": self.gateway_id,
            "status": "OFFLINE",
            "reason": "CONNECTION_LOST_LWT",
            "timestamp": time.time()
        })
        self._client.will_set(self.topic_presence, payload=lwt_payload, qos=1, retain=True)

        # Configurar TLS con ALPN
        try:
            ssl_context = self._create_ssl_context()
            self._client.tls_set_context(ssl_context)
        except Exception as e:
            logger.error(f"Error configurando contexto SSL TLS: {e}")
            return

        try:
            self._client.connect_async(self.endpoint, port=self.port, keepalive=self.keepalive)
            self._client.loop_start()
        except Exception as e:
            logger.error(f"Excepción al conectar con AWS IoT Core: {e}")

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        rc_code = getattr(rc, 'value', rc)
        if rc_code == 0:
            self.is_connected = True
            logger.info(f"✅ ¡Conexión TLS Exitosa con AWS IoT Core en puerto {self.port}!")
            
            # Suscripción a tópicos autorizados por política de AWS IoT
            client.subscribe(self.topic_sub, qos=1)
            logger.info(f"📡 Suscrito a tópico de comandos: '{self.topic_sub}'")

            # Publicar presencia ONLINE
            online_payload = {
                "device_id": self.gateway_id,
                "partner": self.partner,
                "client": self.client_slug,
                "plant": self.plant_slug,
                "status": "ONLINE",
                "hardware": "Raspberry Pi 3 / Edge Gateway",
                "port_used": self.port,
                "timestamp": time.time()
            }
            self.publish_presence(online_payload)
        else:
            self.is_connected = False
            logger.error(f"❌ Falló conexión con AWS IoT Core (RC={rc_code}). Verifique certificados y políticas.")

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self.is_connected = False
        logger.warning(f"⚠️ Desconectado de AWS IoT Core. Reconectando en background... (RC={rc})")

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload_str = msg.payload.decode("utf-8")
            logger.info(f"📥 [DOWNLINK AWS] Mensaje recibido en '{topic}': {payload_str}")

            if topic.endswith("/commands") or topic == self.topic_commands:
                data = json.loads(payload_str)
                if self.command_callback:
                    self.command_callback(data)
        except Exception as e:
            logger.error(f"Error procesando mensaje entrante de AWS: {e}")

    def publish_telemetry(self, data: Dict[str, Any], qos: int = 1) -> bool:
        """Publica paquete de telemetría hacia AWS IoT Core."""
        if not self.is_connected or not self._client:
            return False

        try:
            payload = {
                "device_id": self.gateway_id,
                "partner": self.partner,
                "client": self.client_slug,
                "plant": self.plant_slug,
                "timestamp": time.time(),
                **data
            }
            payload_bytes = json.dumps(payload).encode("utf-8")
            info = self._client.publish(self.topic_telemetry, payload_bytes, qos=qos)
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.error(f"Error publicando telemetría en AWS IoT: {e}")
            return False

    def publish_alarm(self, alarm_data: Dict[str, Any], qos: int = 1) -> bool:
        """Publica evento de alarma hacia AWS IoT Core."""
        if not self.is_connected or not self._client:
            return False

        try:
            payload = {
                "device_id": self.gateway_id,
                "timestamp": time.time(),
                **alarm_data
            }
            payload_bytes = json.dumps(payload).encode("utf-8")
            info = self._client.publish(self.topic_alarms, payload_bytes, qos=qos)
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.error(f"Error publicando alarma en AWS IoT: {e}")
            return False

    def publish_presence(self, presence_data: Dict[str, Any]):
        """Publica estado de presencia."""
        if not self._client:
            return
        try:
            payload_bytes = json.dumps(presence_data).encode("utf-8")
            self._client.publish(self.topic_presence, payload_bytes, qos=1, retain=True)
        except Exception as e:
            logger.error(f"Error publicando presencia: {e}")

    def stop(self):
        if self._client:
            # Enviar offline limpio antes de apagar
            offline_payload = {
                "device_id": self.gateway_id,
                "status": "OFFLINE",
                "reason": "GRACEFUL_SHUTDOWN",
                "timestamp": time.time()
            }
            self.publish_presence(offline_payload)
            self._client.loop_stop()
            self._client.disconnect()
            self.is_connected = False
            logger.info("Puente AWS IoT detenido correctamente.")
