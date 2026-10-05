import time
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger("gateway.rules")

class RuleEngine:
    """
    Motor de Reglas Inteligente en el Borde (Edge Intelligence).
    - Report by Exception (Deadband): evita saturar la red si las variables no cambian.
    - Detección de umbrales y transiciones de alarma en tiempo real directo en la Pi.
    - Transformación y escalado de datos.
    """

    def __init__(self, config: Dict[str, Any]):
        self.deadband_percent = float(config.get("deadband_percent", 0.2))
        self.force_publish_sec = float(config.get("force_publish_sec", 30))
        self.raw_alarms = config.get("alarms", [])

        # Estado en memoria: {tag_name: {"value": val, "time": ts}}
        self._tag_states: Dict[str, Dict[str, Any]] = {}

        # Estado de alarmas: {alarm_id: {"active": bool, "last_triggered": ts}}
        self._alarm_states: Dict[str, Dict[str, Any]] = {}
        for alm in self.raw_alarms:
            self._alarm_states[alm["id"]] = {"active": False, "last_triggered": 0}

    def evaluate_tag(self, tag_name: str, value: Any, timestamp: Optional[float] = None) -> Dict[str, Any]:
        """
        Evalúa un tag para determinar si debe publicarse (Deadband/Timeout)
        y revisa alarmas asociadas.
        """
        now = timestamp or time.time()
        should_publish = False

        prev = self._tag_states.get(tag_name)
        if prev is None:
            # Primera vez que vemos este tag -> publicar
            should_publish = True
            self._tag_states[tag_name] = {"value": value, "time": now}
        else:
            prev_val = prev["value"]
            elapsed = now - prev["time"]

            # Comprobar timeout de publicación forzada
            if elapsed >= self.force_publish_sec:
                should_publish = True
                self._tag_states[tag_name] = {"value": value, "time": now}
            elif isinstance(value, (int, float)) and isinstance(prev_val, (int, float)):
                # Evaluación de banda muerta (Deadband)
                delta = abs(value - prev_val)
                ref = abs(prev_val) if prev_val != 0 else 1.0
                pct = (delta / ref) * 100.0

                if pct >= self.deadband_percent:
                    should_publish = True
                    self._tag_states[tag_name] = {"value": value, "time": now}
            elif value != prev_val:
                # Variable discreta / string cambió
                should_publish = True
                self._tag_states[tag_name] = {"value": value, "time": now}

        # Evaluar alarmas asociadas a este tag
        alarm_events = self._evaluate_alarms(tag_name, value, now)

        return {
            "tag": tag_name,
            "value": value,
            "timestamp": now,
            "should_publish": should_publish,
            "alarm_events": alarm_events,
        }

    def _evaluate_alarms(self, tag_name: str, value: Any, now: float) -> List[Dict[str, Any]]:
        events = []
        for alm in self.raw_alarms:
            if alm.get("tag") != tag_name:
                continue

            cond = alm.get("condition", ">")
            thresh = alm.get("threshold", 0)
            alm_id = alm["id"]
            severity = alm.get("severity", "WARNING")
            msg = alm.get("message", f"Alarma en {tag_name}")

            is_breached = False
            try:
                val_num = float(value)
                thresh_num = float(thresh)
                if cond == ">":
                    is_breached = val_num > thresh_num
                elif cond == ">=":
                    is_breached = val_num >= thresh_num
                elif cond == "<":
                    is_breached = val_num < thresh_num
                elif cond == "<=":
                    is_breached = val_num <= thresh_num
                elif cond == "==":
                    is_breached = val_num == thresh_num
                elif cond == "!=":
                    is_breached = val_num != thresh_num
            except (ValueError, TypeError):
                continue

            current_active = self._alarm_states[alm_id]["active"]

            # Transición CLEARED -> ACTIVE
            if is_breached and not current_active:
                self._alarm_states[alm_id] = {"active": True, "last_triggered": now}
                event = {
                    "alarm_id": alm_id,
                    "tag": tag_name,
                    "value": value,
                    "threshold": thresh,
                    "severity": severity,
                    "state": "ACTIVE",
                    "message": msg,
                    "timestamp": now,
                }
                events.append(event)
                logger.warning(f"🚨 [ALARMA DISPARADA] {alm_id} ({tag_name}={value} {cond} {thresh}) - {msg}")

            # Transición ACTIVE -> CLEARED
            elif not is_breached and current_active:
                self._alarm_states[alm_id] = {"active": False, "last_triggered": now}
                event = {
                    "alarm_id": alm_id,
                    "tag": tag_name,
                    "value": value,
                    "threshold": thresh,
                    "severity": severity,
                    "state": "CLEARED",
                    "message": f"Normalizado: {msg}",
                    "timestamp": now,
                }
                events.append(event)
                logger.info(f"✅ [ALARMA NORMALIZADA] {alm_id} ({tag_name}={value})")

        return events

    def get_active_alarms(self) -> List[Dict[str, Any]]:
        active = []
        for alm in self.raw_alarms:
            alm_id = alm["id"]
            state = self._alarm_states.get(alm_id, {})
            if state.get("active"):
                active.append({**alm, "last_triggered": state.get("last_triggered")})
        return active
