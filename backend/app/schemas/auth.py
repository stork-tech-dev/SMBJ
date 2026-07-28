"""Schemas de autenticación."""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class UsuarioToken(BaseModel):
    """Datos mínimos del usuario que acompañan al login."""

    id: int
    username: str
    nombre: str
    rol: str
    debe_cambiar_password: bool


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Vigencia del access token, en segundos")
    usuario: UsuarioToken


class RefreshRequest(BaseModel):
    """El refresh token puede venir en el cuerpo o en la cookie."""

    refresh_token: str | None = None


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ForgotPasswordRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)


class ResetPasswordRequest(BaseModel):
    token: str
    password_nueva: str = Field(min_length=8, max_length=128)


class CambiarPasswordRequest(BaseModel):
    """Cambio de contraseña del propio usuario logueado."""

    password_actual: str = Field(min_length=1, max_length=128)
    password_nueva: str = Field(min_length=8, max_length=128)
