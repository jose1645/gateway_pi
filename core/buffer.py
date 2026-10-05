import sqlite3
import json
import os
import time
from typing import List, Dict, Any, Tuple
import logging

logger = logging.getLogger("gateway.buffer")

class LocalBuffer:
    """
    Buffer local de alta resiliencia basado en SQLite con modo WAL (Write-Ahead Logging).
    Permite almacenar telemetría y alarmas cuando se pierde conectividad con el servidor central,
    y retransmitir por ráfagas (Store & Forward) sin degradar la tarjeta MicroSD.
    """

    def __init__(self, db_path: str = "data/buffer.db", max_records: int = 200000, wal_mode: bool = True):
        self.db_path = db_path
        self.max_records = max_records
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._init_db(wal_mode)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self, wal_mode: bool):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if wal_mode:
                cursor.execute("PRAGMA journal_mode = WAL;")
                cursor.execute("PRAGMA synchronous = NORMAL;")
                cursor.execute("PRAGMA cache_size = -2000;") # ~2MB de caché en RAM

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    payload TEXT NOT NULL,
                    priority INTEGER DEFAULT 0
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_telemetry_created 
                ON telemetry_queue (priority DESC, created_at ASC)
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alarm_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    alarm_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    state TEXT NOT NULL,
                    message TEXT NOT NULL,
                    synced INTEGER DEFAULT 0
                )
            """)
            conn.commit()
            logger.info(f"Buffer SQLite inicializado en '{self.db_path}' (WAL: {wal_mode})")

    def enqueue(self, payload: Dict[str, Any], priority: int = 0) -> int:
        """Encola un payload de telemetría para retransmisión."""
        try:
            payload_str = json.dumps(payload)
            now = time.time()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO telemetry_queue (created_at, payload, priority) VALUES (?, ?, ?)",
                    (now, payload_str, priority)
                )
                record_id = cursor.lastrowid
                conn.commit()

                # Control de desbordamiento (Protección de almacenamiento de la Pi)
                if record_id % 500 == 0:
                    self._check_and_purge(conn)

                return record_id
        except Exception as e:
            logger.error(f"Error encolando en buffer local: {e}")
            return -1

    def peek_batch(self, limit: int = 50) -> List[Tuple[int, Dict[str, Any]]]:
        """Obtiene un lote de registros pendientes sin eliminarlos."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, payload FROM telemetry_queue ORDER BY priority DESC, created_at ASC LIMIT ?",
                    (limit,)
                )
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    try:
                        data = json.loads(row["payload"])
                        results.append((row["id"], data))
                    except Exception:
                        continue
                return results
        except Exception as e:
            logger.error(f"Error leyendo lote de buffer: {e}")
            return []

    def ack_batch(self, ids: List[int]) -> int:
        """Elimina del buffer los registros que ya fueron confirmados por el broker."""
        if not ids:
            return 0
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ",".join("?" * len(ids))
                cursor.execute(f"DELETE FROM telemetry_queue WHERE id IN ({placeholders})", ids)
                deleted = cursor.rowcount
                conn.commit()
                return deleted
        except Exception as e:
            logger.error(f"Error confirmando lote en buffer: {e}")
            return 0

    def record_alarm_event(self, alarm_id: str, tag: str, severity: str, state: str, message: str):
        """Registra una alarma en el histórico local."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO alarm_events (created_at, alarm_id, tag, severity, state, message, synced)
                       VALUES (?, ?, ?, ?, ?, ?, 0)""",
                    (time.time(), alarm_id, tag, severity, state, message)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Error registrando evento de alarma: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Devuelve estadísticas en tiempo real del buffer local."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM telemetry_queue")
                pending_count = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM alarm_events")
                alarms_count = cursor.fetchone()[0]

            file_size_kb = 0
            if os.path.exists(self.db_path):
                file_size_kb = round(os.path.getsize(self.db_path) / 1024, 2)

            return {
                "pending_telemetry": pending_count,
                "total_alarms": alarms_count,
                "db_size_kb": file_size_kb,
                "max_records": self.max_records,
            }
        except Exception as e:
            logger.error(f"Error obteniendo estadísticas de buffer: {e}")
            return {"pending_telemetry": 0, "total_alarms": 0, "db_size_kb": 0, "max_records": self.max_records}

    def _check_and_purge(self, conn: sqlite3.Connection):
        """Si excede max_records, elimina los registros más antiguos (Buffer circular)."""
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM telemetry_queue")
        total = cursor.fetchone()[0]
        if total > self.max_records:
            excess = total - self.max_records + 1000
            cursor.execute("""
                DELETE FROM telemetry_queue WHERE id IN (
                    SELECT id FROM telemetry_queue ORDER BY created_at ASC LIMIT ?
                )
            """, (excess,))
            conn.commit()
            logger.warning(f"Buffer local excedió {self.max_records} registros. Purgados {excess} más antiguos.")
