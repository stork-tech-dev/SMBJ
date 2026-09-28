"""
Tests del servicio de arqueo (cierre de turno).

El arqueo esperado tiene que listar SIEMPRE todos los medios de pago
activos, hayan tenido pagos en el turno o no: si un medio sin movimiento
queda afuera de la lista, la pantalla de cierre no ofrece dónde declararlo
y la vendedora no puede cerrar correctamente (bug reportado en producción
con Efectivo y Débito faltando cuando el turno solo tuvo ventas con otro
medio).
"""

from decimal import Decimal

import pytest

from app.core.device_scope import DeviceScope
from app.core.permisos import ROL_CUENTA_MAESTRA
from app.models.configuracion import ConfiguracionSistema
from app.models.dispositivo import Dispositivo
from app.models.punto_de_venta import TipoPuntoVenta
from app.models.stock import TipoMovimiento
from app.models.turno import EstadoTurno
from app.services import arqueo as servicio_arqueo
from app.services import categorias as servicio_categorias
from app.services import medios_pago as servicio_medios
from app.services import productos as servicio_productos
from app.services import proveedores as servicio_proveedores
from app.services import stock as servicio_stock
from app.services import turnos as servicio_turnos
from app.services import ventas as servicio_ventas

LIBRE = DeviceScope(restringido=False)


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
def dispositivo(db, local):
    equipo = Dispositivo(punto_de_venta_id=local.id, activo=True, descripcion="Celu 1")
    db.add(equipo)
    db.flush()
    return equipo


@pytest.fixture
def catalogo(db, autor, config):
    categoria = servicio_categorias.crear_categoria(db, autor, nombre="Plata")
    proveedor = servicio_proveedores.crear_proveedor(
        db, autor, nombre="Joyas del Sur", dolar_actual=Decimal("1")
    )
    return categoria, proveedor


@pytest.fixture
def crear_variante(db, autor, catalogo):
    categoria, proveedor = catalogo

    def _crear(descripcion: str, precio: str):
        producto = servicio_productos.crear_producto(
            db, autor,
            categoria_id=categoria.id,
            proveedor_id=proveedor.id,
            precio_usd=Decimal(precio),
            descripcion=descripcion,
        )
        db.flush()
        return producto.variantes[0]

    return _crear


@pytest.fixture
def con_stock(db, autor, local):
    def _cargar(variante, cantidad: int):
        servicio_stock.aplicar_movimiento(
            db, autor,
            tipo=TipoMovimiento.INGRESO_PROVEEDOR,
            variante_id=variante.id,
            cantidad=cantidad,
            punto_venta_destino_id=local.id,
        )

    return _cargar


def _medio(db, nombre):
    """Los medios base (Efectivo, Débito, Tarjeta de Crédito, Seña) vienen
    del seed de la migración 0024: crear otro con el mismo nombre choca
    contra el UNIQUE, así que se buscan en vez de crearse."""
    return next(m for m in servicio_medios.listar_medios(db) if m.nombre == nombre)


def _turno(db, autor, local, efectivo_apertura=0):
    return servicio_turnos.abrir_turno(
        punto_de_venta_id=local.id,
        usuario_id=autor.id,
        efectivo_apertura=efectivo_apertura,
        notas=None,
        db=db,
    )


def test_arqueo_incluye_medios_sin_movimiento_en_el_turno(
    db, autor, local, dispositivo, crear_variante, con_stock,
):
    """Si el turno solo tuvo ventas con Tarjeta de Crédito, Efectivo y
    Débito igual tienen que listarse en $0 — antes del fix desaparecían."""
    turno = _turno(db, autor, local)

    tarjeta = _medio(db, "Tarjeta de Crédito")
    variante = crear_variante("Anillo", "1000")
    con_stock(variante, 5)

    venta = servicio_ventas.iniciar_venta(db, autor, dispositivo, LIBRE)
    servicio_ventas.agregar_item(db, autor, venta, variante_id=variante.id)
    servicio_ventas.registrar_pagos(
        db, autor, venta, [{"medio_de_pago_id": tarjeta.id, "monto": Decimal("1000")}]
    )
    servicio_ventas.confirmar_venta(db, autor, venta, LIBRE)

    resultado = servicio_arqueo.calcular_esperado(turno.id, db)
    montos = {i["medio_nombre"]: i["monto_esperado"] for i in resultado["items"]}

    assert montos["Efectivo"] == Decimal("0")
    assert montos["Débito"] == Decimal("0")
    assert montos["Tarjeta de Crédito"] == Decimal("1000")


def test_arqueo_sin_ninguna_venta_lista_igual_todos_los_medios_activos(
    db, autor, local,
):
    """Turno recién abierto, sin ventas: todos los medios activos tienen
    que aparecer en $0, no una lista vacía."""
    turno = _turno(db, autor, local)

    resultado = servicio_arqueo.calcular_esperado(turno.id, db)
    nombres = {i["medio_nombre"] for i in resultado["items"]}

    assert {"Efectivo", "Débito", "Tarjeta de Crédito", "Seña"} <= nombres
    assert all(i["monto_esperado"] == Decimal("0") for i in resultado["items"])
    assert resultado["total_esperado"] == Decimal("0")


def test_retiro_sin_ventas_en_efectivo_se_descuenta_de_la_apertura(
    db, autor, local, crear_usuario,
):
    """Sin ventas en efectivo, la línea de Efectivo igual existe y refleja
    apertura menos retiros (antes del fix, sin pagos el retiro no se veía)."""
    from app.services import retiros as servicio_retiros

    dueno = crear_usuario("dueno1", "dueno")
    servicio_retiros.asignar_codigo(db, autor, dueno.id, "4321")
    turno = _turno(db, autor, local, efectivo_apertura=1000)
    servicio_retiros.registrar_retiro(
        db, autor, punto_de_venta_id=local.id, monto=Decimal("400"), codigo="4321"
    )

    resultado = servicio_arqueo.calcular_esperado(turno.id, db)
    montos = {i["medio_nombre"]: i["monto_esperado"] for i in resultado["items"]}

    assert montos["Efectivo"] == Decimal("600")


def test_registrar_arqueo_cierra_el_turno_sin_diferencia(db, autor, local):
    """
    Extremo a extremo: declarar exactamente lo esperado tiene que cerrar el
    turno y dejar `diferencia` en $0. `diferencia` es GENERATED ALWAYS AS en
    la base (arqueos.diferencia / arqueo_items.diferencia); si el modelo
    SQLAlchemy no la marca con `Computed()`, el INSERT falla con
    "cannot insert a non-DEFAULT value into column" apenas se intenta cerrar
    cualquier turno — el bug real detrás de "No se pudo cerrar el turno".
    """
    turno = _turno(db, autor, local, efectivo_apertura=1000)

    resultado = servicio_arqueo.calcular_esperado(turno.id, db)
    items = [{**i, "monto_declarado": i["monto_esperado"]} for i in resultado["items"]]

    arqueo = servicio_arqueo.registrar_arqueo(
        turno_id=turno.id,
        items_declarados=items,
        total_declarado=resultado["total_esperado"],
        usuario_id=autor.id,
        db=db,
    )

    assert arqueo.diferencia == Decimal("0")
    assert all(item.diferencia == Decimal("0") for item in arqueo.items)
    assert turno.estado == EstadoTurno.CERRADO


def test_registrar_arqueo_calcula_diferencia_cuando_lo_declarado_no_coincide(
    db, autor, local,
):
    """Declarar de más también tiene que insertar bien (columna generada
    calculada por Postgres, no por el ORM) y reflejarse en `diferencia`."""
    turno = _turno(db, autor, local)

    resultado = servicio_arqueo.calcular_esperado(turno.id, db)
    items = [{**i, "monto_declarado": i["monto_esperado"]} for i in resultado["items"]]
    efectivo_item = next(i for i in items if i["medio_nombre"] == "Efectivo")
    efectivo_item["monto_declarado"] = efectivo_item["monto_esperado"] + Decimal("200")

    arqueo = servicio_arqueo.registrar_arqueo(
        turno_id=turno.id,
        items_declarados=items,
        total_declarado=resultado["total_esperado"] + Decimal("200"),
        usuario_id=autor.id,
        db=db,
    )

    assert arqueo.diferencia == Decimal("200")


# ── Efectivo inicial: lo contado al cierre anterior ─────────────────────────


def _cerrar_declarando_efectivo(db, autor, turno, efectivo):
    """Cierra el turno declarando `efectivo` en la línea de Efectivo."""
    esperado = servicio_arqueo.calcular_esperado(turno.id, db)
    items = [{**i, "monto_declarado": i["monto_esperado"]} for i in esperado["items"]]
    linea = next(i for i in items if i["medio_nombre"] == "Efectivo")
    linea["monto_declarado"] = Decimal(efectivo)
    servicio_arqueo.registrar_arqueo(
        turno_id=turno.id, items_declarados=items,
        total_declarado=sum(i["monto_declarado"] for i in items),
        usuario_id=autor.id, db=db,
    )


def test_sin_cierre_anterior_no_hay_efectivo_sugerido(db, local):
    assert servicio_turnos.efectivo_cierre_anterior(local.id, db) is None


def test_efectivo_del_cierre_anterior_es_lo_contado_del_ultimo_cierre(
    db, autor, local, crear_punto_de_venta,
):
    otro = crear_punto_de_venta("MPJ", "Paseo del Jockey", TipoPuntoVenta.LOCAL)

    primero = _turno(db, autor, local, efectivo_apertura=1000)
    _cerrar_declarando_efectivo(db, autor, primero, "900")  # contó menos de lo esperado
    segundo = _turno(db, autor, local, efectivo_apertura=900)
    _cerrar_declarando_efectivo(db, autor, segundo, "15000")
    _cerrar_declarando_efectivo(db, autor, _turno(db, autor, otro), "1")

    anterior = servicio_turnos.efectivo_cierre_anterior(local.id, db)
    assert anterior["efectivo"] == Decimal("15000")
    assert anterior["turno_id"] == segundo.id


def test_abrir_turno_deja_en_la_auditoria_el_cierre_anterior(db, autor, local):
    from sqlalchemy import select

    from app.models.auditoria import Auditoria

    _cerrar_declarando_efectivo(db, autor, _turno(db, autor, local), "15000")
    nuevo = _turno(db, autor, local, efectivo_apertura=14000)  # la vendedora corrigió

    registro = db.execute(
        select(Auditoria).where(
            Auditoria.accion == "turno.abierto", Auditoria.entidad_id == nuevo.id
        )
    ).scalar_one()
    assert Decimal(str(registro.estado_nuevo["efectivo_cierre_anterior"])) == Decimal("15000")
    assert Decimal(str(registro.estado_nuevo["efectivo_apertura"])) == Decimal("14000")


def test_api_efectivo_cierre_anterior(
    client, db, autor, local, dispositivo, crear_usuario, dar_permiso, roles,
):
    """Una vendedora en el celular del local, que es quien abre el turno."""
    from app.core.permisos import ROL_VENDEDOR

    _cerrar_declarando_efectivo(db, autor, _turno(db, autor, local), "15000")
    crear_usuario("vende", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo="caja", ver=True, crear=True)
    db.commit()
    client.cookies.set("device_uuid", str(dispositivo.uuid))
    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})

    datos = client.get("/api/v1/turnos/efectivo-cierre-anterior").json()
    assert Decimal(str(datos["efectivo"])) == Decimal("15000")
    assert datos["fecha_cierre"] is not None
