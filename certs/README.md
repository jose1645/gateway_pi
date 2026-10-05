# Certificados de AWS IoT Core

Coloca en este directorio los certificados X.509 descargados desde la consola de AWS IoT Core:

- `AmazonRootCA1.pem` (Certificado raíz de confianza de Amazon)
- `<device_id>-cert.pem.crt` (Certificado del dispositivo / Thing)
- `<device_id>-private.pem.key` (Llave privada del dispositivo)

> **Nota de Seguridad**: Las llaves privadas (`*.key`) y certificados de cliente (`*.crt`) están ignorados en `.gitignore` para no exponer credenciales al repositorio público.
