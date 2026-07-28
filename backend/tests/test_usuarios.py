"""Tests de las reglas de negocio de usuarios y del árbol de permisos."""

import pytest

from app.core.permisos import (
    ROL_CUENTA_MAESTRA,
    ROL_DUENO,
    ROL_SUPERVISOR,
    ROL_VENDEDOR,
    Modulo,
    Recurso,
)
from app.services import roles as servicio_roles
from app.services import usuarios as servicio_usuarios


def test_supervisor_solo_gestiona_vendedores(db, crear_usuario, roles):
    """Criterio de aceptación: supervisor sobre usuario no-vendedor → 403."""
    supervisor = crear_usuario("sup", ROL_SUPERVISOR)
    dueno = crear_usuario("jefe", ROL_DUENO)

    # Sobre un vendedor: permitido.
    servicio_usuarios.validar_puede_gestionar(supervisor, roles[ROL_VENDEDOR])

    # Sobre cualquier otro rol: no.
    with pytest.raises(servicio_usuarios.SinPermiso):
        servicio_usuarios.validar_puede_gestionar(supervisor, dueno.rol)


def test_supervisor_editando_no_vendedor_da_403(client, crear_usuario, roles, dar_permiso, login):
    supervisor = crear_usuario("sup", ROL_SUPERVISOR)
    dueno = crear_usuario("jefe", ROL_DUENO)
    dar_permiso(rol_id=roles[ROL_SUPERVISOR].id, modulo=Modulo.USUARIOS, ver=True, editar=True)

    headers = login("sup")
    resp = client.put(f"/api/v1/usuarios/{dueno.id}", json={"nombre": "Cambiado"}, headers=headers)

    assert resp.status_code == 403


def test_solo_una_cuenta_maestra(db, crear_usuario, roles):
    """Criterio de aceptación."""
    admin = crear_usuario("admin", ROL_CUENTA_MAESTRA)

    with pytest.raises(servicio_roles.ReglaDeNegocio, match="cuenta_maestra"):
        servicio_usuarios.crear_usuario(
            db, admin, username="admin2", nombre="Otro", password="Clave1234!",
            rol_id=roles[ROL_CUENTA_MAESTRA].id,
        )


def test_no_puede_desactivarse_a_si_mismo(db, crear_usuario, roles):
    """Criterio de aceptación."""
    admin = crear_usuario("admin", ROL_CUENTA_MAESTRA)

    with pytest.raises(servicio_roles.ReglaDeNegocio, match="sí mismo"):
        servicio_usuarios.cambiar_estado_usuario(db, admin, admin.id, activo=False)


def test_no_se_puede_desactivar_la_cuenta_maestra(db, crear_usuario, roles):
    admin = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    otro_admin = crear_usuario("dueno", ROL_DUENO)
    # Ni siquiera otro usuario con permisos puede hacerlo.
    with pytest.raises(servicio_roles.ReglaDeNegocio):
        servicio_usuarios.cambiar_estado_usuario(db, admin, admin.id, activo=False)


def test_desactivar_usuario_corta_sus_sesiones(db, client, crear_usuario, roles):
    """Un JWT vigente no debe seguir funcionando tras la desactivación."""
    from sqlalchemy import select

    from app.models.sesion import Sesion

    admin = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    juan = crear_usuario("juan", ROL_VENDEDOR)

    client.post("/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"})
    assert db.execute(
        select(Sesion).where(Sesion.usuario_id == juan.id, Sesion.revocada.is_(False))
    ).scalars().first() is not None

    servicio_usuarios.cambiar_estado_usuario(db, admin, juan.id, activo=False)

    assert db.execute(
        select(Sesion).where(Sesion.usuario_id == juan.id, Sesion.revocada.is_(False))
    ).scalars().first() is None


def test_clave_especial_nunca_sale_en_la_respuesta(client, db, crear_usuario, login):
    """Criterio de aceptación: excluida de todos los schemas Pydantic."""
    from app.services.auth import hash_password

    admin = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    admin.clave_especial_hash = hash_password("ClaveEspecial1!")
    db.flush()

    headers = login("admin")

    detalle = client.get(f"/api/v1/usuarios/{admin.id}", headers=headers)
    assert detalle.status_code == 200
    assert "clave_especial_hash" not in detalle.text
    assert "password_hash" not in detalle.text

    listado = client.get("/api/v1/usuarios", headers=headers)
    assert "clave_especial_hash" not in listado.text
    assert "password_hash" not in listado.text


def test_clave_especial_solo_para_cuenta_maestra(client, db, crear_usuario, login):
    """Para cualquier otro usuario, los endpoints devuelven 404."""
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    juan = crear_usuario("juan", ROL_VENDEDOR)
    headers = login("admin")

    resp = client.post(
        f"/api/v1/usuarios/{juan.id}/clave-especial/validar",
        json={"clave": "loquesea"},
        headers=headers,
    )
    assert resp.status_code == 404


def test_clave_especial_valida_correctamente(client, db, crear_usuario, login):
    admin = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    headers = login("admin")

    client.patch(
        f"/api/v1/usuarios/{admin.id}/clave-especial/resetear",
        json={"clave_nueva": "ClaveEspecial1!"},
        headers=headers,
    )

    ok = client.post(
        f"/api/v1/usuarios/{admin.id}/clave-especial/validar",
        json={"clave": "ClaveEspecial1!"},
        headers=headers,
    )
    assert ok.json()["valida"] is True

    mal = client.post(
        f"/api/v1/usuarios/{admin.id}/clave-especial/validar",
        json={"clave": "equivocada"},
        headers=headers,
    )
    assert mal.json()["valida"] is False


def test_auditoria_de_usuario_no_registra_hashes(db, crear_usuario, roles):
    """La auditoría nunca debe guardar un hash de contraseña."""
    from sqlalchemy import select

    from app.models.auditoria import Auditoria

    admin = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    servicio_usuarios.crear_usuario(
        db, admin, username="nuevo", nombre="Nuevo", password="Clave1234!",
        rol_id=roles[ROL_VENDEDOR].id,
    )

    registro = db.execute(
        select(Auditoria).where(Auditoria.accion == "usuario.crear")
    ).scalars().one()
    assert "password_hash" not in registro.estado_nuevo
    assert "clave_especial_hash" not in registro.estado_nuevo
    assert registro.estado_nuevo["username"] == "nuevo"


def test_listado_filtra_en_el_backend(db, crear_usuario, roles):
    crear_usuario("juan", ROL_VENDEDOR, nombre="Juan Pérez")
    crear_usuario("pedro", ROL_VENDEDOR, nombre="Pedro Gómez", activo=False)

    activos, total = servicio_usuarios.listar_usuarios(db, activo=True)
    assert total == 1
    assert activos[0].username == "juan"

    # ILIKE: insensible a mayúsculas.
    por_nombre, total = servicio_usuarios.listar_usuarios(db, nombre="pérez")
    assert total == 1


def test_roles_asignables_excluyen_cuenta_maestra(db, crear_usuario, roles):
    admin = crear_usuario("admin", ROL_CUENTA_MAESTRA)

    asignables = [r.nombre for r in servicio_usuarios.roles_asignables(db, admin)]
    assert ROL_CUENTA_MAESTRA not in asignables


def test_supervisor_solo_puede_asignar_vendedor(db, crear_usuario, roles):
    supervisor = crear_usuario("sup", ROL_SUPERVISOR)

    asignables = [r.nombre for r in servicio_usuarios.roles_asignables(db, supervisor)]
    assert asignables == [ROL_VENDEDOR]


# ============================================================================
# Árbol de permisos
# ============================================================================


def test_arbol_incluye_todos_los_modulos(db, crear_usuario, roles):
    from app.services.permisos import arbol_de_rol

    arbol = arbol_de_rol(db, roles[ROL_VENDEDOR].id)
    assert {n["modulo"] for n in arbol} == {m.value for m in Modulo}


def test_arbol_marca_acciones_no_aplicables(db, roles):
    """Los reportes solo tienen 'ver': el resto viene en None (se pinta '—')."""
    from app.services.permisos import arbol_de_rol

    arbol = arbol_de_rol(db, roles[ROL_VENDEDOR].id)
    reportes = next(n for n in arbol if n["modulo"] == Modulo.REPORTES.value)

    recurso = next(
        r for r in reportes["recursos"] if r["recurso"] == Recurso.REPORTE_VENTAS_DIARIAS.value
    )
    assert recurso["puede_ver"] is False
    assert recurso["puede_crear"] is None
    assert recurso["puede_editar"] is None
    assert recurso["puede_eliminar"] is None


def test_arbol_de_usuario_separa_herencia_de_override(db, crear_usuario, roles, dar_permiso):
    from app.services.permisos import arbol_de_usuario

    usuario = crear_usuario("juan", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.VENTAS, ver=True)
    dar_permiso(usuario_id=usuario.id, modulo=Modulo.VENTAS, crear=True)

    arbol = arbol_de_usuario(db, usuario)
    ventas = next(n for n in arbol if n["modulo"] == Modulo.VENTAS.value)

    assert ventas["heredado_ver"] is True
    assert ventas["override_ver"] is False
    assert ventas["puede_ver"] is True

    assert ventas["heredado_crear"] is False
    assert ventas["override_crear"] is True
    assert ventas["puede_crear"] is True


def test_guardar_permisos_ignora_acciones_no_aplicables(db, crear_usuario, roles):
    """
    Aunque el cliente mande puede_crear=True en un reporte, se guarda FALSE:
    esa acción no aplica al recurso.
    """
    from app.services.permisos import actualizar_permisos_rol, arbol_de_rol

    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    actualizar_permisos_rol(
        db,
        roles[ROL_VENDEDOR],
        [
            {
                "modulo": Modulo.REPORTES.value,
                "recurso": Recurso.REPORTE_STOCK.value,
                "puede_ver": True,
                "puede_crear": True,
                "puede_editar": True,
                "puede_eliminar": True,
            }
        ],
        autor.id,
    )

    arbol = arbol_de_rol(db, roles[ROL_VENDEDOR].id)
    reportes = next(n for n in arbol if n["modulo"] == Modulo.REPORTES.value)
    recurso = next(r for r in reportes["recursos"] if r["recurso"] == Recurso.REPORTE_STOCK.value)

    assert recurso["puede_ver"] is True
    assert recurso["puede_crear"] is None  # no aplica, y quedó en FALSE en la base


def test_recurso_de_otro_modulo_es_rechazado(db, crear_usuario, roles):
    from app.services.permisos import actualizar_permisos_rol

    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)

    with pytest.raises(ValueError, match="no pertenece"):
        actualizar_permisos_rol(
            db,
            roles[ROL_VENDEDOR],
            [{"modulo": Modulo.VENTAS.value, "recurso": Recurso.REPORTE_STOCK.value}],
            autor.id,
        )
