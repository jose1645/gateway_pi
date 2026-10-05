# Gateway Central Inteligente - Raspberry Pi (gateway_pi)

Gateway de borde industrial diseñado para ejecutarse de forma nativa en **Raspberry Pi 3** y PCs locales (Windows/Linux) sin necesidad de contenedores Docker ni entornos virtuales.

## Propósito
Unir dispositivos de campo locales (PLCs, sensores, RTUs, puertos serie/RS485, GPIO) con la plataforma remota en la nube / SCADA Synteck.

## Estructura del Proyecto
- `main.py`: Punto de entrada del Gateway.
- `config.yaml`: Archivo de configuración central.
- `drivers/`: Drivers de adquisición local (Modbus, Serial, MQTT, GPIO, etc.).
- `requirements.txt`: Dependencias mínimas en Python.

## Ejecución
```bash
python main.py
```
