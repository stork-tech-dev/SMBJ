"""
Tests del módulo de etiquetas: el motor ZPL (portado del prototipo del
cliente), la preparación por rollo, impresoras, diseños con versiones, el
origen de las etiquetas, permisos y las pantallas.
"""

import json

import pytest

from app.core.etiquetas.motor import Etiqueta, Motor
from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_DUENO, ROL_VENDEDOR, Modulo
from app.models.auditoria import Auditoria
from app.models.compra import Compra, CompraItem, EstadoCompra
from app.models.etiqueta import EtiquetaDiseno, EtiquetaFormato
from app.schemas.etiquetas import ParametrosDiseno
from app.services import etiquetas as servicio

from tests.test_arqueo import autor, catalogo, config, crear_variante, local  # noqa: F401

MULTIPLE, COLITA = 1, 2  # ids que siembra la migración 0043
APROBADO = 1


# ── El motor: lo que ya se imprimió y se leyó ──────────────────────────────

# Los dos ejemplos de "Ejemplos de ZPL que ya funcionaron" del documento de
# requisitos del cliente: se imprimieron el 19/10/2026 en las Zebra y se
# leyeron con el celular. El motor tiene que dar exactamente esto.
ZPL_MULTIPLE_APROBADO = """^XA
^CI28
~SD14
^PR2,2,2
^PW816
^LL80
^LH0,0
^PON
^FO8,12^BXN,4,200,14,14^FDMAA009R4^FS
^FO72,27^AFN,26,13^FB176,1,0,C^FDMAA009R4^FS
^FO288,12^BXN,4,200,14,14^FDMAA009R4^FS
^FO352,21^A0N,16,16^FB176,1,0,C^FDARO PERLA^FS
^FO352,41^ADN,18,10^FB176,1,0,C^FDMAA009R4^FS
^FO568,32^A0N,16,16^FB240,1,0,C^FDSALE^FS
^PQ1
^XZ
"""

# En el documento el texto de la colita va de corrido y `^FB` lo parte
# solo; el motor lo parte él con `\&` en el mismo lugar, para que la vista
# previa corte igual que lo impreso. Es la única diferencia.
ZPL_COLITA_APROBADO = """^XA
^CI28
~SD14
^PR2,2,2
^PW528
^LL88
^LH0,0
^POI
^FO38,16^BXN,4,200,14,14^FDMAA009R4^FS
^FO148,19^A0N,14,14^FB108,2,0,C^FDPULSERA\\&ACERO DORADO^FS
^FO148,51^ADN,18,10^FB108,1,0,C^FDMAA009R4^FS
^PQ1
^XZ
"""

FICHA_SISTEMA_VIEJO = {"oscuridad": 14, "velocidad": 2}


def _motor(db, formato_id):
    formato = db.get(EtiquetaFormato, formato_id)
    diseno = db.get(EtiquetaDiseno, APROBADO)
    return Motor(servicio.formato_para_motor(formato), diseno.parametros)


def test_la_fila_multiple_sale_igual_a_la_aprobada(db):
    fila = [Etiqueta("MAA009R4"), Etiqueta("MAA009R4", "ARO PERLA"), Etiqueta(None, "SALE")]
    zpl, avisos = _motor(db, MULTIPLE).zpl_fila(fila, FICHA_SISTEMA_VIEJO)

    assert zpl == ZPL_MULTIPLE_APROBADO
    assert not [a for a in avisos if a.nivel == "error"]


def test_la_colita_sale_igual_a_la_aprobada(db):
    zpl, _ = _motor(db, COLITA).zpl_fila(
        [Etiqueta("MAA009R4", "PULSERA ACERO DORADO")], FICHA_SISTEMA_VIEJO
    )
    assert zpl == ZPL_COLITA_APROBADO


def test_los_ajustes_de_la_ficha_van_dentro_del_zpl(db):
    ficha = {"oscuridad": 20, "velocidad": 3, "corrimiento_x_mm": 1, "corrimiento_y_mm": -0.5}
    zpl, _ = _motor(db, MULTIPLE).zpl_fila([Etiqueta("MAA009R4")], ficha)

    assert "~SD20" in zpl and "^PR3,3,3" in zpl
    # El corrimiento se suma a cada posición: 8+8 y 12-4.
    assert "^FO16,8^BXN" in zpl


@pytest.mark.parametrize("codigo,mensaje", [
    ("MAA-009", "caracteres no válidos"),
    ("MAA0091234", "más de 8 caracteres"),
])
def test_un_codigo_invalido_no_deja_imprimir(db, codigo, mensaje):
    _, avisos = _motor(db, MULTIPLE).zpl_fila([Etiqueta(codigo)], FICHA_SISTEMA_VIEJO)
    assert any(a.nivel == "error" and mensaje in a.texto for a in avisos)


def test_un_texto_largo_se_achica_o_avisa_que_no_entra(db):
    motor = _motor(db, MULTIPLE)

    _, avisos = motor.zpl_fila([Etiqueta("MAA009R4", "PULSERA ACERO DORADO")], {})
    assert any(a.nivel == "ojo" and "2 renglones" in a.texto for a in avisos)

    _, avisos = motor.zpl_fila([Etiqueta("MAA009R4", "X" * 60)], {})
    assert any(a.nivel == "error" and "no entra" in a.texto for a in avisos)


def test_las_filas_iguales_van_en_una_sola_orden(db):
    motor = _motor(db, COLITA)
    ordenes, _, filas = motor.trabajos([Etiqueta("MAA009R4", copias=10)], {})

    assert len(filas) == 10
    assert len(ordenes) == 1 and "^PQ10" in ordenes[0]


# ── Preparar: repartir por rollo ───────────────────────────────────────────


class _Pedida:
    def __init__(self, variante_id=None, texto=None, copias=1, formato_id=MULTIPLE):
        self.variante_id, self.texto, self.copias, self.formato_id = variante_id, texto, copias, formato_id


@pytest.fixture
def impresoras(db, autor):
    stella = servicio.crear_impresora(db, autor.id, "Zebra de STELLA", r"\\STELLA\ZDesigner GC420t (EPL)")
    lenovo = servicio.crear_impresora(db, autor.id, "Zebra de la Lenovo", r"\\PCMAYORISTA\ZDesigner GC420t")
    servicio.asignar_impresora(db, autor.id, MULTIPLE, stella.id)
    servicio.asignar_impresora(db, autor.id, COLITA, lenovo.id)
    return stella, lenovo


def test_un_rollo_sin_impresora_no_deja_imprimir(db, crear_variante):
    variante = crear_variante("Aro perla", "10")
    resultado = servicio.preparar(db, APROBADO, [_Pedida(variante.id)])

    (grupo,) = resultado["grupos"]
    assert not resultado["puede_imprimir"]
    assert "no tiene impresora asignada" in grupo["avisos"][0]["texto"]


def test_preparar_reparte_por_rollo_y_pone_el_codigo_de_la_variante(db, crear_variante, impresoras):
    stella, lenovo = impresoras
    aro = crear_variante("Aro perla", "10")
    resultado = servicio.preparar(db, APROBADO, [
        _Pedida(aro.id, copias=4),
        _Pedida(None, "LIQUIDACION 50%", formato_id=COLITA),
    ])

    multiple, colita = resultado["grupos"]
    assert resultado["puede_imprimir"]
    assert resultado["total_etiquetas"] == 5
    assert multiple["impresora"]["id"] == stella.id and colita["impresora"]["id"] == lenovo.id
    assert f"^FD{aro.codigo_con_verificador}^FS" in multiple["trabajos"][0]
    # 4 etiquetas en filas de 3: dos filas, la segunda con 2 en blanco.
    assert multiple["filas"] == 2
    assert any("quedan 2 etiquetas en blanco" in a["texto"] for a in multiple["avisos"])
    assert multiple["vista_previa"][0].startswith("<svg")


def test_preparar_con_un_diseno_archivado_o_una_variante_que_no_existe(db, autor, impresoras):
    with pytest.raises(servicio.NoEncontrado):
        servicio.preparar(db, APROBADO, [_Pedida(999999)])

    copia = servicio.duplicar_diseno(db, autor.id, APROBADO)
    servicio.cambiar_archivado(db, autor.id, copia.id, True)
    with pytest.raises(servicio.ReglaDeNegocio):
        servicio.preparar(db, copia.id, [_Pedida(None, "SALE")])


# ── Origen: compra, variante o código ──────────────────────────────────────


def test_el_origen_de_una_compra_trae_la_cantidad_como_copias(db, autor, catalogo, local, crear_variante):
    _, proveedor = catalogo
    aro, anillo = crear_variante("Aro perla", "10"), crear_variante("Anillo", "20")
    compra = Compra(proveedor_id=proveedor.id, punto_de_venta_id=local.id,
                    estado=EstadoCompra.CERRADA, usuario_carga_id=autor.id)
    db.add(compra)
    db.flush()
    db.add_all([
        CompraItem(compra_id=compra.id, variante_id=aro.id, cantidad=12, precio_usd_nuevo=1),
        CompraItem(compra_id=compra.id, variante_id=anillo.id, cantidad=3, precio_usd_nuevo=1),
    ])
    db.flush()

    renglones = servicio.renglones_de_compra(db, compra.id)

    assert [(r["variante_id"], r["copias"]) for r in renglones] == [(aro.id, 12), (anillo.id, 3)]
    assert renglones[0]["codigo"] == aro.codigo_con_verificador


def test_el_origen_por_codigo_acepta_con_y_sin_digito(db, crear_variante):
    aro = crear_variante("Aro perla", "10")

    for texto in (aro.codigo_con_verificador, aro.codigo_completo):
        assert servicio.renglon_de_codigo(db, texto)["variante_id"] == aro.id
    with pytest.raises(servicio.NoEncontrado):
        servicio.renglon_de_codigo(db, "ZZZ999")


# ── Impresoras ─────────────────────────────────────────────────────────────


def _acciones(db, entidad):
    return [a.accion for a in db.query(Auditoria).filter(Auditoria.entidad == entidad).order_by(Auditoria.id)]


def test_impresoras_crear_editar_quitar_y_auditar(db, autor, impresoras):
    stella, _ = impresoras

    with pytest.raises(servicio.ReglaDeNegocio, match="ya está cargada"):
        servicio.crear_impresora(db, autor.id, "Otra", stella.browser_print)

    servicio.editar_impresora(db, autor.id, stella.id, {"oscuridad": 18, "nombre": "STELLA"})
    assert stella.oscuridad == 18

    with pytest.raises(servicio.ReglaDeNegocio, match="Primero asigná otra impresora"):
        servicio.quitar_impresora(db, autor.id, stella.id)
    servicio.asignar_impresora(db, autor.id, MULTIPLE, None)
    servicio.quitar_impresora(db, autor.id, stella.id)
    assert stella not in servicio.listar_impresoras(db)

    assert _acciones(db, "etiqueta_impresoras") == [
        "etiqueta_impresora.crear", "etiqueta_impresora.crear",
        "etiqueta_impresora.editar", "etiqueta_impresora.quitar",
    ]
    assert "etiqueta_formato.asignar" in _acciones(db, "etiqueta_formatos")


def test_la_prueba_usa_el_rollo_y_la_ficha_de_la_impresora(db, autor, impresoras):
    _, lenovo = impresoras
    servicio.editar_impresora(db, autor.id, lenovo.id, {"oscuridad": 9})

    zpl, svg = servicio.zpl_prueba(db, lenovo.id)

    assert "^POI" in zpl and "~SD09" in zpl and "PRUEBA01" in zpl
    assert svg.startswith("<svg")


# ── Diseños ────────────────────────────────────────────────────────────────


def test_editar_un_diseno_guarda_versiones_y_se_puede_volver(db, autor):
    original = db.get(EtiquetaDiseno, APROBADO).parametros
    nuevos = ParametrosDiseno(**{**original, "codigo_max": 7})

    diseno = servicio.editar_diseno(db, autor.id, APROBADO, parametros=nuevos)
    assert diseno.version == 2 and diseno.parametros["codigo_max"] == 7

    diseno = servicio.restaurar_version(db, autor.id, APROBADO, 1)
    assert diseno.version == 3 and diseno.parametros == original
    assert [v.version for v in servicio.versiones_diseno(db, APROBADO)] == [3, 2, 1]
    assert _acciones(db, "etiqueta_disenos")[-2:] == ["etiqueta_diseno.editar", "etiqueta_diseno.restaurar"]


def test_no_se_archiva_el_unico_diseno(db, autor):
    with pytest.raises(servicio.ReglaDeNegocio, match="único diseño"):
        servicio.cambiar_archivado(db, autor.id, APROBADO, True)


def test_la_vista_previa_de_un_diseno_trae_los_dos_rollos(db):
    rollos = servicio.vista_previa_diseno(db, ParametrosDiseno())

    assert [r["formato_id"] for r in rollos] == [MULTIPLE, COLITA]
    assert all(r["vista_previa"] and r["zpl"] for r in rollos)


# ── API y permisos ─────────────────────────────────────────────────────────


@pytest.fixture
def como(client, db, crear_usuario, roles, dar_permiso):
    """Entra con un usuario nuevo; `productos=True` le da el permiso de ver Productos."""

    def _entrar(username, rol, productos=False):
        crear_usuario(username, rol)
        if productos:
            dar_permiso(rol_id=roles[rol].id, modulo=Modulo.PRODUCTOS, ver=True)
        db.commit()
        client.post("/api/v1/auth/login", json={"username": username, "password": "Test1234!"})
        return client

    return _entrar


def test_bajar_y_subir_un_diseno(como):
    cliente = como("cm", ROL_CUENTA_MAESTRA)
    archivo = cliente.get(f"/api/v1/etiquetas/disenos/{APROBADO}/archivo")
    assert archivo.status_code == 200
    contenido = archivo.json()
    contenido["nombre"] = "Subido"

    resp = cliente.post("/api/v1/etiquetas/disenos/importar",
                        files={"archivo": ("d.json", json.dumps(contenido), "application/json")})
    assert resp.status_code == 201, resp.text
    assert resp.json()["nombre"] == "Subido"

    contenido["parametros"]["matriz"]["tamano"] = 3  # campo que no existe
    resp = cliente.post("/api/v1/etiquetas/disenos/importar",
                        files={"archivo": ("d.json", json.dumps(contenido), "application/json")})
    assert resp.status_code == 422 and "matriz.tamano" in resp.json()["detail"]


def test_la_api_de_imprimir_trae_el_origen_y_prepara(como, crear_variante):
    aro = crear_variante("Aro perla", "10")
    cliente = como("dueno", ROL_DUENO, productos=True)

    renglones = cliente.get("/api/v1/etiquetas/origen", params={"variante_id": aro.id, "copias": 2}).json()
    assert renglones["renglones"][0]["copias"] == 2

    resp = cliente.post("/api/v1/etiquetas/preparar", json={
        "diseno_id": APROBADO,
        "etiquetas": [{"variante_id": aro.id, "copias": 2, "formato_id": MULTIPLE}],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_etiquetas"] == 2


def test_el_vendedor_no_imprime_y_solo_la_maestra_administra(como):
    vendedor = como("vende", ROL_VENDEDOR)
    assert vendedor.post("/api/v1/etiquetas/preparar", json={"diseno_id": 1, "etiquetas": []}).status_code == 403

    dueno = como("dueno", ROL_DUENO, productos=True)
    assert dueno.get("/api/v1/etiquetas/formatos").status_code == 200
    assert dueno.get("/api/v1/etiquetas/impresoras").status_code == 403
    assert dueno.post("/api/v1/etiquetas/impresoras", json={"nombre": "x", "browser_print": "y"}).status_code == 403


def test_el_origen_pide_uno_solo(como):
    cliente = como("dueno", ROL_DUENO, productos=True)
    assert cliente.get("/api/v1/etiquetas/origen").status_code == 422
    assert cliente.get("/api/v1/etiquetas/origen", params={"compra_id": 1, "codigo": "X"}).status_code == 422


# ── Pantallas ──────────────────────────────────────────────────────────────


def test_las_pantallas_de_etiquetas(como):
    cliente = como("cm", ROL_CUENTA_MAESTRA)

    imprimir = cliente.get("/etiquetas").text
    assert "etiquetasImprimir(" in imprimir and "browserprint.js" in imprimir
    # El buscador de producto con la lista de coincidencias y su foto, como
    # el del Historial del Producto; "Cargar una compra" queda oculto.
    assert 'x-for="v in resultados"' in imprimir and "v.foto_url" in imprimir
    assert 'class="hidden' in imprimir.split("Cargar una compra")[0].rsplit("<button", 1)[1]
    disenos = cliente.get("/etiquetas/disenos").text
    assert "disenosEtiqueta()" in disenos and "Lado en módulos" in disenos


def test_disenos_es_solo_de_la_cuenta_maestra(como):
    cliente = como("dueno", ROL_DUENO, productos=True)
    assert cliente.get("/etiquetas/disenos", follow_redirects=False).status_code == 303
    assert cliente.get("/etiquetas").status_code == 200


def test_productos_y_compras_llevan_a_la_pantalla_de_etiquetas(como):
    """Los dos botones viejos (Rectangular / Con colita) son ahora uno solo."""
    cliente = como("cm", ROL_CUENTA_MAESTRA)

    productos = cliente.get("/productos").text
    assert "'/etiquetas?variante_id=' + v.id" in productos
    assert "Con colita" not in productos and "imprimirEtiquetas(" not in productos

    compra = cliente.get("/compras/nueva").text
    assert "'/etiquetas?compra_id=' + compraId" in compra
    assert "imprimirEtiquetasCompra" not in compra

    # El listado de compras también lleva, fila por fila, sin abrir el detalle.
    listado = cliente.get("/compras").text
    assert "'/etiquetas?compra_id=' + c.id" in listado and 'title="Imprimir Etiquetas"' in listado

    assert cliente.post("/api/v1/productos/etiquetas", json={}).status_code in (404, 405)
