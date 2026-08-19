"""
Configuración de pytest.

Los tests corren contra una base PostgreSQL real y descartable
(`<base>_test`), creada al arrancar la sesión de tests y migrada con
Alembic: así se prueban también los triggers y los UNIQUE, que son parte
de las garantías del sistema y no existirían con SQLite.

Cada test corre dentro de una transacción que se revierte al terminar,
así que el orden de ejecución no importa.
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from config import settings

# URL de la base de tests: la misma instancia, otra base de datos.
URL_TEST = settings.DATABASE_URL.rsplit("/", 1)[0] + "/soleil_test"


@pytest.fixture(scope="session")
def engine_test():
    """Crea la base de tests, la migra con Alembic y la deja lista."""
    from alembic import command
    from alembic.config import Config

    # Conexión a la base 'postgres' para poder crear/borrar la de tests.
    admin_url = settings.DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as con:
        con.execute(text("DROP DATABASE IF EXISTS soleil_test WITH (FORCE)"))
        con.execute(text("CREATE DATABASE soleil_test"))
    admin.dispose()

    # Alembic lee la URL de settings: se apunta a la base de tests.
    os.environ["DATABASE_URL"] = URL_TEST
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", URL_TEST)
    command.upgrade(config, "head")

    engine = create_engine(URL_TEST, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine_test) -> Session:
    """
    Sesión aislada por test.

    join_transaction_mode="create_savepoint" hace que los commit() de los
    services se traduzcan en savepoints: el rollback final los descarta
    todos y la base queda intacta para el test siguiente.
    """
    conexion = engine_test.connect()
    transaccion = conexion.begin()
    sesion = Session(bind=conexion, join_transaction_mode="create_savepoint")

    yield sesion

    sesion.close()
    transaccion.rollback()
    conexion.close()


class _SesionDeTest:
    """
    La sesión del test, con `close()` desactivado.

    Los middlewares no pueden usar `Depends`, así que abren y cierran la suya.
    Acá se les pasa la del test —la de ellos no vería nada, porque los datos
    viven en una transacción que nunca se commitea— y se le saca el `close()`,
    que cerraría la sesión que el fixture todavía necesita.
    """

    def __init__(self, sesion):
        self._sesion = sesion

    def __getattr__(self, nombre):
        return getattr(self._sesion, nombre)

    def close(self):
        pass


@pytest.fixture
def client(db, monkeypatch) -> TestClient:
    """Cliente HTTP con la sesión de test inyectada en lugar de la real."""
    from app.core.database import get_db
    from app.middleware import auth_refresh_middleware
    from config import settings
    from main import app

    # `AuthRefreshMiddleware` consulta la sesión en CADA request para correr la
    # ventana de inactividad. Con su propia SessionLocal no vería el login del
    # test y trataría toda sesión como inexistente: 401 y cookies borradas en
    # cualquier test que navegue autenticado.
    monkeypatch.setattr(auth_refresh_middleware, "SessionLocal", lambda: _SesionDeTest(db))

    # El middleware de dispositivos usa su propia SessionLocal (fuera de la
    # transacción del test): se apaga para no ensuciar la base. Los endpoints
    # de dispositivos igual funcionan vía Depends(get_current_device), que sí
    # usa la sesión inyectada.
    settings.DEVICE_MIDDLEWARE_ENABLED = False

    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ============================================================================
# Datos de prueba
# ============================================================================


@pytest.fixture
def roles(db):
    """Los 6 roles del sistema, como los deja el seed."""
    from app.core.permisos import ROLES_SISTEMA
    from app.core.utils import ahora_db
    from app.models.rol import Rol

    creados = {}
    for nombre in ROLES_SISTEMA:
        rol = Rol(
            nombre=nombre, descripcion=nombre, es_sistema=True, activo=True,
            created_at=ahora_db(), updated_at=ahora_db(),
        )
        db.add(rol)
        creados[nombre] = rol
    db.flush()
    return creados


@pytest.fixture
def crear_usuario(db, roles):
    """Fábrica de usuarios de prueba."""
    from app.core.utils import ahora_db
    from app.models.usuario import Usuario
    from app.services.auth import hash_password

    def _crear(username: str, rol: str, password: str = "Test1234!", **kwargs):
        usuario = Usuario(
            username=username,
            nombre=kwargs.pop("nombre", username.title()),
            email=kwargs.pop("email", None),
            password_hash=hash_password(password),
            rol_id=roles[rol].id,
            activo=kwargs.pop("activo", True),
            created_at=ahora_db(),
            updated_at=ahora_db(),
            ultimo_acceso=kwargs.pop("ultimo_acceso", ahora_db()),
            **kwargs,
        )
        db.add(usuario)
        db.flush()
        return usuario

    return _crear


@pytest.fixture
def dar_permiso(db):
    """Otorga un permiso a un rol o a un usuario (override)."""
    from app.models.permiso import RolPermiso, UsuarioPermiso

    def _dar(*, rol_id=None, usuario_id=None, modulo, recurso=None, **acciones):
        modelo = RolPermiso if rol_id else UsuarioPermiso
        fila = modelo(
            modulo=modulo.value if hasattr(modulo, "value") else modulo,
            recurso=recurso.value if hasattr(recurso, "value") else recurso,
            **{f"puede_{a}": v for a, v in acciones.items()},
        )
        if rol_id:
            fila.rol_id = rol_id
        else:
            fila.usuario_id = usuario_id
        db.add(fila)
        db.flush()
        return fila

    return _dar


@pytest.fixture
def crear_punto_de_venta(db):
    """
    Fábrica de puntos de venta.

    Vive acá y no en un módulo de tests porque desde el control de stock la
    necesitan varios: el stock, los remitos y las auditorías son siempre
    de una ubicación, así que casi ningún test del módulo se arma sin esto.
    """
    from app.core.utils import ahora_db
    from app.models.punto_de_venta import PuntoDeVenta, TipoPuntoVenta

    def _crear(codigo: str, nombre: str | None = None, tipo=TipoPuntoVenta.LOCAL):
        punto = PuntoDeVenta(
            codigo=codigo.upper(),
            nombre=nombre or f"Punto {codigo.upper()}",
            tipo=tipo,
            activo=True,
            created_at=ahora_db(),
            updated_at=ahora_db(),
        )
        db.add(punto)
        db.flush()
        return punto

    return _crear


@pytest.fixture
def punto_de_venta(crear_punto_de_venta):
    """Un local cualquiera, para los tests que solo necesitan una ubicación."""
    return crear_punto_de_venta("LOC", "Local de prueba")


@pytest.fixture
def login(client):
    """Hace login y devuelve los headers con el Bearer token."""

    def _login(username: str, password: str = "Test1234!") -> dict:
        resp = client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    return _login
