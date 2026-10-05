import os
import sys
import time
import subprocess
import logging
from typing import Dict, Any, Optional

try:
    import psutil
except ImportError:
    psutil = None

logger = logging.getLogger("gateway.observability")

class SystemMonitor:
    """
    Monitor de salud y observabilidad del hardware (Raspberry Pi 3 y PC Local).
    Monitorea métricas críticas del sistema para anticipar fallas en campo:
    - Temperatura del SoC (Thermal Throttling)
    - Detección de bajo voltaje (Undervoltage - causa #1 de caídas en plantas)
    - Consumo de RAM (clave para los 1GB de la Pi 3)
    - Espacio y desgaste de la MicroSD
    - Uptime y latencia de conexión
    """

    def __init__(self):
        self.start_time = time.time()
        self.is_linux = sys.platform.startswith("linux")
        self.is_raspberry_pi = self._detect_raspberry_pi()
        logger.info(f"Monitor de observabilidad iniciado (Raspberry Pi detectada: {self.is_raspberry_pi})")

    def _detect_raspberry_pi(self) -> bool:
        if not self.is_linux:
            return False
        try:
            if os.path.exists("/proc/device-tree/model"):
                with open("/proc/device-tree/model", "r") as f:
                    model = f.read().lower()
                    return "raspberry pi" in model
        except Exception:
            pass
        return False

    def get_cpu_temperature(self) -> Optional[float]:
        """Obtiene la temperatura de la CPU en grados Celsius."""
        if self.is_raspberry_pi:
            # 1. Método térmico nativo del kernel de Linux
            thermal_path = "/sys/class/thermal/thermal_zone0/temp"
            if os.path.exists(thermal_path):
                try:
                    with open(thermal_path, "r") as f:
                        temp_raw = int(f.read().strip())
                        return round(temp_raw / 1000.0, 1)
                except Exception:
                    pass

            # 2. Comando vcgencmd en Raspberry Pi OS
            try:
                out = subprocess.check_output(["vcgencmd", "measure_temp"], timeout=1).decode("utf-8")
                # Salida ejemplo: temp=48.2'C
                return float(out.replace("temp=", "").replace("'C\n", "").strip())
            except Exception:
                pass

        # Fallback para PCs / Laptops con sensores psutil si están disponibles
        if psutil and hasattr(psutil, "sensors_temperatures"):
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        if entries:
                            return round(entries[0].current, 1)
            except Exception:
                pass

        return None

    def get_throttled_state(self) -> Dict[str, Any]:
        """
        Diagnostica si la Raspberry Pi ha sufrido caída de voltaje o throttling térmico.
        Usa 'vcgencmd get_throttled'.
        """
        result = {
            "undervoltage_detected": False,
            "frequency_capped": False,
            "throttling_active": False,
            "undervoltage_occurred_past": False,
            "raw_hex": "0x0"
        }
        if not self.is_raspberry_pi:
            return result

        try:
            out = subprocess.check_output(["vcgencmd", "get_throttled"], timeout=1).decode("utf-8")
            # Salida típica: throttled=0x0 o throttled=0x50000 (undervoltage ocurrido)
            val_hex = out.split("=")[-1].strip()
            val = int(val_hex, 16)
            result["raw_hex"] = val_hex
            result["undervoltage_detected"] = bool(val & 0x1)
            result["frequency_capped"] = bool(val & 0x2)
            result["throttling_active"] = bool(val & 0x4)
            result["undervoltage_occurred_past"] = bool(val & 0x50000)
        except Exception:
            pass

        return result

    def collect_metrics(self) -> Dict[str, Any]:
        """Recopila todas las métricas de salud del nodo Edge."""
        now = time.time()
        uptime_sec = round(now - self.start_time, 1)

        # CPU y Memoria
        cpu_pct = 0.0
        ram_used_mb = 0.0
        ram_total_mb = 0.0
        ram_pct = 0.0
        disk_free_gb = 0.0
        disk_pct = 0.0

        if psutil:
            try:
                cpu_pct = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory()
                ram_used_mb = round((mem.total - mem.available) / (1024 * 1024), 1)
                ram_total_mb = round(mem.total / (1024 * 1024), 1)
                ram_pct = mem.percent

                disk = psutil.disk_usage(os.path.abspath("."))
                disk_free_gb = round(disk.free / (1024 * 1024 * 1024), 2)
                disk_pct = disk.percent
            except Exception as e:
                logger.error(f"Error leyendo psutil: {e}")

        # Temperatura del SoC
        cpu_temp = self.get_cpu_temperature()

        # Diagnóstico Pi
        throttled_info = self.get_throttled_state()

        # Load average en Linux
        load_avg = [0.0, 0.0, 0.0]
        if hasattr(os, "getloadavg"):
            try:
                load_avg = [round(x, 2) for x in os.getloadavg()]
            except Exception:
                pass

        return {
            "uptime_seconds": uptime_sec,
            "cpu_percent": cpu_pct,
            "cpu_temp_celsius": cpu_temp,
            "load_average_1m": load_avg[0],
            "load_average_5m": load_avg[1],
            "ram": {
                "used_mb": ram_used_mb,
                "total_mb": ram_total_mb,
                "percent": ram_pct,
            },
            "disk": {
                "free_gb": disk_free_gb,
                "percent_used": disk_pct,
            },
            "hardware": {
                "is_raspberry_pi": self.is_raspberry_pi,
                "platform": sys.platform,
                "undervoltage_detected": throttled_info["undervoltage_detected"],
                "throttling_active": throttled_info["throttling_active"],
            },
            "timestamp": now,
        }
