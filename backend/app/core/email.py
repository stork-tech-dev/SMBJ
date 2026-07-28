"""
Envío de emails por SMTP.

Si no hay SMTP configurado (caso normal en desarrollo), el mensaje se
escribe en el log en lugar de enviarse: el flujo de recuperación de
contraseña se puede probar entero sin servidor de correo.
"""

import logging
import smtplib
from email.message import EmailMessage

from config import settings

logger = logging.getLogger(__name__)


def smtp_configurado() -> bool:
    """True si hay servidor SMTP definido en el entorno."""
    return bool(settings.SMTP_HOST)


def enviar_email(destinatario: str, asunto: str, cuerpo: str) -> bool:
    """
    Envía un email de texto plano.

    Returns:
        True si se envió, False si solo se registró en el log.
    """
    if not smtp_configurado():
        logger.warning(
            "SMTP no configurado. Email NO enviado:\n"
            "  Para: %s\n  Asunto: %s\n  Cuerpo:\n%s",
            destinatario,
            asunto,
            cuerpo,
        )
        return False

    mensaje = EmailMessage()
    mensaje["From"] = settings.SMTP_FROM
    mensaje["To"] = destinatario
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as servidor:
        if settings.SMTP_TLS:
            servidor.starttls()
        if settings.SMTP_USER:
            servidor.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
        servidor.send_message(mensaje)

    logger.info("Email enviado a %s: %s", destinatario, asunto)
    return True


def enviar_reset_password(destinatario: str, nombre: str, token: str) -> bool:
    """Email de recuperación de contraseña con el link de reseteo."""
    url = f"{settings.APP_URL}/reset-password?token={token}"
    cuerpo = (
        f"Hola {nombre}:\n\n"
        f"Recibimos un pedido para restablecer tu contraseña de {settings.APP_NAME}.\n\n"
        f"Entrá a este link para definir una nueva (vence en 30 minutos):\n{url}\n\n"
        "Si no pediste esto, ignorá el mensaje: tu contraseña sigue igual.\n"
    )
    return enviar_email(destinatario, f"{settings.APP_NAME} — Restablecer contraseña", cuerpo)
