"""Tests del endpoint de consulta de auditoría y de su inmutabilidad."""

import pytest
from sqlalchemy import text

from app.core.permisos import ROL_AUDITOR, ROL_CUENTA_MAESTRA, ROL_VENDEDOR, Modulo


def test_solo_ve_auditoria_quien_tiene_el_permiso(client, crear_usuario, roles, dar_permiso, login):
    """Visible para Cuenta Maestra y Auditor; para el resto, 403."""
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    crear_usuario("auditor", ROL_AUDITOR)
    crear_usuario("juan", ROL_VENDEDOR)
    # El seed le da al auditor el permiso de ver el módulo AUDITORIA.
    dar_permiso(rol_id=roles[ROL_AUDITOR].id, modulo=Modulo.AUDITORIA, ver=True)

    assert client.get("/api/v1/auditoria", headers=login("admin")).status_code == 200
    assert client.get("/api/v1/auditoria", headers=login("auditor")).status_code == 200
    assert client.get("/api/v1/auditoria", headers=login("juan")).status_code == 403


def test_el_login_aparece_en_la_consulta(client, crear_usuario, login):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    headers = login("admin")

    resp = client.get("/api/v1/auditoria?accion=auth.login", headers=headers)
    assert resp.status_code == 200

    datos = resp.json()
    assert datos["total"] >= 1
    assert datos["resultados"][0]["accion"].startswith("auth.login")


def test_filtro_por_entidad(client, db, crear_usuario, roles, login):
    from app.services import usuarios as servicio_usuarios

    admin = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    servicio_usuarios.crear_usuario(
        db, admin, username="nuevo", nombre="Nuevo", password="Clave1234!",
        rol_id=roles[ROL_VENDEDOR].id,
    )

    resp = client.get("/api/v1/auditoria?accion=usuario.crear", headers=login("admin"))
    datos = resp.json()

    assert datos["total"] == 1
    assert datos["resultados"][0]["entidad"] == "usuarios"


@pytest.mark.parametrize(
    "sentencia",
    [
        "UPDATE auditoria SET accion = 'adulterado'",
        "DELETE FROM auditoria",
        "TRUNCATE auditoria",
    ],
)
def test_la_auditoria_es_inmutable_en_la_base(db, crear_usuario, sentencia):
    """
    La garantía del Principio 3 vive en la base, no en el código: los
    triggers abortan cualquier intento de modificar la tabla.
    """
    from app.core.auditoria import registrar_auditoria

    usuario = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    registrar_auditoria(
        db, usuario_id=usuario.id, accion="test.inmutable", entidad="test", entidad_id=1
    )

    with pytest.raises(Exception, match="append-only"):
        db.execute(text(sentencia))


def test_el_historial_de_accesos_tambien_es_inmutable(db, client, crear_usuario):
    """Mismo criterio que la auditoría: es evidencia, no dato editable."""
    crear_usuario("juan", ROL_VENDEDOR)
    client.post("/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"})

    with pytest.raises(Exception, match="append-only"):
        db.execute(text("UPDATE historial_accesos SET resultado = 'exitoso'"))
