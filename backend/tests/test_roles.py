"""Tests de las reglas de negocio de roles."""

import pytest

from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_VENDEDOR, Modulo
from app.services import roles as servicio_roles


def test_no_se_puede_renombrar_rol_de_sistema(db, crear_usuario, roles):
    """Criterio de aceptación."""
    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)

    with pytest.raises(servicio_roles.ReglaDeNegocio, match="renombrar"):
        servicio_roles.editar_rol(
            db, roles[ROL_VENDEDOR].id, nombre="otro_nombre", descripcion=None, autor_id=autor.id
        )


def test_rol_de_sistema_permite_cambiar_descripcion(db, crear_usuario, roles):
    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)

    rol = servicio_roles.editar_rol(
        db, roles[ROL_VENDEDOR].id, nombre=None, descripcion="Nueva descripción", autor_id=autor.id
    )
    assert rol.descripcion == "Nueva descripción"
    assert rol.nombre == ROL_VENDEDOR


def test_no_se_puede_eliminar_rol_de_sistema(db, crear_usuario, roles):
    """Criterio de aceptación."""
    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)

    with pytest.raises(servicio_roles.ReglaDeNegocio, match="eliminar"):
        servicio_roles.eliminar_rol(db, roles[ROL_VENDEDOR].id, autor.id)


def test_no_se_puede_desactivar_rol_con_usuarios_activos(db, crear_usuario, roles):
    """Criterio de aceptación."""
    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    crear_usuario("juan", ROL_VENDEDOR, activo=True)

    with pytest.raises(servicio_roles.ReglaDeNegocio, match="activo"):
        servicio_roles.cambiar_estado_rol(db, roles[ROL_VENDEDOR].id, activo=False, autor_id=autor.id)


def test_se_puede_desactivar_rol_sin_usuarios_activos(db, crear_usuario, roles):
    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    crear_usuario("juan", ROL_VENDEDOR, activo=False)

    rol = servicio_roles.cambiar_estado_rol(
        db, roles[ROL_VENDEDOR].id, activo=False, autor_id=autor.id
    )
    assert rol.activo is False


def test_rol_nuevo_arranca_sin_permisos(db, crear_usuario, roles):
    """Criterio: al crear un rol, todos los módulos quedan en FALSE."""
    from app.services.permisos import arbol_de_rol

    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    rol = servicio_roles.crear_rol(db, "repositor", "Rol de prueba", autor.id)

    arbol = arbol_de_rol(db, rol.id)
    assert len(arbol) == len(Modulo)
    for nodo in arbol:
        assert nodo["puede_ver"] is False
        assert nodo["puede_crear"] is False
        assert nodo["puede_editar"] is False
        assert nodo["puede_eliminar"] is False


def test_rol_nuevo_no_es_de_sistema(db, crear_usuario, roles):
    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    rol = servicio_roles.crear_rol(db, "Repositor Turno Noche", None, autor.id)

    assert rol.es_sistema is False
    # El nombre se normaliza a minúsculas con guiones bajos.
    assert rol.nombre == "repositor_turno_noche"


def test_no_se_repite_el_nombre_de_rol(db, crear_usuario, roles):
    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    servicio_roles.crear_rol(db, "repositor", None, autor.id)

    with pytest.raises(servicio_roles.ReglaDeNegocio, match="Ya existe"):
        servicio_roles.crear_rol(db, "repositor", None, autor.id)


def test_listado_cuenta_usuarios_por_rol(db, crear_usuario, roles):
    crear_usuario("juan", ROL_VENDEDOR)
    crear_usuario("pedro", ROL_VENDEDOR)

    filas = servicio_roles.listar_roles(db)
    por_nombre = {f["rol"].nombre: f["cantidad_usuarios"] for f in filas}

    assert por_nombre[ROL_VENDEDOR] == 2
    assert por_nombre[ROL_CUENTA_MAESTRA] == 0


def test_endpoint_roles_exige_cuenta_maestra(client, crear_usuario, login):
    """Los endpoints de roles son exclusivos de la Cuenta Maestra."""
    crear_usuario("juan", ROL_VENDEDOR)
    headers = login("juan")

    assert client.get("/api/v1/roles", headers=headers).status_code == 403


def test_endpoint_roles_permite_cuenta_maestra(client, crear_usuario, login):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    headers = login("admin")

    resp = client.get("/api/v1/roles", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 6
