"""Tests del módulo de proveedores y valor del dólar."""

from decimal import Decimal
from io import BytesIO

import pytest
from sqlalchemy import text

from app.core.permisos import (
    ROL_CUENTA_MAESTRA,
    ROL_DISTRIBUCION,
    ROL_DUENO,
    ROL_SUPERVISOR,
    Modulo,
    Recurso,
)
from app.models.proveedor import EstadoProveedor, ProveedorDolarHistorial
from app.services import proveedores as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio


@pytest.fixture
def autor(crear_usuario):
    return crear_usuario("admin", ROL_CUENTA_MAESTRA)


@pytest.fixture
def proveedor(db, autor):
    return servicio.crear_proveedor(
        db, autor, nombre="Distribuidora Norte", dolar_actual=Decimal("1000")
    )


# ============================================================================
# Alta, edición y estado
# ============================================================================


def test_alta_registra_dolar_inicial_en_historial(db, proveedor):
    hist = servicio.historial_dolar(db, proveedor.id)
    assert len(hist) == 1
    assert hist[0].valor_nuevo == Decimal("1000.00")


def test_dolar_no_puede_ser_cero_ni_negativo(db, autor):
    for valor in (Decimal("0"), Decimal("-5")):
        with pytest.raises(ReglaDeNegocio, match="mayor a cero"):
            servicio.crear_proveedor(db, autor, nombre="X", dolar_actual=valor)


def test_baja_es_logica(db, autor, proveedor):
    servicio.cambiar_estado(db, autor, proveedor.id, EstadoProveedor.DESACTIVADO)
    assert proveedor.estado == EstadoProveedor.DESACTIVADO
    # Sigue existiendo en la base.
    assert servicio.obtener_proveedor(db, proveedor.id) is proveedor


def test_desactivado_se_reactiva_libremente(db, crear_usuario, proveedor):
    dist = crear_usuario("dist", ROL_DISTRIBUCION)
    servicio.cambiar_estado(db, dist, proveedor.id, EstadoProveedor.DESACTIVADO)

    # Distribución puede reactivar un desactivado.
    servicio.cambiar_estado(db, dist, proveedor.id, EstadoProveedor.ACTIVO)
    assert proveedor.estado == EstadoProveedor.ACTIVO


def test_inhabilitado_no_lo_reactiva_distribucion(db, crear_usuario, autor, proveedor):
    dist = crear_usuario("dist", ROL_DISTRIBUCION)
    servicio.cambiar_estado(db, autor, proveedor.id, EstadoProveedor.INHABILITADO)

    with pytest.raises(servicio.SinPermiso, match="Cuenta Maestra o Dueño"):
        servicio.cambiar_estado(db, dist, proveedor.id, EstadoProveedor.ACTIVO)


def test_inhabilitado_lo_reactiva_dueno(db, crear_usuario, autor, proveedor):
    dueno = crear_usuario("jefe", ROL_DUENO)
    servicio.cambiar_estado(db, autor, proveedor.id, EstadoProveedor.INHABILITADO)

    servicio.cambiar_estado(db, dueno, proveedor.id, EstadoProveedor.ACTIVO)
    assert proveedor.estado == EstadoProveedor.ACTIVO


def test_no_delete_fisico_en_la_api(client, crear_usuario, roles, dar_permiso, login):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    resp = client.delete("/api/v1/proveedores/1", headers=login("admin"))
    # El método no existe en el router.
    assert resp.status_code == 405


# ============================================================================
# Cambio de dólar: individual, masivo, historial
# ============================================================================


def test_cambio_individual_historiza_y_audita(db, autor, proveedor):
    from app.models.auditoria import Auditoria

    servicio.cambiar_dolar(db, autor, proveedor.id, Decimal("1200"))

    assert proveedor.dolar_actual == Decimal("1200.00")
    hist = servicio.historial_dolar(db, proveedor.id)
    assert hist[0].valor_anterior == Decimal("1000.00")
    assert hist[0].valor_nuevo == Decimal("1200.00")

    from sqlalchemy import select

    assert db.execute(
        select(Auditoria).where(Auditoria.accion == "dolar.cambio")
    ).scalars().first() is not None


def test_masivo_porcentaje_por_proveedor(db, autor):
    p1 = servicio.crear_proveedor(db, autor, nombre="A", dolar_actual=Decimal("1000"))
    p2 = servicio.crear_proveedor(db, autor, nombre="B", dolar_actual=Decimal("1500"))

    servicio.cambio_masivo(db, autor, None, "porcentaje", Decimal("10"))

    # El porcentaje se aplica sobre el valor de cada uno.
    assert p1.dolar_actual == Decimal("1100.00")
    assert p2.dolar_actual == Decimal("1650.00")


def test_masivo_valor_fijo(db, autor):
    p1 = servicio.crear_proveedor(db, autor, nombre="A", dolar_actual=Decimal("1000"))
    p2 = servicio.crear_proveedor(db, autor, nombre="B", dolar_actual=Decimal("1500"))

    servicio.cambio_masivo(db, autor, None, "valor", Decimal("2000"))

    assert p1.dolar_actual == Decimal("2000.00")
    assert p2.dolar_actual == Decimal("2000.00")


def test_masivo_genera_un_registro_por_proveedor(db, autor):
    from sqlalchemy import func, select

    p1 = servicio.crear_proveedor(db, autor, nombre="A", dolar_actual=Decimal("1000"))
    p2 = servicio.crear_proveedor(db, autor, nombre="B", dolar_actual=Decimal("1500"))

    servicio.cambio_masivo(db, autor, [p1.id, p2.id], "valor", Decimal("2000"))

    # 2 del alta + 2 del masivo = 4.
    total = db.execute(select(func.count(ProveedorDolarHistorial.id))).scalar_one()
    assert total == 4


def test_masivo_solo_afecta_activos(db, autor):
    activo = servicio.crear_proveedor(db, autor, nombre="A", dolar_actual=Decimal("1000"))
    inactivo = servicio.crear_proveedor(db, autor, nombre="B", dolar_actual=Decimal("1000"))
    servicio.cambiar_estado(db, autor, inactivo.id, EstadoProveedor.DESACTIVADO)

    servicio.cambio_masivo(db, autor, None, "valor", Decimal("2000"))

    assert activo.dolar_actual == Decimal("2000.00")
    assert inactivo.dolar_actual == Decimal("1000.00")  # sin cambios


def test_preview_no_aplica_cambios(db, autor, proveedor):
    servicio.preview_masivo(db, None, "porcentaje", Decimal("50"))
    assert proveedor.dolar_actual == Decimal("1000.00")  # intacto


# ============================================================================
# Importación por Excel
# ============================================================================


def _xlsx(filas: list[tuple]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["proveedor_id", "dolar_nuevo"])
    for fila in filas:
        ws.append(list(fila))
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_excel_aplica_si_todo_es_valido(db, autor):
    p1 = servicio.crear_proveedor(db, autor, nombre="A", dolar_actual=Decimal("1000"))
    p2 = servicio.crear_proveedor(db, autor, nombre="B", dolar_actual=Decimal("1000"))

    resultado = servicio.importar_dolar(db, autor, _xlsx([(p1.id, 1200), (p2.id, 1300)]))

    assert resultado["aplicados"] == 2
    assert resultado["errores"] == []
    assert p1.dolar_actual == Decimal("1200.00")
    assert p2.dolar_actual == Decimal("1300.00")


def test_excel_es_todo_o_nada(db, autor):
    """Una fila mala aborta la importación completa: criterio de aceptación."""
    p1 = servicio.crear_proveedor(db, autor, nombre="A", dolar_actual=Decimal("1000"))

    resultado = servicio.importar_dolar(
        db, autor, _xlsx([(p1.id, 1200), (999999, 1300)])
    )

    assert resultado["aplicados"] == 0
    assert len(resultado["errores"]) == 1
    assert resultado["errores"][0]["fila"] == 3
    # El proveedor válido NO se modificó.
    assert p1.dolar_actual == Decimal("1000.00")


def test_excel_reporta_valores_invalidos(db, autor):
    p1 = servicio.crear_proveedor(db, autor, nombre="A", dolar_actual=Decimal("1000"))

    resultado = servicio.importar_dolar(
        db, autor, _xlsx([(p1.id, -5), ("no-num", 100), (None, 100)])
    )

    assert resultado["aplicados"] == 0
    assert len(resultado["errores"]) == 3


def test_excel_sin_columnas_correctas(db, autor):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["id", "valor"])
    buffer = BytesIO()
    wb.save(buffer)

    with pytest.raises(ReglaDeNegocio, match="columnas"):
        servicio.importar_dolar(db, autor, buffer.getvalue())


# ============================================================================
# Endpoints y permisos
# ============================================================================


def test_listado_filtra_por_estado(client, crear_usuario, login, db, autor):
    servicio.crear_proveedor(db, autor, nombre="Activo SA", dolar_actual=Decimal("1000"))
    inact = servicio.crear_proveedor(db, autor, nombre="Baja SA", dolar_actual=Decimal("1000"))
    servicio.cambiar_estado(db, autor, inact.id, EstadoProveedor.DESACTIVADO)

    headers = login("admin")
    resp = client.get("/api/v1/proveedores?estado=activo", headers=headers)

    assert resp.status_code == 200
    assert [p["nombre"] for p in resp.json()] == ["Activo SA"]


def test_sin_permiso_no_lista(client, crear_usuario, login):
    """Vendedor sin permiso sobre proveedores → 403."""
    from app.core.permisos import ROL_VENDEDOR

    crear_usuario("juan", ROL_VENDEDOR)
    resp = client.get("/api/v1/proveedores", headers=login("juan"))
    assert resp.status_code == 403


def test_masivo_requiere_el_recurso(client, crear_usuario, roles, dar_permiso, login):
    """Sin el recurso dolar.cambio_masivo (ni módulo completo) → 403."""
    from app.core.permisos import ROL_VENDEDOR

    crear_usuario("juan", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.PROVEEDORES, ver=True)

    resp = client.post(
        "/api/v1/proveedores/dolar/masivo",
        json={"proveedor_ids": None, "modalidad": "valor", "valor": "1000"},
        headers=login("juan"),
    )
    assert resp.status_code == 403


def test_masivo_con_el_recurso_puntual(client, crear_usuario, roles, dar_permiso, login, db, autor):
    """El recurso dolar.cambio_masivo habilita el masivo aunque falte editar general."""
    from app.core.permisos import ROL_VENDEDOR

    servicio.crear_proveedor(db, autor, nombre="A", dolar_actual=Decimal("1000"))
    juan = crear_usuario("juan", ROL_VENDEDOR)
    dar_permiso(
        rol_id=roles[ROL_VENDEDOR].id,
        modulo=Modulo.PROVEEDORES,
        recurso=Recurso.DOLAR_CAMBIO_MASIVO,
        editar=True,
    )

    resp = client.post(
        "/api/v1/proveedores/dolar/masivo",
        json={"proveedor_ids": None, "modalidad": "valor", "valor": "1500"},
        headers=login("juan"),
    )
    assert resp.status_code == 200


# ============================================================================
# NOMBRE (ex razon_social) Y CONTACTO
# ============================================================================


def test_el_contacto_es_opcional(db, autor):
    """Un proveedor se puede dar de alta sin persona de contacto."""
    p = servicio.crear_proveedor(
        db, autor, nombre="Sin Contacto SA", dolar_actual=Decimal("1000")
    )
    assert p.contacto is None


def test_el_contacto_se_guarda_y_se_edita(db, autor):
    p = servicio.crear_proveedor(
        db, autor, nombre="Distribuidora Norte", dolar_actual=Decimal("1000"),
        contacto="Leandra Carvallo",
    )
    assert p.contacto == "Leandra Carvallo"

    servicio.editar_proveedor(db, autor, p.id, contacto="Ana Gómez")
    assert p.contacto == "Ana Gómez"


def test_el_contacto_viaja_en_la_api(client, db, autor, login, dar_permiso, roles):
    servicio.crear_proveedor(
        db, autor, nombre="Distribuidora Norte", dolar_actual=Decimal("1000"),
        contacto="Leandra Carvallo",
    )
    db.commit()

    resp = client.get("/api/v1/proveedores", headers=login("admin"))
    assert resp.status_code == 200

    fila = resp.json()[0]
    assert fila["nombre"] == "Distribuidora Norte"
    assert fila["contacto"] == "Leandra Carvallo"
    # El nombre viejo no debe seguir apareciendo en el contrato.
    assert "razon_social" not in fila


def test_el_filtro_de_nombre_sigue_funcionando(db, autor):
    """El rename no puede haberse llevado puesto el filtro del Principio 5."""
    servicio.crear_proveedor(db, autor, nombre="Distribuidora Norte", dolar_actual=Decimal("1000"))
    servicio.crear_proveedor(db, autor, nombre="Mayorista Sur", dolar_actual=Decimal("1000"))

    # ILIKE: insensible a mayúsculas, como el resto de los filtros de texto.
    encontrados = servicio.listar_proveedores(db, nombre="norte")
    assert [p.nombre for p in encontrados] == ["Distribuidora Norte"]


def test_no_quedan_referencias_a_razon_social():
    """
    El rename tiene que ser total: una referencia suelta en un template o
    en el JS falla en silencio (Alpine renderiza vacío, no da error).
    """
    import pathlib

    app = pathlib.Path(__file__).parent.parent / "app"
    con_referencias = [
        str(p.relative_to(app))
        for p in list(app.rglob("*.py")) + list(app.rglob("*.html")) + list(app.rglob("*.js"))
        if "razon_social" in p.read_text()
    ]
    assert not con_referencias, con_referencias
