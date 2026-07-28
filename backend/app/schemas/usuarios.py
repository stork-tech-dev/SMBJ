"""
Schemas del módulo de usuarios.

Ningún schema de respuesta incluye `password_hash` ni `clave_especial_hash`:
se declaran campo por campo, nunca con un volcado del modelo completo.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.roles import RolResponse


class UsuarioCrear(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    nombre: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=8, max_length=128)
    rol_id: int
    email: EmailStr | None = None


class UsuarioEditar(BaseModel):
    """Todo opcional: se actualiza solo lo que llega."""

    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    email: EmailStr | None = None
    rol_id: int | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


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
