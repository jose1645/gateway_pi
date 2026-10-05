import logging
import os
import sys
from logging.handlers import RotatingFileHandler

class ColoredFormatter(logging.Formatter):
    """Formateador ANSI con colores para terminales industriales."""
    COLORS = {
        logging.DEBUG: "\033[36m",    # Cian
        logging.INFO: "\033[32m",     # Verde
        logging.WARNING: "\033[33m",  # Amarillo
        logging.ERROR: "\033[31m",    # Rojo
        logging.CRITICAL: "\033[41m\033[37m", # Fondo Rojo, texto Blanco
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        time_str = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        lvl = f"{record.levelname:<7}"
        msg = record.getMessage()
        return f"\033[90m[{time_str}]\033[0m {color}{self.BOLD}{lvl}{self.RESET} \033[35m[{record.name}]\033[0m {msg}"

def setup_logger(name: str = "gateway", log_level: str = "INFO", log_dir: str = "logs") -> logging.Logger:
    """Configura logger con salida simultánea a consola y archivo rotativo."""
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "gateway.log")

    logger = logging.getLogger(name)
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(level)

    # Evitar duplicar handlers si ya existen
    if not logger.handlers:
        # Handler de consola con colores
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(ColoredFormatter())
        logger.addHandler(console_handler)

        # Handler de archivo (Rotativo: 5 MB por archivo, máximo 3 respaldos para cuidar la MicroSD)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger
