"""
Schemas del módulo de usuarios.

Ningún schema de respuesta incluye `password_hash` ni `clave_especial_hash`:
se declaran campo por campo, nunca con un volcado del modelo completo.
"""

import re
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field

from app.schemas.roles import RolResponse

# El celular se guarda como texto pero solo admite dígitos, con el prefijo
# internacional opcional que muestra el diseño ("+3512108190"). Se aceptan
# espacios, guiones y paréntesis al escribir y se descartan al normalizar:
# lo que llega a la base es siempre "+?dígitos".
_CELULAR_SEPARADORES = re.compile(r"[\s\-().]")
_CELULAR_VALIDO = re.compile(r"^\+?\d{6,19}$")


def _normalizar_celular(valor: object) -> object:
    """Limpia separadores y valida que no quede nada que no sea un número."""
    if valor is None or not isinstance(valor, str):
        return valor

    limpio = _CELULAR_SEPARADORES.sub("", valor).strip()
    if not limpio:
        return None
    if not _CELULAR_VALIDO.match(limpio):
        raise ValueError(
            "El celular solo admite números, con prefijo internacional opcional"
        )
    return limpio


# Tipo reutilizable: la misma regla en alta y edición, definida una sola vez.
# El largo lo acota el propio regex (máx. 20 con el "+"), así que no lleva
# `Field(max_length=...)`: esa restricción se aplicaría también al None de
# la unión y explota antes de validar nada.
Celular = Annotated[str | None, BeforeValidator(_normalizar_celular)]


class UsuarioCrear(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    nombre: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=8, max_length=128)
    rol_id: int
    email: EmailStr | None = None
    fecha_nacimiento: date | None = None
    celular: Celular = None
    local_asignado_id: int | None = None


class UsuarioEditar(BaseModel):
    """
    Todo opcional: se actualiza solo lo que llega.

    Los tres campos personales distinguen "no enviado" de "enviado en
    NULL" con `model_fields_set`, igual que `punto_de_venta_id` en
    dispositivos: son opcionales y hay que poder vaciarlos.
    """

    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    email: EmailStr | None = None
    rol_id: int | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    fecha_nacimiento: date | None = None
    celular: Celular = None
    local_asignado_id: int | None = None


class LocalResumen(BaseModel):
    """
    Punto de venta asignado, en la respuesta de usuarios.

    Solo `id` y `nombre`: es lo que el selector necesita para mostrarlo y
    elegirlo. El resto de los campos del punto de venta —tipo, código,
    estado— se piden a su propio endpoint cuando hacen falta, y no viajan
    duplicados en cada fila del listado de usuarios.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str


class UsuarioEstado(BaseModel):
    activo: bool


class UsuarioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    nombre: str
    rol_id: int
    rol: RolResponse
    activo: bool
    # Fecha cruda en ISO: el formato dd/mm/yyyy lo arma el frontend.
    fecha_nacimiento: date | None
    celular: str | None
    local_asignado_id: int | None
    local_asignado: LocalResumen | None
    created_at: datetime
    updated_at: datetime
    ultimo_acceso: datetime | None
    # No hay campo de hashes: ni de contraseña ni de clave especial.


class HistorialAccesoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario_id: int
    timestamp: datetime
    ip_origen: str | None
    resultado: str
    detalle: str | None


class ClaveEspecialValidar(BaseModel):
    clave: str = Field(min_length=1, max_length=128)


class ClaveEspecialResetear(BaseModel):
    clave_nueva: str = Field(min_length=8, max_length=128)


class ClaveEspecialResultado(BaseModel):
    valida: bool
