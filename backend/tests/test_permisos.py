"""
Tests de `resolver_permiso`: la única barrera de acceso del sistema.

Son los tests más importantes del módulo: si esta función se equivoca,
todo el control de acceso del ERP se equivoca con ella.
"""

from app.core.permisos import (
    ROL_CUENTA_MAESTRA,
    ROL_VENDEDOR,
    Modulo,
    Recurso,
    resolver_permiso,
)


def test_sin_permisos_no_puede_nada(db, crear_usuario):
    usuario = crear_usuario("juan", ROL_VENDEDOR)
    assert resolver_permiso(db, usuario.id, Modulo.VENTAS, "ver") is False


def test_permiso_del_rol_habilita(db, crear_usuario, roles, dar_permiso):
    usuario = crear_usuario("juan", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.VENTAS, ver=True, crear=True)

    assert resolver_permiso(db, usuario.id, Modulo.VENTAS, "ver") is True
    assert resolver_permiso(db, usuario.id, Modulo.VENTAS, "crear") is True
    # Lo que no se otorgó sigue denegado.
    assert resolver_permiso(db, usuario.id, Modulo.VENTAS, "eliminar") is False


def test_recurso_especifico_sin_acceso_general(db, crear_usuario, roles, dar_permiso):
    """
    Criterio de aceptación: el override de un recurso puntual habilita ese
    recurso aunque el rol no tenga acceso general al módulo, y NO habilita
    el módulo completo.
    """
    usuario = crear_usuario("juan", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.REPORTES, ver=False)
    dar_permiso(
        usuario_id=usuario.id,
        modulo=Modulo.REPORTES,
        recurso=Recurso.REPORTE_VENTAS_DIARIAS,
        ver=True,
    )

    assert (
        resolver_permiso(
            db, usuario.id, Modulo.REPORTES, "ver", Recurso.REPORTE_VENTAS_DIARIAS
        )
        is True
    )
    # Sin acceso general al módulo.
    assert resolver_permiso(db, usuario.id, Modulo.REPORTES, "ver") is False
    # Ni a otro recurso del mismo módulo.
    assert (
        resolver_permiso(db, usuario.id, Modulo.REPORTES, "ver", Recurso.REPORTE_STOCK)
        is False
    )


def test_permiso_general_del_modulo_habilita_sus_recursos(db, crear_usuario, roles, dar_permiso):
    """Quien puede ver todos los reportes puede ver cualquiera en particular."""
    usuario = crear_usuario("juan", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.REPORTES, ver=True)

    assert (
        resolver_permiso(db, usuario.id, Modulo.REPORTES, "ver", Recurso.REPORTE_STOCK)
        is True
    )


def test_override_es_aditivo_nunca_resta(db, crear_usuario, roles, dar_permiso):
    """Un override en FALSE no puede quitar lo que el rol ya concede."""
    usuario = crear_usuario("juan", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.VENTAS, ver=True)
    dar_permiso(usuario_id=usuario.id, modulo=Modulo.VENTAS, ver=False)

    assert resolver_permiso(db, usuario.id, Modulo.VENTAS, "ver") is True


def test_cuenta_maestra_puede_todo(db, crear_usuario):
    """Sin una sola fila de permisos cargada."""
    usuario = crear_usuario("admin", ROL_CUENTA_MAESTRA)

    for modulo in Modulo:
        for accion in ("ver", "crear", "editar", "eliminar"):
            assert resolver_permiso(db, usuario.id, modulo, accion) is True


def test_usuario_inactivo_no_puede_nada(db, crear_usuario, roles, dar_permiso):
    usuario = crear_usuario("juan", ROL_VENDEDOR, activo=False)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.VENTAS, ver=True)

    assert resolver_permiso(db, usuario.id, Modulo.VENTAS, "ver") is False


def test_rol_inactivo_no_habilita(db, crear_usuario, roles, dar_permiso):
    usuario = crear_usuario("juan", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.VENTAS, ver=True)
    roles[ROL_VENDEDOR].activo = False
    db.flush()

    assert resolver_permiso(db, usuario.id, Modulo.VENTAS, "ver") is False


def test_usuario_inexistente(db):
    assert resolver_permiso(db, 999999, Modulo.VENTAS, "ver") is False


def test_accion_invalida_falla_fuerte(db, crear_usuario):
    """Un typo en el nombre de la acción tiene que romper, no devolver False."""
    import pytest

    usuario = crear_usuario("juan", ROL_VENDEDOR)
    with pytest.raises(ValueError):
        resolver_permiso(db, usuario.id, Modulo.VENTAS, "borrar")
