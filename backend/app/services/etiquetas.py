"""
Lógica del módulo de etiquetas: impresoras, rollos, diseños y la
preparación de lo que se imprime.

Dos reglas del cliente, que valen para cualquier consumidor de la API:
  - El ZPL lo arma SIEMPRE el servidor (acá, con `app/core/etiquetas`). El
    navegador solo se lo pasa a Zebra Browser Print.
  - El código de cada etiqueta lo pone el servidor desde la variante: no se
    imprime un código que el cliente haya escrito a mano.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.etiquetas.motor import (
    DpiNoSoportado,
    Etiqueta,
    Motor,
    avisos_sin_repetir,
    zpl_calibrar,
)
from app.core.etiquetas.vista_previa import svg_fila
from app.core.utils import ahora_db
from app.models.compra import Compra, CompraItem, EstadoCompra
from app.models.etiqueta import EtiquetaDiseno, EtiquetaDisenoVersion, EtiquetaFormato, EtiquetaImpresora
from app.models.producto import Variante
from app.schemas.etiquetas import ParametrosDiseno
from app.services.roles import NoEncontrado, ReglaDeNegocio

# Cuántas filas distintas se dibujan en la vista previa de cada rollo.
FILAS_VISTA_PREVIA = 6

# Código de ejemplo para la vista previa de un diseño: el mismo del
# documento del diseño aprobado (8 caracteres, el máximo de hoy).
CODIGO_DE_EJEMPLO = "MAA009R4"


# ============================================================================
# Conversión a lo que entiende el motor (diccionarios en mm)
# ============================================================================


def formato_para_motor(formato: EtiquetaFormato) -> dict:
    return {
        "nombre": formato.nombre,
        "ancho_rollo_mm": float(formato.ancho_rollo_mm),
        "columnas": formato.columnas,
        "paso_mm": float(formato.paso_mm),
        "etiqueta": {"ancho_mm": float(formato.ancho_mm), "alto_mm": float(formato.alto_mm)},
        "zona_mm": [float(formato.zona_desde_mm), float(formato.zona_hasta_mm)],
        "doblez_mm": float(formato.doblez_mm) if formato.doblez_mm is not None else None,
        "giro": formato.giro.value,
    }


def ficha_para_motor(impresora: EtiquetaImpresora | None) -> dict:
    """Los ajustes de la ficha que van dentro del ZPL. Sin impresora, los de siempre."""
    if impresora is None:
        return {}
    return {
        "corrimiento_x_mm": float(impresora.corrimiento_x_mm),
        "corrimiento_y_mm": float(impresora.corrimiento_y_mm),
        "oscuridad": impresora.oscuridad,
        "velocidad": impresora.velocidad,
    }


# ============================================================================
# Rollos
# ============================================================================


def listar_formatos(db: Session) -> list[EtiquetaFormato]:
    return list(db.execute(select(EtiquetaFormato).order_by(EtiquetaFormato.id)).scalars())


def obtener_formato(db: Session, formato_id: int) -> EtiquetaFormato:
    formato = db.get(EtiquetaFormato, formato_id)
    if formato is None:
        raise NoEncontrado(f"No existe el tipo de etiqueta {formato_id}")
    return formato


def asignar_impresora(
    db: Session, autor_id: int, formato_id: int, impresora_id: int | None, ip_origen: str | None = None
) -> EtiquetaFormato:
    """
    Qué impresora imprime un rollo. Cada rollo tiene UNA: al imprimir no se
    elige, así no se manda una colita a la Zebra que tiene la múltiple.
    """
    formato = obtener_formato(db, formato_id)
    if impresora_id is not None:
        obtener_impresora(db, impresora_id)
    if formato.impresora_id == impresora_id:
        return formato

    anterior = {"impresora_id": formato.impresora_id}
    formato.impresora_id = impresora_id
    db.flush()
    registrar_auditoria(
        db, usuario_id=autor_id, accion="etiqueta_formato.asignar", entidad="etiqueta_formatos",
        entidad_id=formato.id, estado_anterior=anterior, estado_nuevo={"impresora_id": impresora_id},
        ip_origen=ip_origen,
    )
    return formato


# ============================================================================
# Impresoras
# ============================================================================


def listar_impresoras(db: Session) -> list[EtiquetaImpresora]:
    return list(
        db.execute(
            select(EtiquetaImpresora).where(EtiquetaImpresora.activa.is_(True)).order_by(EtiquetaImpresora.nombre)
        ).scalars()
    )


def obtener_impresora(db: Session, impresora_id: int) -> EtiquetaImpresora:
    impresora = db.get(EtiquetaImpresora, impresora_id)
    if impresora is None or not impresora.activa:
        raise NoEncontrado(f"No existe la impresora {impresora_id}")
    return impresora


def _por_nombre_browser_print(db: Session, nombre: str) -> EtiquetaImpresora | None:
    return db.execute(
        select(EtiquetaImpresora).where(EtiquetaImpresora.browser_print == nombre)
    ).scalar_one_or_none()


def crear_impresora(
    db: Session, autor_id: int, nombre: str, browser_print: str, ip_origen: str | None = None
) -> EtiquetaImpresora:
    """
    Ficha nueva, con los ajustes de siempre (los del sistema viejo: oscuridad
    14, velocidad 2). Si esa impresora se había quitado, vuelve con su ficha.
    """
    nombre, browser_print = nombre.strip(), browser_print.strip()
    existente = _por_nombre_browser_print(db, browser_print)
    if existente is not None and existente.activa:
        raise ReglaDeNegocio(f'Esa impresora ya está cargada como "{existente.nombre}".')

    if existente is not None:
        existente.activa = True
        existente.nombre = nombre
        existente.updated_at = ahora_db()
        impresora = existente
    else:
        impresora = EtiquetaImpresora(nombre=nombre, browser_print=browser_print)
        db.add(impresora)
    db.flush()
    db.refresh(impresora)
    registrar_auditoria(
        db, usuario_id=autor_id, accion="etiqueta_impresora.crear", entidad="etiqueta_impresoras",
        entidad_id=impresora.id, estado_nuevo=impresora, ip_origen=ip_origen,
    )
    return impresora


def editar_impresora(
    db: Session, autor_id: int, impresora_id: int, cambios: dict, ip_origen: str | None = None
) -> EtiquetaImpresora:
    """Edita la ficha. Solo cuenta lo que vino y es distinto: guardar sin cambios no deja rastro."""
    impresora = obtener_impresora(db, impresora_id)
    nuevos = {
        campo: (valor.strip() if isinstance(valor, str) else valor)
        for campo, valor in cambios.items()
        if valor is not None
    }
    nuevos = {campo: valor for campo, valor in nuevos.items() if getattr(impresora, campo) != valor}
    if not nuevos:
        return impresora

    if "browser_print" in nuevos:
        otra = _por_nombre_browser_print(db, nuevos["browser_print"])
        if otra is not None and otra.id != impresora.id:
            raise ReglaDeNegocio(f'Ese nombre de Browser Print ya es de "{otra.nombre}".')

    anterior = snapshot(impresora, list(nuevos))
    for campo, valor in nuevos.items():
        setattr(impresora, campo, valor)
    impresora.updated_at = ahora_db()
    db.flush()
    registrar_auditoria(
        db, usuario_id=autor_id, accion="etiqueta_impresora.editar", entidad="etiqueta_impresoras",
        entidad_id=impresora.id, estado_anterior=anterior, estado_nuevo=snapshot(impresora, list(nuevos)),
        ip_origen=ip_origen,
    )
    return impresora


def quitar_impresora(db: Session, autor_id: int, impresora_id: int, ip_origen: str | None = None) -> None:
    """
    Quita la ficha (la desactiva). No se puede si imprime algún rollo: ese
    rollo quedaría sin impresora sin que nadie lo decida.
    """
    impresora = obtener_impresora(db, impresora_id)
    rollos = [f.nombre for f in listar_formatos(db) if f.impresora_id == impresora.id]
    if rollos:
        raise ReglaDeNegocio(f"Primero asigná otra impresora a: {', '.join(rollos)}.")

    impresora.activa = False
    impresora.updated_at = ahora_db()
    db.flush()
    registrar_auditoria(
        db, usuario_id=autor_id, accion="etiqueta_impresora.quitar", entidad="etiqueta_impresoras",
        entidad_id=impresora.id, estado_anterior={"activa": True}, estado_nuevo={"activa": False},
        ip_origen=ip_origen,
    )


def _formato_de_impresora(db: Session, impresora: EtiquetaImpresora) -> EtiquetaFormato:
    for formato in listar_formatos(db):
        if formato.impresora_id == impresora.id:
            return formato
    raise ReglaDeNegocio("Esta impresora no tiene ningún tipo de etiqueta asignado.")


def _motor(formato: EtiquetaFormato, parametros: dict, impresora: EtiquetaImpresora | None) -> Motor:
    try:
        return Motor(formato_para_motor(formato), parametros, impresora.dpi if impresora else 203)
    except DpiNoSoportado as exc:
        raise ReglaDeNegocio(str(exc)) from exc


def zpl_prueba(db: Session, impresora_id: int) -> tuple[str, str]:
    """
    Etiqueta de prueba de una impresora: una fila de su rollo, en la opción
    2 (código + texto), con los ajustes de su ficha. Devuelve (ZPL, SVG).
    """
    impresora = obtener_impresora(db, impresora_id)
    formato = _formato_de_impresora(db, impresora)
    diseno = _diseno_para_prueba(db)
    motor = _motor(formato, diseno.parametros, impresora)
    fila = [Etiqueta("PRUEBA01", "ETIQUETA DE PRUEBA")] * formato.columnas
    zpl, _ = motor.zpl_fila(fila, ficha_para_motor(impresora))
    return zpl, svg_fila(motor, fila)


def zpl_calibracion(db: Session, impresora_id: int) -> str:
    """La orden para que la Zebra mida el rollo (cuando se cambia el rollo o la cinta)."""
    obtener_impresora(db, impresora_id)
    return zpl_calibrar()


# ============================================================================
# Diseños
# ============================================================================


def listar_disenos(db: Session, archivados: bool = False) -> list[EtiquetaDiseno]:
    return list(
        db.execute(
            select(EtiquetaDiseno)
            .where(EtiquetaDiseno.archivado.is_(archivados))
            .order_by(EtiquetaDiseno.nombre)
        ).scalars()
    )


def obtener_diseno(db: Session, diseno_id: int) -> EtiquetaDiseno:
    diseno = db.get(EtiquetaDiseno, diseno_id)
    if diseno is None:
        raise NoEncontrado(f"No existe el diseño {diseno_id}")
    return diseno


def _diseno_para_prueba(db: Session) -> EtiquetaDiseno:
    disenos = listar_disenos(db)
    if not disenos:
        raise ReglaDeNegocio("No hay ningún diseño de etiqueta sin archivar.")
    return disenos[0]


def _guardar_version(db: Session, diseno: EtiquetaDiseno, autor_id: int | None) -> None:
    db.add(EtiquetaDisenoVersion(
        diseno_id=diseno.id, version=diseno.version, nombre=diseno.nombre,
        parametros=diseno.parametros, usuario_id=autor_id, creado_en=ahora_db(),
    ))
    db.flush()


def crear_diseno(
    db: Session, autor_id: int, nombre: str, parametros: ParametrosDiseno,
    ip_origen: str | None = None, accion: str = "etiqueta_diseno.crear",
) -> EtiquetaDiseno:
    ahora = ahora_db()
    diseno = EtiquetaDiseno(
        nombre=nombre.strip(), parametros=parametros.model_dump(), version=1,
        actualizado_por_id=autor_id, created_at=ahora, updated_at=ahora,
    )
    db.add(diseno)
    db.flush()
    _guardar_version(db, diseno, autor_id)
    registrar_auditoria(
        db, usuario_id=autor_id, accion=accion, entidad="etiqueta_disenos", entidad_id=diseno.id,
        estado_nuevo={"nombre": diseno.nombre, "parametros": diseno.parametros}, ip_origen=ip_origen,
    )
    return diseno


def editar_diseno(
    db: Session, autor_id: int, diseno_id: int, nombre: str | None = None,
    parametros: ParametrosDiseno | None = None, ip_origen: str | None = None,
    accion: str = "etiqueta_diseno.editar",
) -> EtiquetaDiseno:
    """
    Cada cambio es una versión nueva: la anterior queda guardada con quién y
    cuándo, y se puede volver a ella.
    """
    diseno = obtener_diseno(db, diseno_id)
    nuevo_nombre = nombre.strip() if nombre is not None else diseno.nombre
    nuevos_parametros = parametros.model_dump() if parametros is not None else diseno.parametros
    if nuevo_nombre == diseno.nombre and nuevos_parametros == diseno.parametros:
        return diseno

    anterior = {"nombre": diseno.nombre, "version": diseno.version, "parametros": diseno.parametros}
    diseno.nombre = nuevo_nombre
    diseno.parametros = nuevos_parametros
    diseno.version += 1
    diseno.actualizado_por_id = autor_id
    diseno.updated_at = ahora_db()
    db.flush()
    _guardar_version(db, diseno, autor_id)
    registrar_auditoria(
        db, usuario_id=autor_id, accion=accion, entidad="etiqueta_disenos", entidad_id=diseno.id,
        estado_anterior=anterior,
        estado_nuevo={"nombre": diseno.nombre, "version": diseno.version, "parametros": diseno.parametros},
        ip_origen=ip_origen,
    )
    return diseno


def duplicar_diseno(db: Session, autor_id: int, diseno_id: int, ip_origen: str | None = None) -> EtiquetaDiseno:
    original = obtener_diseno(db, diseno_id)
    nombre = f"{original.nombre} (copia)"[:80]
    return crear_diseno(db, autor_id, nombre, ParametrosDiseno(**original.parametros), ip_origen)


def cambiar_archivado(
    db: Session, autor_id: int, diseno_id: int, archivado: bool, ip_origen: str | None = None
) -> EtiquetaDiseno:
    """Borrar = archivar: un diseño archivado no se ofrece al imprimir, pero no se pierde."""
    diseno = obtener_diseno(db, diseno_id)
    if diseno.archivado == archivado:
        return diseno
    if archivado and len(listar_disenos(db)) == 1:
        raise ReglaDeNegocio("Es el único diseño activo: sin él no se podría imprimir.")

    diseno.archivado = archivado
    diseno.updated_at = ahora_db()
    db.flush()
    registrar_auditoria(
        db, usuario_id=autor_id,
        accion="etiqueta_diseno.archivar" if archivado else "etiqueta_diseno.desarchivar",
        entidad="etiqueta_disenos", entidad_id=diseno.id,
        estado_anterior={"archivado": not archivado}, estado_nuevo={"archivado": archivado},
        ip_origen=ip_origen,
    )
    return diseno


def versiones_diseno(db: Session, diseno_id: int) -> list[EtiquetaDisenoVersion]:
    obtener_diseno(db, diseno_id)
    return list(
        db.execute(
            select(EtiquetaDisenoVersion)
            .options(joinedload(EtiquetaDisenoVersion.usuario))
            .where(EtiquetaDisenoVersion.diseno_id == diseno_id)
            .order_by(EtiquetaDisenoVersion.version.desc())
        ).scalars()
    )


def restaurar_version(
    db: Session, autor_id: int, diseno_id: int, version: int, ip_origen: str | None = None
) -> EtiquetaDiseno:
    """Volver a una versión: es una edición nueva con esos parámetros (no se borra historia)."""
    guardada = db.execute(
        select(EtiquetaDisenoVersion).where(
            EtiquetaDisenoVersion.diseno_id == diseno_id, EtiquetaDisenoVersion.version == version
        )
    ).scalar_one_or_none()
    if guardada is None:
        raise NoEncontrado(f"El diseño {diseno_id} no tiene la versión {version}")
    return editar_diseno(
        db, autor_id, diseno_id, nombre=guardada.nombre,
        parametros=ParametrosDiseno(**guardada.parametros), ip_origen=ip_origen,
        accion="etiqueta_diseno.restaurar",
    )


def exportar_diseno(db: Session, diseno_id: int) -> dict:
    """Lo que se baja como archivo: nombre y parámetros, para editarlo afuera y volver a subirlo."""
    diseno = obtener_diseno(db, diseno_id)
    return {"nombre": diseno.nombre, "parametros": diseno.parametros}


# ============================================================================
# Vista previa de un diseño (sin guardar)
# ============================================================================


def _ejemplos(formato: EtiquetaFormato) -> list[list[Etiqueta]]:
    """Las tres opciones, con textos corto, mediano y largo, como en el documento aprobado."""
    c = CODIGO_DE_EJEMPLO
    if formato.doblez_mm is not None:
        return [
            [Etiqueta(c)],
            [Etiqueta(c, "ARO PERLA")],
            [Etiqueta(c, "PULSERA ACERO DORADO")],
            [Etiqueta(None, "LIQUIDACION 50%")],
        ]
    ejemplos = [
        Etiqueta(c), Etiqueta(c, "PROMO"), Etiqueta(c, "ARO PERLA"),
        Etiqueta(c, "PULSERA ACERO DORADO"), Etiqueta(None, "SALE"),
        Etiqueta(None, "NO TOCAR - RESERVADO PARA CLIENTA"),
    ]
    return [ejemplos[i : i + formato.columnas] for i in range(0, len(ejemplos), formato.columnas)]


def vista_previa_diseno(db: Session, parametros: ParametrosDiseno) -> list[dict]:
    """Cómo salen las tres opciones en cada rollo con estos parámetros, con su ZPL y avisos."""
    rollos = []
    for formato in listar_formatos(db):
        motor = _motor(formato, parametros.model_dump(), formato.impresora)
        ficha = ficha_para_motor(formato.impresora)
        filas = _ejemplos(formato)
        avisos, zpls = [], []
        for fila in filas:
            zpl, av = motor.zpl_fila(fila, ficha)
            zpls.append(zpl)
            avisos += av
        rollos.append({
            "formato_id": formato.id,
            "formato_nombre": formato.nombre,
            "vista_previa": [svg_fila(motor, fila) for fila in filas],
            "zpl": zpls,
            "avisos": avisos_sin_repetir(avisos),
        })
    return rollos


# ============================================================================
# Origen de las etiquetas: una compra o un código
# ============================================================================


def _renglon(variante: Variante, copias: int) -> dict:
    return {
        "variante_id": variante.id,
        "codigo": variante.codigo_con_verificador,
        "descripcion": variante.producto.descripcion,
        "variante": None if variante.es_base else variante.descripcion_sufijo or variante.sufijo,
        "copias": copias,
    }


def renglones_de_compra(db: Session, compra_id: int) -> list[dict]:
    """Los productos de una compra, con la cantidad comprada como copias (una etiqueta por unidad)."""
    compra = db.get(Compra, compra_id)
    if compra is None or compra.estado == EstadoCompra.ELIMINADA:
        raise NoEncontrado(f"No existe la compra {compra_id}")
    items = db.execute(
        select(CompraItem)
        .options(joinedload(CompraItem.variante).joinedload(Variante.producto))
        .where(CompraItem.compra_id == compra_id)
        .order_by(CompraItem.id)
    ).scalars()
    return [_renglon(i.variante, i.cantidad) for i in items]


def renglon_de_codigo(db: Session, codigo: str) -> dict:
    """Un producto por su código de etiqueta (con o sin dígito verificador)."""
    from app.services.ventas import buscar_variante

    return _renglon(buscar_variante(db, codigo), 1)


def renglon_de_variante(db: Session, variante_id: int, copias: int = 1) -> dict:
    variante = db.get(Variante, variante_id)
    if variante is None:
        raise NoEncontrado(f"No existe la variante {variante_id}")
    return _renglon(variante, copias)


# ============================================================================
# Preparar lo que se imprime
# ============================================================================


def _preparar_grupo(
    db: Session, formato: EtiquetaFormato, parametros: dict, etiquetas: list[Etiqueta]
) -> dict:
    """Las etiquetas de UN rollo: sus órdenes ZPL, avisos y vista previa."""
    # Sin impresora (o con una que el motor no maneja) igual se cuentan las
    # pedidas: la pantalla muestra cuántas son y el aviso explica por qué no
    # se pueden imprimir.
    base = {
        "formato_id": formato.id, "formato_nombre": formato.nombre, "impresora": None,
        "trabajos": [], "filas": 0, "total_etiquetas": sum(max(0, e.copias) for e in etiquetas),
        "vista_previa": [], "puede_imprimir": False,
    }
    impresora = formato.impresora if formato.impresora is not None and formato.impresora.activa else None
    if impresora is None:
        return base | {"avisos": [{
            "nivel": "error",
            "texto": f'"{formato.nombre}" no tiene impresora asignada (se asigna en Ajustes → Impresoras).',
        }]}
    try:
        motor = Motor(formato_para_motor(formato), parametros, impresora.dpi)
    except DpiNoSoportado as exc:
        return base | {"avisos": [{"nivel": "error", "texto": str(exc)}]}

    trabajos, avisos, filas = motor.trabajos(etiquetas, ficha_para_motor(impresora))
    salida = avisos_sin_repetir(avisos) if filas else [{"nivel": "error", "texto": "No hay etiquetas para imprimir."}]

    columnas, ultima = formato.columnas, (len(filas[-1]) if filas else 0)
    if columnas > 1 and 0 < ultima < columnas:
        # La fila se gasta entera aunque no se use.
        vacias = columnas - ultima
        quedan = "queda 1 etiqueta" if vacias == 1 else f"quedan {vacias} etiquetas"
        salida.append({"nivel": "ojo", "texto": f"La última fila lleva {ultima} de {columnas}: {quedan} en blanco."})

    # Vista previa: una etiqueta de cada renglón (sin repetir copias).
    distintas = [Etiqueta(e.codigo, e.texto, 1) for e in etiquetas if e.copias > 0]
    previas = [svg_fila(motor, f) for f in motor.filas(distintas)[:FILAS_VISTA_PREVIA]]
    return {
        "formato_id": formato.id,
        "formato_nombre": formato.nombre,
        "impresora": {"id": impresora.id, "nombre": impresora.nombre, "browser_print": impresora.browser_print},
        "trabajos": trabajos,
        "filas": len(filas),
        "total_etiquetas": sum(len(f) for f in filas),
        "avisos": salida,
        "vista_previa": previas,
        "puede_imprimir": bool(filas) and not any(a["nivel"] == "error" for a in salida),
    }


def preparar(db: Session, diseno_id: int, pedidas: list) -> dict:
    """
    Arma todas las etiquetas pedidas, REPARTIDAS por rollo: cada grupo va a
    la impresora asignada a ese rollo (la pantalla no elige impresora).

    `pedidas`: objetos con `variante_id` (None = solo texto), `texto`,
    `copias` y `formato_id`.
    """
    diseno = obtener_diseno(db, diseno_id)
    if diseno.archivado:
        raise ReglaDeNegocio(f'El diseño "{diseno.nombre}" está archivado.')

    ids = {p.variante_id for p in pedidas if p.variante_id is not None}
    variantes = {
        v.id: v for v in db.execute(select(Variante).where(Variante.id.in_(ids))).scalars()
    } if ids else {}
    faltan = ids - set(variantes)
    if faltan:
        raise NoEncontrado(f"No existe la variante {min(faltan)}")

    grupos: dict[int, list[Etiqueta]] = {}
    for p in pedidas:
        codigo = variantes[p.variante_id].codigo_con_verificador if p.variante_id is not None else None
        grupos.setdefault(p.formato_id, []).append(Etiqueta(codigo, p.texto, p.copias))

    salida = [
        _preparar_grupo(db, obtener_formato(db, formato_id), diseno.parametros, etiquetas)
        for formato_id, etiquetas in grupos.items()
    ]
    avisos = [] if salida else [{"nivel": "error", "texto": "No hay etiquetas para imprimir."}]
    return {
        "grupos": salida,
        "avisos": avisos,
        "total_etiquetas": sum(g["total_etiquetas"] for g in salida),
        "puede_imprimir": bool(salida) and all(g["puede_imprimir"] for g in salida),
    }

