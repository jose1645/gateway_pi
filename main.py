import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("GatewayPi")

def main():
    logger.info("Iniciando Gateway Central Inteligente en Raspberry Pi...")
    logger.info("Sistema listo para inicializar drivers locales y enlace remoto.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Deteniendo Gateway...")

if __name__ == "__main__":
    main()
