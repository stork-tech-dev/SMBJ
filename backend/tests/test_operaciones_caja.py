"""
Tests de las operaciones de caja (sesión 09): retiros de efectivo con código,
novedades de caja, retiros de mercadería de empleadas y cobros de joyero, y su
impacto en el arqueo del turno.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_DUENO, ROL_VENDEDOR
from app.models.auditoria import Auditoria
from app.models.cambio import TipoCambio
from app.models.configuracion import ConfiguracionSistema
from app.models.operaciones_caja import TipoNovedad
from app.models.punto_de_venta import TipoPuntoVenta
from app.models.stock import TipoMovimiento
from app.models.venta import Venta
from app.schemas.usuarios import UsuarioResponse
from app.services import arqueo as servicio_arqueo
from app.services import cambios as servicio_cambios
from app.services import categorias as servicio_categorias
from app.services import cobros_joyero as servicio_joyero
from app.services import descuentos as servicio_descuentos
from app.services import medios_pago as servicio_medios
from app.services import novedades_caja as servicio_novedades
from app.services import productos as servicio_productos
from app.services import proveedores as servicio_proveedores
from app.services import retiros as servicio_retiros
from app.services import retiros_mercaderia as servicio_mercaderia
from app.services import stock as servicio_stock
from app.services import turnos as servicio_turnos
from app.services.roles import ReglaDeNegocio

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def autor(crear_usuario):
    return crear_usuario("admin", ROL_CUENTA_MAESTRA)


@pytest.fixture
def config(db, autor):
    fila = ConfiguracionSistema(
        redondeo=Decimal("1.00"),
        descuento_maximo=Decimal("50.00"),
        metodo_descuento="encadenado",
        letra_empresa="S",
        updated_by=autor.id,
    )
    db.add(fila)
    db.flush()
    return fila


@pytest.fixture
def local(crear_punto_de_venta):
    return crear_punto_de_venta("MPO", "Patio Olmos", TipoPuntoVenta.LOCAL)


@pytest.fixture
def turno(db, autor, local):
    return servicio_turnos.abrir_turno(
        punto_de_venta_id=local.id,
        usuario_id=autor.id,
        efectivo_apertura=1000,
        notas=None,
        db=db,
    )


@pytest.fixture
def dueno(db, autor, crear_usuario):
    usuario = crear_usuario("dueno1", ROL_DUENO, nombre="Dueño Uno")
    servicio_retiros.asignar_codigo(db, autor, usuario.id, "1234")
    return usuario


@pytest.fixture
def variante(db, autor, config, local):
    categoria = servicio_categorias.crear_categoria(db, autor, nombre="Plata")
    proveedor = servicio_proveedores.crear_proveedor(
        db, autor, nombre="Joyas del Sur", dolar_actual=Decimal("1")
    )
    producto = servicio_productos.crear_producto(
        db, autor,
        categoria_id=categoria.id,
        proveedor_id=proveedor.id,
        precio_usd=Decimal("10000"),
        descripcion="Anillo plata",
    )
    db.flush()
    v = producto.variantes[0]
    servicio_stock.aplicar_movimiento(
        db, autor,
        tipo=TipoMovimiento.INGRESO_PROVEEDOR,
        variante_id=v.id,
        cantidad=3,
        punto_venta_destino_id=local.id,
    )
    return v


@pytest.fixture
def motivo_empleada(db, autor):
    return servicio_descuentos.crear_motivo(
        db, autor, nombre="Empleada", porcentaje_sugerido=Decimal("30"),
        es_descuento_empleada=True,
    )


def _medio(db, nombre):
    return next(m for m in servicio_medios.listar_medios(db) if m.nombre == nombre)


def _esperado(db, turno, medio):
    resultado = servicio_arqueo.calcular_esperado(turno.id, db)
    return next(i["monto_esperado"] for i in resultado["items"] if i["medio_nombre"] == medio)


# ── Retiros de efectivo ─────────────────────────────────────────────────────


def test_no_se_habilita_el_codigo_de_retiro_a_un_vendedor(db, autor, crear_usuario):
    vendedora = crear_usuario("vende", ROL_VENDEDOR)
    with pytest.raises(ReglaDeNegocio, match="vendedor"):
        servicio_retiros.asignar_codigo(db, autor, vendedora.id, "1111")


def test_el_codigo_son_cuatro_digitos_y_no_se_repite(db, autor, crear_usuario, dueno):
    otro = crear_usuario("dueno2", ROL_DUENO)
    with pytest.raises(ReglaDeNegocio, match="4 dígitos"):
        servicio_retiros.asignar_codigo(db, autor, otro.id, "12a4")
    with pytest.raises(ReglaDeNegocio, match="otra persona"):
        servicio_retiros.asignar_codigo(db, autor, otro.id, "1234")


def test_el_codigo_se_guarda_con_bcrypt_y_no_se_expone(db, dueno):
    assert dueno.puede_retirar is True
    assert dueno.codigo_retiro_hash and dueno.codigo_retiro_hash != "1234"
    assert dueno.codigo_retiro_hash.startswith("$2")
    assert "codigo_retiro_hash" not in UsuarioResponse.model_fields


def test_retiro_valido_identifica_a_quien_retira_y_baja_el_efectivo(
    db, autor, local, turno, dueno,
):
    retiro = servicio_retiros.registrar_retiro(
        db, autor, punto_de_venta_id=local.id, monto=Decimal("300"), codigo="1234"
    )
    assert retiro.usuario_id == dueno.id
    assert retiro.registrado_por_id == autor.id
    assert _esperado(db, turno, "Efectivo") == Decimal("700")


def test_retiro_no_puede_superar_el_efectivo_disponible(db, autor, local, turno, dueno):
    with pytest.raises(ReglaDeNegocio, match="supera el efectivo disponible"):
        servicio_retiros.registrar_retiro(
            db, autor, punto_de_venta_id=local.id, monto=Decimal("1500"), codigo="1234"
        )


def test_codigo_incorrecto_falla_generico_y_queda_auditado(db, autor, local, turno, dueno):
    with pytest.raises(servicio_retiros.CodigoInvalido, match="incorrecto"):
        servicio_retiros.registrar_retiro(
            db, autor, punto_de_venta_id=local.id, monto=Decimal("100"), codigo="9999"
        )
    fallidos = db.execute(
        select(func.count()).where(Auditoria.accion == "caja.retiro_efectivo_fallido")
    ).scalar_one()
    assert fallidos == 1


def test_codigo_revocado_ya_no_sirve(db, autor, local, turno, dueno):
    servicio_retiros.revocar_codigo(db, autor, dueno.id)
    assert dueno.puede_retirar is False
    with pytest.raises(servicio_retiros.CodigoInvalido):
        servicio_retiros.registrar_retiro(
            db, autor, punto_de_venta_id=local.id, monto=Decimal("100"), codigo="1234"
        )


def test_sin_turno_abierto_no_hay_retiro(db, autor, local, dueno):
    with pytest.raises(ReglaDeNegocio, match="turno abierto"):
        servicio_retiros.registrar_retiro(
            db, autor, punto_de_venta_id=local.id, monto=Decimal("100"), codigo="1234"
        )


# ── Novedades de caja ───────────────────────────────────────────────────────


def test_novedades_ajustan_el_efectivo_segun_el_tipo_del_concepto(
    db, autor, local, turno, crear_usuario,
):
    autorizador = crear_usuario("auto", ROL_DUENO, es_autorizador=True)
    gasto = servicio_novedades.crear_concepto(db, autor, "Pago electricista", "salida")
    ingreso = servicio_novedades.crear_concepto(db, autor, "Falla del sistema", "entrada")

    salida = servicio_novedades.registrar_novedad(
        db, autor, punto_de_venta_id=local.id, concepto_id=gasto.id,
        monto=Decimal("200"), autorizador_id=autorizador.id,
    )
    servicio_novedades.registrar_novedad(
        db, autor, punto_de_venta_id=local.id, concepto_id=ingreso.id,
        monto=Decimal("50"), autorizador_id=autorizador.id,
    )

    assert salida.tipo == TipoNovedad.SALIDA
    assert _esperado(db, turno, "Efectivo") == Decimal("850")

    # Cambiar el concepto después no altera lo ya registrado.
    servicio_novedades.editar_concepto(db, autor, gasto.id, tipo="entrada")
    db.refresh(salida)
    assert salida.tipo == TipoNovedad.SALIDA
    assert _esperado(db, turno, "Efectivo") == Decimal("850")


def test_la_novedad_exige_un_autorizador_de_la_lista(db, autor, local, turno, crear_usuario):
    comun = crear_usuario("comun", ROL_DUENO)
    concepto = servicio_novedades.crear_concepto(db, autor, "Gasto", "salida")
    with pytest.raises(ReglaDeNegocio, match="autorizador"):
        servicio_novedades.registrar_novedad(
            db, autor, punto_de_venta_id=local.id, concepto_id=concepto.id,
            monto=Decimal("10"), autorizador_id=comun.id,
        )


# ── Cobros de joyero ────────────────────────────────────────────────────────


def test_joyero_cobra_segun_el_medio_y_suma_al_arqueo_sin_ser_venta(
    db, autor, local, turno,
):
    en_efectivo = servicio_joyero.registrar_cobro(
        db, autor, punto_de_venta_id=local.id,
        medio_de_pago_id=_medio(db, "Efectivo").id,
        monto_efectivo=Decimal("500"), monto_otros=Decimal("600"),
    )
    con_debito = servicio_joyero.registrar_cobro(
        db, autor, punto_de_venta_id=local.id,
        medio_de_pago_id=_medio(db, "Débito").id,
        monto_efectivo=Decimal("500"), monto_otros=Decimal("600"),
        numero_reclamo="R-15",
    )

    assert en_efectivo.monto_cobrado == Decimal("500")
    assert con_debito.monto_cobrado == Decimal("600")
    assert _esperado(db, turno, "Efectivo") == Decimal("1500")
    # Débito se arquea junto con Crédito (migración 0039).
    assert _esperado(db, turno, servicio_arqueo.GRUPO_TARJETAS) == Decimal("600")
    assert db.execute(select(func.count(Venta.id))).scalar_one() == 0


def test_joyero_no_acepta_sena_ni_precio_faltante(db, autor, local, turno):
    with pytest.raises(ReglaDeNegocio, match="seña"):
        servicio_joyero.registrar_cobro(
            db, autor, punto_de_venta_id=local.id,
            medio_de_pago_id=_medio(db, "Seña").id,
            monto_efectivo=Decimal("0"), monto_otros=Decimal("100"),
        )
    with pytest.raises(ReglaDeNegocio, match="Falta el precio"):
        servicio_joyero.registrar_cobro(
            db, autor, punto_de_venta_id=local.id,
            medio_de_pago_id=_medio(db, "Débito").id,
            monto_efectivo=Decimal("100"), monto_otros=Decimal("0"),
        )


# ── Retiros de mercadería ───────────────────────────────────────────────────


def test_sin_motivo_de_empleada_no_hay_retiro(db, autor, local, turno, variante):
    with pytest.raises(ReglaDeNegocio, match="Descuento de empleada"):
        servicio_mercaderia.registrar_retiro(
            db, autor, punto_de_venta_id=local.id, variante_id=variante.id,
            empleada_nombre="Ana Pérez",
        )


def test_un_solo_motivo_de_empleada(db, autor, motivo_empleada):
    with pytest.raises(ReglaDeNegocio, match="ya es el descuento de empleada"):
        servicio_descuentos.crear_motivo(
            db, autor, nombre="Otro", porcentaje_sugerido=Decimal("20"),
            es_descuento_empleada=True,
        )


def test_retiro_de_mercaderia_descuenta_stock_y_no_toca_caja(
    db, autor, local, turno, variante, motivo_empleada, crear_usuario,
):
    empleada = crear_usuario("maria", ROL_VENDEDOR, nombre="María García")
    antes = _esperado(db, turno, "Efectivo")

    retiro = servicio_mercaderia.registrar_retiro(
        db, autor, punto_de_venta_id=local.id, variante_id=variante.id,
        empleada_usuario_id=empleada.id,
    )

    assert retiro.es_empresa_propia is True
    assert retiro.precio_lista == Decimal("10000")
    assert retiro.descuento_aplicado == Decimal("30")
    assert retiro.precio_con_descuento == Decimal("7000")
    assert retiro.codigo_cambio
    assert servicio_stock.cantidad_en(db, variante.id, local.id) == 2
    assert _esperado(db, turno, "Efectivo") == antes
    assert db.execute(select(func.count(Venta.id))).scalar_one() == 0


def test_empleada_de_otra_empresa_requiere_nombre(
    db, autor, local, turno, variante, motivo_empleada,
):
    with pytest.raises(ReglaDeNegocio, match="nombre"):
        servicio_mercaderia.registrar_retiro(
            db, autor, punto_de_venta_id=local.id, variante_id=variante.id,
        )
    retiro = servicio_mercaderia.registrar_retiro(
        db, autor, punto_de_venta_id=local.id, variante_id=variante.id,
        empleada_nombre="Laura Díaz", empleada_dni="30111222",
    )
    assert retiro.es_empresa_propia is False
    assert retiro.nombre_empleada == "Laura Díaz"


def test_reporte_muestra_primero_esta_empresa(
    db, autor, local, turno, variante, motivo_empleada, crear_usuario,
):
    empleada = crear_usuario("zoe", ROL_VENDEDOR, nombre="Zoe")
    servicio_mercaderia.registrar_retiro(
        db, autor, punto_de_venta_id=local.id, variante_id=variante.id,
        empleada_nombre="Ana de la otra",
    )
    servicio_mercaderia.registrar_retiro(
        db, autor, punto_de_venta_id=local.id, variante_id=variante.id,
        empleada_usuario_id=empleada.id,
    )
    filas, total = servicio_mercaderia.reporte(db)
    assert total == 2
    assert [f.es_empresa_propia for f in filas] == [True, False]


def test_el_codigo_del_retiro_se_cambia_al_precio_de_lista(
    db, autor, local, turno, variante, motivo_empleada,
):
    retiro = servicio_mercaderia.registrar_retiro(
        db, autor, punto_de_venta_id=local.id, variante_id=variante.id,
        empleada_nombre="Laura Díaz",
    )

    with pytest.raises(ReglaDeNegocio, match="cambio común"):
        servicio_cambios.iniciar_cambio(
            db, autor, tipo=TipoCambio.PROMOCION, punto_de_venta_id=local.id,
            codigo_cambio=retiro.codigo_cambio,
        )

    cambio, _avisos = servicio_cambios.iniciar_cambio(
        db, autor, tipo=TipoCambio.COMUN, punto_de_venta_id=local.id,
        codigo_cambio=retiro.codigo_cambio,
    )
    assert cambio.retiro_mercaderia_origen_id == retiro.id

    item, _ = servicio_cambios.agregar_item_devuelto(db, cambio, variante.id)
    assert item.precio_reconocido == Decimal("10000")

    # El retiro es una unidad: no entra dos veces en el mismo cambio.
    with pytest.raises(ReglaDeNegocio, match="ya está entre los devueltos"):
        servicio_cambios.agregar_item_devuelto(db, cambio, variante.id)


# ── API y pantallas (extremo a extremo) ─────────────────────────────────────


@pytest.fixture
def vendedora_en_local(client, db, crear_usuario, dar_permiso, roles, local):
    """Vendedora logueada en un celular asignado al local, con permiso de caja."""
    from app.models.dispositivo import Dispositivo

    crear_usuario("vende", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo="caja", ver=True, crear=True)
    equipo = Dispositivo(punto_de_venta_id=local.id, activo=True, descripcion="Caja MPO")
    db.add(equipo)
    db.commit()
    client.cookies.set("device_uuid", str(equipo.uuid))
    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})
    return client


def test_api_retiro_codigo_incorrecto_da_403_y_deja_el_intento_auditado(
    db, vendedora_en_local, turno, dueno,
):
    db.commit()
    client = vendedora_en_local

    assert Decimal(client.get("/api/v1/retiros-efectivo/disponible").json()["disponible"]) == Decimal("1000")

    resp = client.post("/api/v1/retiros-efectivo", json={"monto": "100", "codigo": "0000"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Código de autorización incorrecto"
    assert db.execute(
        select(func.count()).where(Auditoria.accion == "caja.retiro_efectivo_fallido")
    ).scalar_one() == 1

    resp = client.post("/api/v1/retiros-efectivo", json={"monto": "100", "codigo": "1234"})
    assert resp.status_code == 201
    assert resp.json()["usuario_nombre"] == "Dueño Uno"
    assert "codigo" not in resp.json()


@pytest.mark.parametrize(
    "ruta",
    [
        "/caja/operaciones",
        "/caja/retiro-efectivo",
        "/caja/novedad",
        "/caja/retiro-mercaderia",
        "/caja/cobro-joyero",
    ],
)
def test_pantallas_de_operaciones_se_sirven_en_el_celular_del_local(vendedora_en_local, ruta):
    resp = vendedora_en_local.get(ruta)
    assert resp.status_code == 200
    assert "permiso para operar la caja" not in resp.text


def test_el_home_mobile_ofrece_operaciones_de_caja(vendedora_en_local):
    resp = vendedora_en_local.get("/ventas")
    assert 'href="/caja/operaciones"' in resp.text


@pytest.mark.parametrize(
    "ruta, texto",
    [
        ("/conceptos-novedad", "Conceptos de novedad"),
        ("/reportes/caja/retiros-mercaderia", "Retiros de mercadería"),
        ("/motivos-descuento", "Descuento de empleada"),
        ("/usuarios", "Código de retiro de efectivo"),
        ("/configuracion", "/conceptos-novedad"),
        ("/reportes/caja", "/reportes/caja/retiros-mercaderia"),
    ],
)
def test_pantallas_de_escritorio_de_la_sesion_09(client, db, autor, ruta, texto):
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})
    resp = client.get(ruta)
    assert resp.status_code == 200
    assert texto in resp.text
