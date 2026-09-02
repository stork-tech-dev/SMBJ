"""
Tests de la sección "Accesos permitidos" del formulario de usuario.

Es la vista simplificada de los permisos: una lista plana de casilleros
que se guardan como overrides individuales.
"""

from app.core.permisos import (
    ROL_CUENTA_MAESTRA,
    ROL_SUPERVISOR,
    ROL_VENDEDOR,
    Modulo,
    Recurso,
    catalogo_accesos,
    resolver_permiso,
)
from app.services import permisos as servicio_permisos


def test_catalogo_cubre_todos_los_recursos():
    """Agregar un Recurso al Enum lo suma a la pantalla sin tocar nada más."""
    claves = {a["clave"] for a in catalogo_accesos()}

    for recurso in Recurso:
        assert any(recurso.value in c for c in claves), recurso.value


def test_catalogo_tiene_una_sola_accion_por_recurso():
    """Cada casillero es una única acción: si no, no sería un checkbox."""
    accesos = catalogo_accesos()
    por_recurso = {}
    for a in accesos:
        if a["recurso"] is not None:
            por_recurso.setdefault(a["recurso"], []).append(a["accion"])

    for recurso, acciones in por_recurso.items():
        assert len(acciones) == 1, f"{recurso} tiene {acciones}"


def test_accesos_de_rol_marcan_lo_heredado(db, roles, dar_permiso):
    dar_permiso(
        rol_id=roles[ROL_VENDEDOR].id,
        modulo=Modulo.VENTAS,
        recurso=Recurso.VENTA_DESCUENTO,
        crear=True,
    )

    accesos = servicio_permisos.accesos_de_rol(db, roles[ROL_VENDEDOR].id)
    descuento = next(a for a in accesos if Recurso.VENTA_DESCUENTO.value in a["clave"])

    assert descuento["heredado"] is True
    assert descuento["override"] is False
    assert descuento["permitido"] is True


def test_guardar_accesos_crea_override(db, crear_usuario, roles):
    """Marcar un acceso lo habilita de verdad en resolver_permiso."""
    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    usuario = crear_usuario("juan", ROL_VENDEDOR)

    clave = f"{Modulo.CAJA.value}:{Recurso.CAJA_RETIRO.value}:crear"
    servicio_permisos.actualizar_accesos_usuario(db, usuario, [clave], autor.id)

    assert resolver_permiso(db, usuario.id, Modulo.CAJA, "crear", Recurso.CAJA_RETIRO) is True
    # No habilita el módulo completo.
    assert resolver_permiso(db, usuario.id, Modulo.CAJA, "crear") is False


def test_desmarcar_acceso_lo_quita(db, crear_usuario, roles):
    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    usuario = crear_usuario("juan", ROL_VENDEDOR)
    clave = f"{Modulo.CAJA.value}:{Recurso.CAJA_RETIRO.value}:crear"

    servicio_permisos.actualizar_accesos_usuario(db, usuario, [clave], autor.id)
    servicio_permisos.actualizar_accesos_usuario(db, usuario, [], autor.id)

    assert resolver_permiso(db, usuario.id, Modulo.CAJA, "crear", Recurso.CAJA_RETIRO) is False


def test_lo_heredado_del_rol_no_se_puede_quitar(db, crear_usuario, roles, dar_permiso):
    """
    Desmarcar algo que otorga el rol no lo quita: los overrides solo suman.
    El checkbox va deshabilitado en la UI, pero la regla vive en el service.
    """
    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    usuario = crear_usuario("juan", ROL_VENDEDOR)
    dar_permiso(
        rol_id=roles[ROL_VENDEDOR].id,
        modulo=Modulo.VENTAS,
        recurso=Recurso.VENTA_DESCUENTO,
        crear=True,
    )

    # Se guarda sin ese acceso marcado.
    servicio_permisos.actualizar_accesos_usuario(db, usuario, [], autor.id)

    assert (
        resolver_permiso(db, usuario.id, Modulo.VENTAS, "crear", Recurso.VENTA_DESCUENTO) is True
    )


def test_marcar_lo_que_ya_da_el_rol_no_crea_override(db, crear_usuario, roles, dar_permiso):
    """Sin filas redundantes: si el rol ya lo otorga, no se duplica."""
    from sqlalchemy import select

    from app.models.permiso import UsuarioPermiso

    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    usuario = crear_usuario("juan", ROL_VENDEDOR)
    dar_permiso(
        rol_id=roles[ROL_VENDEDOR].id,
        modulo=Modulo.VENTAS,
        recurso=Recurso.VENTA_DESCUENTO,
        crear=True,
    )
    clave = f"{Modulo.VENTAS.value}:{Recurso.VENTA_DESCUENTO.value}:crear"

    servicio_permisos.actualizar_accesos_usuario(db, usuario, [clave], autor.id)

    filas = db.execute(
        select(UsuarioPermiso).where(
            UsuarioPermiso.usuario_id == usuario.id,
            UsuarioPermiso.puede_crear.is_(True),
        )
    ).scalars().all()
    assert filas == []


def test_no_pisa_otros_permisos_del_mismo_modulo(db, crear_usuario, roles, dar_permiso):
    """
    Guardar accesos toca SOLO la acción de cada casillero. Un override
    cargado desde la pantalla completa de permisos no se pierde.
    """
    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    usuario = crear_usuario("juan", ROL_VENDEDOR)

    # Override de módulo completo cargado por la pantalla de permisos.
    dar_permiso(usuario_id=usuario.id, modulo=Modulo.TESORERIA, ver=True)

    clave = f"{Modulo.CAJA.value}:{Recurso.CAJA_RETIRO.value}:crear"
    servicio_permisos.actualizar_accesos_usuario(db, usuario, [clave], autor.id)

    assert resolver_permiso(db, usuario.id, Modulo.TESORERIA, "ver") is True


def test_endpoint_accesos_de_rol(client, crear_usuario, login, roles):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    headers = login("admin")

    resp = client.get(f"/api/v1/usuarios/accesos?rol_id={roles[ROL_VENDEDOR].id}", headers=headers)

    assert resp.status_code == 200
    assert len(resp.json()) == len(catalogo_accesos())


def test_endpoint_accesos_de_usuario(client, crear_usuario, login):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    juan = crear_usuario("juan", ROL_VENDEDOR)
    headers = login("admin")

    resp = client.get(f"/api/v1/usuarios/{juan.id}/accesos", headers=headers)

    assert resp.status_code == 200
    assert {"clave", "label", "heredado", "override", "permitido"} <= set(resp.json()[0])


def test_endpoint_guardar_accesos(client, crear_usuario, login):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    juan = crear_usuario("juan", ROL_VENDEDOR)
    headers = login("admin")
    clave = f"{Modulo.CAJA.value}:{Recurso.CAJA_RETIRO.value}:crear"

    resp = client.put(
        f"/api/v1/usuarios/{juan.id}/accesos", json={"accesos": [clave]}, headers=headers
    )

    assert resp.status_code == 200
    marcado = next(a for a in resp.json() if a["clave"] == clave)
    assert marcado["override"] is True
    assert marcado["permitido"] is True


def test_supervisor_no_toca_accesos_de_no_vendedor(client, crear_usuario, roles, dar_permiso, login):
    crear_usuario("sup", ROL_SUPERVISOR)
    otro = crear_usuario("jefe", "dueno")
    dar_permiso(rol_id=roles[ROL_SUPERVISOR].id, modulo=Modulo.USUARIOS, ver=True, editar=True)

    resp = client.put(
        f"/api/v1/usuarios/{otro.id}/accesos", json={"accesos": []}, headers=login("sup")
    )

    assert resp.status_code == 403


def test_guardar_accesos_queda_auditado(db, crear_usuario, roles):
    from sqlalchemy import select

    from app.models.auditoria import Auditoria

    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    usuario = crear_usuario("juan", ROL_VENDEDOR)
    clave = f"{Modulo.CAJA.value}:{Recurso.CAJA_RETIRO.value}:crear"

    servicio_permisos.actualizar_accesos_usuario(db, usuario, [clave], autor.id)

    registro = db.execute(
        select(Auditoria).where(Auditoria.accion == "usuario.accesos_actualizar")
    ).scalars().one()
    assert registro.usuario_id == autor.id
    assert clave in registro.estado_nuevo["accesos"]
    assert clave not in (registro.estado_anterior["accesos"] or [])


# ============================================================================
# UNICIDAD CON recurso = NULL
# ============================================================================
#
# `recurso = NULL` es el permiso general del módulo, el caso más común. El
# UNIQUE no lo protegía: en PostgreSQL NULL no es igual a NULL, así que la
# misma fila entraba dos veces. Así llegaron 45 duplicados a `rol_permisos`,
# que rompían el guardado de accesos con un 500 —`_fila()` usa
# `scalar_one_or_none()`— y neutralizaban el `ON CONFLICT DO NOTHING` del seed.


def test_el_permiso_general_de_un_rol_no_se_puede_duplicar(db, roles, dar_permiso):
    """El test del agujero: antes de `NULLS NOT DISTINCT` esto pasaba."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.VENTAS, ver=True)

    # El nombre del constraint en la aserción: sin eso, el test daría verde
    # con cualquier otro error de integridad que apareciera de casualidad.
    with pytest.raises(IntegrityError, match="uq_rol_permisos_rol_modulo_recurso"):
        dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.VENTAS, ver=True)


def test_el_permiso_general_de_un_usuario_no_se_puede_duplicar(
    db, crear_usuario, roles, dar_permiso
):
    """`usuario_permisos` tenía el mismo constraint débil."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    usuario = crear_usuario("juan", ROL_VENDEDOR)
    dar_permiso(usuario_id=usuario.id, modulo=Modulo.VENTAS, ver=True)

    with pytest.raises(IntegrityError, match="uq_usuario_permisos_usuario_modulo_recurso"):
        dar_permiso(usuario_id=usuario.id, modulo=Modulo.VENTAS, ver=True)


def test_la_unicidad_no_se_pasa_de_estricta(db, crear_usuario, roles, dar_permiso):
    """
    Lo que SÍ tiene que seguir entrando: el mismo módulo con recursos
    distintos, y el mismo par (módulo, recurso) en roles distintos. Si esto
    se rompiera, la restricción estaría de más.
    """
    vendedor = roles[ROL_VENDEDOR].id
    supervisor = roles[ROL_SUPERVISOR].id

    dar_permiso(rol_id=vendedor, modulo=Modulo.VENTAS, ver=True)
    dar_permiso(rol_id=vendedor, modulo=Modulo.VENTAS, recurso=Recurso.VENTA_ANULAR, eliminar=True)
    dar_permiso(rol_id=vendedor, modulo=Modulo.VENTAS, recurso=Recurso.VENTA_DESCUENTO, crear=True)
    dar_permiso(rol_id=supervisor, modulo=Modulo.VENTAS, ver=True)

    from sqlalchemy import func, select

    from app.models.permiso import RolPermiso

    total = db.execute(
        select(func.count(RolPermiso.id)).where(RolPermiso.modulo == Modulo.VENTAS.value)
    ).scalar_one()
    assert total == 4


def test_guardar_accesos_con_permisos_generales_del_rol(db, crear_usuario, roles, dar_permiso):
    """
    El 500 que motivó todo: con un permiso general duplicado, guardar los
    accesos de un usuario reventaba con MultipleResultsFound. Con la
    restricción arreglada el duplicado no existe y el guardado funciona.

    No había ningún test que cubriera este camino de punta a punta.
    """
    autor = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    usuario = crear_usuario("juan", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.VENTAS, ver=True, crear=True)

    clave = f"{Modulo.CAJA.value}:{Recurso.CAJA_RETIRO.value}:crear"
    accesos = servicio_permisos.actualizar_accesos_usuario(db, usuario, [clave], autor.id)

    assert any(a["clave"] == clave and a["permitido"] for a in accesos)
