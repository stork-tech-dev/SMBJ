"""Tests del módulo de puntos de venta."""

import pytest

from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_VENDEDOR, Modulo
from app.models.punto_de_venta import TipoPuntoVenta
from app.services import puntos_de_venta as servicio
from app.services.roles import ReglaDeNegocio


@pytest.fixture
def autor(crear_usuario):
    return crear_usuario("admin", ROL_CUENTA_MAESTRA)


def test_solo_un_cd(db, autor):
    servicio.crear_punto(db, autor, "CD Central", TipoPuntoVenta.CD, "CDC")

    with pytest.raises(ReglaDeNegocio, match="Centro de Distribución"):
        servicio.crear_punto(db, autor, "CD Secundario", TipoPuntoVenta.CD, "CDS")


def test_el_codigo_aplica_a_todos_los_tipos(db, autor):
    """
    Antes el código solo lo llevaban los locales, porque era el secreto con
    el que confirmaban la recepción de un envío del CD. Ahora es la
    abreviatura del punto de venta —"MPO", "MTO"— y el CD y la tienda online
    también se nombran en un reporte.
    """
    local = servicio.crear_punto(db, autor, "Local Centro", TipoPuntoVenta.LOCAL, "LCE")
    online = servicio.crear_punto(db, autor, "Online", TipoPuntoVenta.ONLINE, "ONL")
    cd = servicio.crear_punto(db, autor, "CD", TipoPuntoVenta.CD, "CD")

    assert (local.codigo, online.codigo, cd.codigo) == ("LCE", "ONL", "CD")


def test_cambiar_de_tipo_conserva_el_codigo(db, autor):
    """
    Cambiar de local a online borraba el código: era de confirmación y dejaba
    de tener sentido. Ahora identifica al punto de venta, que sigue siendo el
    mismo, así que se conserva.
    """
    local = servicio.crear_punto(db, autor, "Local", TipoPuntoVenta.LOCAL, "LOC")
    servicio.editar_punto(db, autor, local.id, tipo=TipoPuntoVenta.ONLINE)
    assert local.codigo == "LOC"


def test_el_codigo_es_obligatorio(db, autor):
    for vacio in ("", "   "):
        with pytest.raises(ReglaDeNegocio, match="obligatorio"):
            servicio.crear_punto(db, autor, "Local", TipoPuntoVenta.LOCAL, vacio)


def test_el_codigo_no_se_puede_repetir(db, autor):
    """
    A futuro identifica los reportes: dos puntos de venta con el mismo código
    los volverían ambiguos. Lo garantiza el índice único de la base; el
    servicio lo revisa antes para dar un mensaje que se entienda.
    """
    servicio.crear_punto(db, autor, "Patio Olmos", TipoPuntoVenta.LOCAL, "MPO")

    with pytest.raises(ReglaDeNegocio, match="Ya existe un punto de venta"):
        servicio.crear_punto(db, autor, "Otro Local", TipoPuntoVenta.LOCAL, "MPO")


def test_el_codigo_se_guarda_en_mayusculas(db, autor):
    """Si no, "mpo" y "MPO" convivirían como dos códigos distintos."""
    punto = servicio.crear_punto(db, autor, "Local", TipoPuntoVenta.LOCAL, " mpo ")
    assert punto.codigo == "MPO"

    # Y la unicidad se mide sobre el normalizado, no sobre lo tipeado.
    with pytest.raises(ReglaDeNegocio, match="Ya existe un punto de venta"):
        servicio.crear_punto(db, autor, "Otro", TipoPuntoVenta.LOCAL, "Mpo")


def test_el_codigo_tiene_entre_2_y_6_caracteres(db, autor):
    for invalido in ("X", "DEMASIADO"):
        with pytest.raises(ReglaDeNegocio, match="entre 2 y 6"):
            servicio.crear_punto(db, autor, "Local", TipoPuntoVenta.LOCAL, invalido)


def test_editar_sin_tocar_el_codigo_no_choca_consigo_mismo(db, autor):
    """
    El control de unicidad tiene que excluir al propio punto de venta: si no,
    cambiarle el nombre fallaría diciendo que su código ya está usado.
    """
    punto = servicio.crear_punto(db, autor, "Patio Olmos", TipoPuntoVenta.LOCAL, "MPO")

    servicio.editar_punto(db, autor, punto.id, nombre="Patio Olmos II", codigo="MPO")

    assert punto.nombre == "Patio Olmos II"
    assert punto.codigo == "MPO"


def test_no_desactivar_con_dispositivos_activos_sin_confirmar(db, autor):
    from app.models.dispositivo import Dispositivo

    local = servicio.crear_punto(db, autor, "Local", TipoPuntoVenta.LOCAL, "LOC")
    db.add(Dispositivo(punto_de_venta_id=local.id, descripcion="Cel 1", activo=True))
    db.flush()

    with pytest.raises(ReglaDeNegocio, match="dispositivo"):
        servicio.cambiar_estado(db, autor, local.id, activo=False)

    # Con confirmación explícita, procede.
    servicio.cambiar_estado(db, autor, local.id, activo=False, confirmar=True)
    assert local.activo is False


def test_alta_registra_en_auditoria(db, autor):
    from sqlalchemy import select

    from app.models.auditoria import Auditoria

    servicio.crear_punto(db, autor, "CD", TipoPuntoVenta.CD, "CD")

    assert db.execute(
        select(Auditoria).where(Auditoria.accion == "punto_venta.crear")
    ).scalars().first() is not None


def test_endpoint_requiere_configuracion(client, crear_usuario, login):
    """Un vendedor sin permiso de configuración → 403."""
    crear_usuario("juan", ROL_VENDEDOR)
    resp = client.get("/api/v1/puntos-de-venta", headers=login("juan"))
    assert resp.status_code == 403


def test_endpoint_alta_y_listado(client, crear_usuario, roles, dar_permiso, login):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    headers = login("admin")

    alta = client.post(
        "/api/v1/puntos-de-venta",
        json={"nombre": "Local Patio Olmos", "tipo": "local", "codigo": "mpo"},
        headers=headers,
    )
    assert alta.status_code == 201
    # Sale en mayúsculas: la normalización es del servicio, no de la pantalla.
    assert alta.json()["codigo"] == "MPO"

    listado = client.get("/api/v1/puntos-de-venta?tipo=local", headers=headers)
    assert listado.status_code == 200
    assert len(listado.json()) == 1
