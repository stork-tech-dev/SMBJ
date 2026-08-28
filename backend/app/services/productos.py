"""
Reglas de negocio de productos y variantes.

Lo central de este módulo es el precio de venta: es un campo persistido
que se deriva de otros dos (`precio_usd` del producto y `dolar_actual` del
proveedor). Que esté desnormalizado obliga a que TODO camino que toque
cualquiera de esos dos pase por `calcular_precio_venta()`, o la base
empieza a mentir.

Los dos caminos son:
  1. Cambia `precio_usd` → `crear_producto` / `editar_producto`.
  2. Cambia el dólar del proveedor → `recalcular_precios_de_proveedor()`,
     que llama `_aplicar_cambio_dolar()` en el service de proveedores.
"""

from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.codigos import (
    CodigoInvalido,
    armar_codigo_completo,
    codificar_sku,
    codigo_es_valido,
    digito_verificador,
)
from app.core.permisos import ROL_CUENTA_MAESTRA
from app.core.utils import (
    ahora_db,
    capitalizar_inicial,
    normalizar_texto,
    redondear_hacia_arriba,
    sin_tildes,
    sin_tildes_sql,
)
from app.models.categoria import Categoria
from app.models.configuracion import ConfiguracionSistema
from app.models.producto import Producto, Temporada, Variante
from app.models.proveedor import EstadoProveedor, Proveedor
from app.models.punto_de_venta import PuntoDeVenta, TipoPuntoVenta
from app.models.stock import Stock, TipoMovimiento
from app.models.usuario import Usuario
from app.services.roles import NoEncontrado, ReglaDeNegocio


class SinPermiso(Exception):
    """El autor no puede tocar este campo del producto (403)."""


def _ingresar_stock_inicial(
    db: Session, autor: Usuario, variante: Variante,
    cantidad: int, ip_origen: str | None,
) -> None:
    """
    Registra un ingreso de proveedor al CD con la cantidad indicada.

    Se llama después de crear un producto o variante si el usuario cargó
    stock inicial. Usa el mismo `aplicar_movimiento` que el resto del
    sistema: la mercadería queda en el CD con su movimiento y auditoría.
    """
    if cantidad <= 0:
        return

    from app.services.stock import aplicar_movimiento

    cd = db.execute(
        select(PuntoDeVenta).where(PuntoDeVenta.tipo == TipoPuntoVenta.CD)
    ).scalars().first()
    if cd is None:
        raise ReglaDeNegocio(
            "No hay un Centro de Distribución configurado para cargar stock"
        )

    aplicar_movimiento(
        db, autor,
        tipo=TipoMovimiento.INGRESO_PROVEEDOR,
        variante_id=variante.id,
        cantidad=cantidad,
        punto_venta_destino_id=cd.id,
        ip_origen=ip_origen,
    )


def _validar_stock_infinito(autor: Usuario, pedido: bool | None, actual: bool) -> None:
    """
    `stock_infinito` lo decide solo la Cuenta Maestra.

    Es el interruptor que hace que un producto NO descuente stock al vender:
    prendido por error, el sistema deja de saber cuánto hay de ese artículo y
    no queda ninguna señal de que pasó. Por eso no alcanza con esconder el
    checkbox del formulario —la API es el contrato (Principio 1) y se puede
    llamar sin la pantalla— y por eso la regla vive acá, en el service, que
    es por donde pasan todos los clientes.

    Solo molesta si el valor CAMBIA: el formulario manda el producto entero
    en cada guardado, así que rechazar la mera presencia del campo haría que
    ninguna edición de un vendedor pudiera guardarse.
    """
    if pedido is None or pedido == actual:
        return
    if autor.rol is not None and autor.rol.nombre == ROL_CUENTA_MAESTRA:
        return
    raise SinPermiso("El stock infinito lo define la Cuenta Maestra")


def obtener_producto(db: Session, producto_id: int) -> Producto:
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise NoEncontrado("Producto inexistente")
    return producto


def obtener_variante(db: Session, variante_id: int) -> Variante:
    variante = db.get(Variante, variante_id)
    if variante is None:
        raise NoEncontrado("Variante inexistente")
    return variante


# ============================================================================
# PRECIO
# ============================================================================


def calcular_precio_venta(
    db: Session, precio_usd: Decimal, dolar: Decimal
) -> Decimal:
    """
    Precio en pesos: dólares × cotización, redondeado HACIA ARRIBA al
    múltiplo configurado.

    Hacia arriba y no al más cercano: el redondeo no puede hacer que el
    precio de venta quede por debajo del que corresponde.
    """
    config = db.execute(select(ConfiguracionSistema)).scalars().first()
    multiplo = config.redondeo if config else Decimal("1")
    return redondear_hacia_arriba(Decimal(precio_usd) * Decimal(dolar), multiplo)


def recalcular_precios_de_proveedor(db: Session, proveedor_id: int) -> int:
    """
    Recalcula el precio de venta de todo lo que cuelga de un proveedor.

    La llama `_aplicar_cambio_dolar()` en el service de proveedores, que es
    el único punto por donde pasa un cambio de cotización —individual,
    masivo o por Excel—. Engancharse ahí y no en los tres endpoints es lo
    que evita que uno quede desincronizado.

    Son DOS cosas, no una: los productos y las variantes que tienen precio
    propio. Las variantes con `precio_usd` propio no derivan del producto,
    así que si esta función solo tocara productos, su precio en pesos
    quedaría congelado al dólar viejo y se desfasaría en silencio — sin
    error, sin aviso, y solo visible comparando contra el dólar del día.

    Van las dos acá y no en dos enganches separados a propósito: dos puntos
    de cascada es exactamente cómo se desincronizan.

    Devuelve cuántas filas se actualizaron, sumando productos y variantes.
    """
    proveedor = db.get(Proveedor, proveedor_id)
    if proveedor is None:
        return 0

    productos = list(
        db.execute(select(Producto).where(Producto.proveedor_id == proveedor_id))
        .scalars()
        .all()
    )

    for producto in productos:
        producto.precio_venta = calcular_precio_venta(
            db, producto.precio_usd, proveedor.dolar_actual
        )
        producto.updated_at = ahora_db()

    variantes = list(
        db.execute(
            select(Variante)
            .join(Producto, Variante.producto_id == Producto.id)
            .where(
                Producto.proveedor_id == proveedor_id,
                Variante.precio_usd.is_not(None),
            )
        )
        .scalars()
        .all()
    )

    for variante in variantes:
        variante.precio_venta = calcular_precio_venta(
            db, variante.precio_usd, proveedor.dolar_actual
        )
        variante.updated_at = ahora_db()

    if productos or variantes:
        db.flush()
    return len(productos) + len(variantes)


# ============================================================================
# VALIDACIONES
# ============================================================================


def _validar_categoria(db: Session, categoria_id: int) -> Categoria:
    categoria = db.get(Categoria, categoria_id)
    if categoria is None:
        raise ReglaDeNegocio("La categoría no existe")
    return categoria


def _validar_proveedor(db: Session, proveedor_id: int) -> Proveedor:
    proveedor = db.get(Proveedor, proveedor_id)
    if proveedor is None:
        raise ReglaDeNegocio("El proveedor no existe")
    if proveedor.estado != EstadoProveedor.ACTIVO:
        raise ReglaDeNegocio("No se puede cargar un producto de un proveedor inactivo")
    return proveedor


def _validar_descripcion(descripcion: str) -> str:
    """
    La descripción es obligatoria y no puede quedar vacía.

    `normalizar_texto` colapsa espacios y devuelve None si no queda nada,
    así que sin este control un valor de solo espacios llegaría como NULL a
    una columna NOT NULL: reventaría con un error de base en vez de decir
    qué está mal.

    La inicial se pone en mayúscula acá y no en la pantalla porque este es el
    único embudo por el que se escribe la descripción —`crear_producto` y
    `editar_producto`—: así queda igual en el listado, en la ficha, en la
    edición y en cualquier pantalla que se agregue después, sin que ninguna
    tenga que acordarse de formatearla.
    """
    limpia = normalizar_texto(descripcion)
    if not limpia:
        raise ReglaDeNegocio("La descripción del producto es obligatoria")
    return capitalizar_inicial(limpia)


def _validar_descripcion_unica(
    db: Session,
    descripcion: str,
    categoria_id: int,
    proveedor_id: int,
    excluir_id: int | None = None,
) -> None:
    """
    Dos productos del mismo proveedor y la misma categoría no pueden
    llamarse igual.

    Mirando el catálogo serían la misma fila cargada dos veces: no queda
    ningún dato en pantalla para distinguirlos. Lo que corresponde cuando
    el artículo viene en colores o talles es una variante del que ya
    existe, que además comparte precio y descripción.

    Compara sin tildes y sin mayúsculas —"Cadena plata" y "cadena PLATA"
    tampoco se distinguen— con la MISMA expresión del índice único
    `uq_productos_descripcion_por_categoria_y_proveedor` (migración 0020).
    La base es la que lo garantiza; esto existe para poder decir con cuál
    choca en vez de devolver un error de integridad.

    La categoría se compara exacta y no por rama: es lo que hace el índice,
    y dos productos iguales colgados de hojas distintas son un problema de
    clasificación, no un duplicado.

    Los inactivos cuentan: no se borran, se pueden volver a activar, y ahí
    quedarían las dos filas idénticas.
    """
    consulta = select(Producto).where(
        func.lower(sin_tildes_sql(Producto.descripcion)) == sin_tildes(descripcion).lower(),
        Producto.categoria_id == categoria_id,
        Producto.proveedor_id == proveedor_id,
    )
    if excluir_id is not None:
        consulta = consulta.where(Producto.id != excluir_id)

    existente = db.execute(consulta.limit(1)).scalars().first()
    if existente is None:
        return

    baja = "" if existente.activo else ", que está inactivo y se puede volver a activar"
    raise ReglaDeNegocio(
        f"Ya existe un producto con esa descripción en este proveedor y categoría: "
        f"{existente.sku}{baja}. Si es el mismo artículo en otro color o talle, "
        f"agregale una variante en lugar de crear otro producto."
    )


def _validar_nombre_variante(descripcion_sufijo: str) -> str:
    """
    El nombre de la variante es obligatorio y no puede quedar vacío.

    Mismo criterio que `_validar_descripcion` del producto: sin esto, un
    valor de solo espacios llegaría como NULL y lo rechazaría el CHECK de la
    tabla con un error de base en vez de decir qué falta.
    """
    limpio = normalizar_texto(descripcion_sufijo)
    if not limpio:
        raise ReglaDeNegocio("El nombre de la variante es obligatorio")
    return limpio


def _validar_descuento(db: Session, descuento: Decimal | None) -> Decimal:
    """
    El descuento del producto no puede pasar el tope global.

    El tope vive en `configuracion_sistema`, así que la validación tiene
    que consultarlo: no alcanza con el CHECK de 0-100 de la tabla.
    """
    if descuento is None:
        return Decimal("0")

    descuento = Decimal(descuento)
    if descuento < 0:
        raise ReglaDeNegocio("El descuento no puede ser negativo")

    config = db.execute(select(ConfiguracionSistema)).scalars().first()
    tope = config.descuento_maximo if config else Decimal("100")
    if descuento > tope:
        raise ReglaDeNegocio(f"El descuento no puede superar el máximo configurado ({tope}%)")

    return descuento


# ============================================================================
# CÓDIGOS Y VARIANTES
# ============================================================================


def _siguiente_sku(db: Session) -> str:
    """
    Próximo SKU, tomado de la secuencia de PostgreSQL.

    `nextval` es atómico: dos transacciones concurrentes reciben valores
    distintos sin bloquearse. Un `MAX(sku) + 1` podría entregar el mismo
    número a las dos y hacer fallar una por el índice único.
    """
    correlativo = db.execute(select(func.nextval("productos_sku_seq"))).scalar_one()
    try:
        return codificar_sku(int(correlativo))
    except CodigoInvalido as exc:
        raise ReglaDeNegocio(str(exc)) from exc


def _letra_empresa(db: Session) -> str:
    from app.services.configuracion import letra_empresa

    return letra_empresa(db)


def _crear_variante(
    db: Session,
    producto: Producto,
    sufijo: str | None,
    es_base: bool,
    descripcion_sufijo: str | None = None,
) -> Variante:
    """
    Crea una variante y le congela el código.

    `codigo_completo` y `verificador` se calculan una sola vez, acá: la
    etiqueta se imprime y se pega a la mercadería, así que recalcularlos
    después invalidaría lo que ya está en el depósito.
    """
    try:
        codigo = armar_codigo_completo(_letra_empresa(db), producto.sku, sufijo)
    except CodigoInvalido as exc:
        raise ReglaDeNegocio(str(exc)) from exc

    existe = db.execute(
        select(Variante.id).where(Variante.codigo_completo == codigo)
    ).scalar_one_or_none()
    if existe:
        raise ReglaDeNegocio(f"Ya existe una variante con el código '{codigo}'")

    variante = Variante(
        producto_id=producto.id,
        sufijo=sufijo,
        # Va acá y no asignado después: el CHECK que lo ata a `es_base` se
        # evalúa en el flush de esta función, así que setearlo más tarde
        # llegaría tarde.
        descripcion_sufijo=descripcion_sufijo,
        es_base=es_base,
        codigo_completo=codigo,
        verificador=digito_verificador(codigo),
        created_at=ahora_db(),
        updated_at=ahora_db(),
    )
    db.add(variante)
    db.flush()
    return variante


def agregar_variante(
    db: Session,
    autor: Usuario,
    producto_id: int,
    sufijo: str,
    descripcion_sufijo: str,
    sku_proveedor: str | None = None,
    ubicacion_deposito: str | None = None,
    stock_inicial: int | None = None,
    ip_origen: str | None = None,
) -> Variante:
    """
    Agrega una variante real a un producto.

    Si el producto todavía no manejaba variantes, la BASE se elimina: no
    pueden convivir con las reales, porque el stock quedaría partido entre
    una variante genérica y las concretas.
    """
    producto = obtener_producto(db, producto_id)

    # Se consulta la BASE en vez de leerla de `producto.variantes`: esa
    # colección queda cacheada en la sesión y, tras haber borrado la base
    # en una llamada anterior, seguiría devolviendo el objeto eliminado.
    base = (
        db.execute(
            select(Variante).where(
                Variante.producto_id == producto.id, Variante.es_base.is_(True)
            )
        )
        .scalars()
        .first()
    )
    if base is not None:
        # El stock de la BASE ya no es una columna suya: está repartido en
        # `stock`, una fila por ubicación. Se suman todas porque el problema
        # es el mismo en cualquiera —dividir en variantes dejaría unidades
        # colgadas de un código que va a dejar de existir— y con una sola
        # que tenga mercadería alcanza para frenar.
        cargado = db.execute(
            select(func.coalesce(func.sum(Stock.cantidad), 0)).where(
                Stock.variante_id == base.id
            )
        ).scalar_one()
        if cargado:
            raise ReglaDeNegocio(
                "El producto tiene stock cargado sin variantes: hay que "
                "descargarlo antes de dividirlo en variantes"
            )
        db.delete(base)
        db.flush()

    variante = _crear_variante(
        db, producto, sufijo=sufijo, es_base=False,
        descripcion_sufijo=_validar_nombre_variante(descripcion_sufijo),
    )

    variante.ubicacion_deposito = normalizar_texto(ubicacion_deposito)
    # Vacío queda en NULL, que es "usa el del producto" y no "sin código".
    variante.sku_proveedor = normalizar_texto(sku_proveedor)

    producto.tiene_variantes = True
    producto.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="variante.crear",
        entidad="producto_variantes",
        entidad_id=variante.id,
        estado_nuevo=variante,
        ip_origen=ip_origen,
    )

    if stock_inicial:
        _ingresar_stock_inicial(db, autor, variante, stock_inicial, ip_origen)

    return variante


def editar_variante(
    db: Session,
    autor: Usuario,
    variante_id: int,
    descripcion_sufijo: str | None = None,
    ubicacion_deposito: str | None = None,
    precio_usd: Decimal | None = None,
    editar_precio: bool = False,
    sku_proveedor: str | None = None,
    editar_sku_proveedor: bool = False,
    ip_origen: str | None = None,
) -> Variante:
    """
    Edita lo que se puede cambiar de una variante.

    El SUFIJO NO ESTÁ, y no es un olvido: entra en `codigo_completo`, que se
    congela al crear la variante porque la etiqueta ya se imprimió y está
    pegada a la mercadería. Cambiarlo dejaría sin producto a lo que hay en el
    depósito. Lo mismo vale para el dígito verificador, que se deriva de él.
    """
    variante = obtener_variante(db, variante_id)
    antes = snapshot(variante)

    if variante.es_base and descripcion_sufijo is not None:
        raise ReglaDeNegocio("La variante BASE no lleva nombre: no es variante de nada")

    if descripcion_sufijo is not None:
        variante.descripcion_sufijo = _validar_nombre_variante(descripcion_sufijo)
    if ubicacion_deposito is not None:
        variante.ubicacion_deposito = normalizar_texto(ubicacion_deposito)

    # `editar_precio` distingue "no lo mandes" de "ponelo en NULL": None es
    # ambiguo y NULL acá significa algo concreto —volver al precio del
    # producto—, no "sin cambios".
    if editar_precio:
        if precio_usd is None:
            variante.precio_usd = None
            variante.precio_venta = None
        else:
            if Decimal(precio_usd) <= 0:
                raise ReglaDeNegocio("El precio en dólares debe ser mayor a cero")

            # Se resuelve TODO antes de asignar. Leer el proveedor y calcular
            # el precio disparan consultas, y cada consulta hace autoflush:
            # con `precio_usd` ya puesto y `precio_venta` todavía en NULL, el
            # CHECK `ck_producto_variantes_precio_completo` rechaza la fila a mitad de
            # camino. Las dos asignaciones tienen que quedar pegadas.
            nuevo_usd = Decimal(precio_usd)
            dolar = variante.producto.proveedor.dolar_actual
            nuevo_venta = calcular_precio_venta(db, nuevo_usd, dolar)

            variante.precio_usd = nuevo_usd
            variante.precio_venta = nuevo_venta

    # Misma mecánica que el precio, y por el mismo motivo: NULL acá no es
    # "sin cambios" sino algo concreto —volver al código del producto—, así
    # que hace falta la bandera para distinguirlo de "no lo mandes".
    # `normalizar_texto` deja en NULL el string vacío, que es lo que manda la
    # pantalla al borrar el campo.
    if editar_sku_proveedor:
        variante.sku_proveedor = normalizar_texto(sku_proveedor)

    variante.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="variante.editar",
        entidad="producto_variantes",
        entidad_id=variante.id,
        estado_anterior=antes,
        estado_nuevo=variante,
        ip_origen=ip_origen,
    )
    return variante


# ============================================================================
# LISTADO Y ABM
# ============================================================================


def listar_productos(
    db: Session,
    sku: str | None = None,
    descripcion: str | None = None,
    categoria_id: int | None = None,
    proveedor_id: int | None = None,
    temporada: str | None = None,
    activo: bool | None = None,
    precio_desde: Decimal | None = None,
    precio_hasta: Decimal | None = None,
    pagina: int = 1,
    tamano: int = 50,
) -> tuple[list[Producto], int]:
    """Filtros del Principio 5, todos resueltos en el backend."""
    consulta = select(Producto)

    if sku:
        consulta = consulta.where(Producto.sku.ilike(f"%{sku}%"))
    if descripcion:
        consulta = consulta.where(Producto.descripcion.ilike(f"%{descripcion}%"))
    if categoria_id is not None:
        # Incluye la descendencia: filtrar por "Zapatillas" trae también lo
        # de "Deportivas" y "Urbanas". Los productos suelen colgar de las
        # hojas, así que un filtro exacto por un nodo intermedio devolvería
        # cero resultados casi siempre.
        from app.services.categorias import rama_de_ids

        consulta = consulta.where(Producto.categoria_id.in_(rama_de_ids(db, categoria_id)))
    if proveedor_id is not None:
        consulta = consulta.where(Producto.proveedor_id == proveedor_id)
    if temporada:
        consulta = consulta.where(Producto.temporada == temporada)
    if activo is not None:
        consulta = consulta.where(Producto.activo.is_(activo))
    if precio_desde is not None:
        consulta = consulta.where(Producto.precio_venta >= precio_desde)
    if precio_hasta is not None:
        consulta = consulta.where(Producto.precio_venta <= precio_hasta)

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()

    filas = (
        db.execute(consulta.order_by(Producto.sku).limit(tamano).offset((pagina - 1) * tamano))
        .unique()
        .scalars()
        .all()
    )
    return list(filas), total


# Cuántos caracteres hay que tener tipeados antes de buscar parecidos.
#
# Con menos, la búsqueda no dice nada útil: "cadena" coincide con medio
# catálogo y el desplegable se convierte en ruido justo cuando todavía no
# se terminó de escribir. Diez es el largo a partir del cual una
# descripción ya tiene dos palabras y empieza a identificar algo.
#
# El formulario usa el mismo número para no pedirle a la API lo que sabe
# que va a volver vacío (`MINIMO_SIMILARES` en productos.js), pero la
# regla vive acá: el endpoint la aplica igual aunque lo llame otro cliente.
MINIMO_CARACTERES_SIMILARES = 10

# Cuántas palabras cortas ("de", "18k") se ignoran al comparar.
_LARGO_PALABRA_UTIL = 3


def buscar_similares(
    db: Session,
    descripcion: str,
    categoria_id: int | None = None,
    proveedor_id: int | None = None,
    limite: int = 8,
) -> list[Producto]:
    """
    Productos ya cargados cuya descripción se parece a la que se está
    tipeando, acotados a la categoría y el proveedor elegidos.

    Alimenta el desplegable del formulario de alta, que sirve para dos
    cosas a la vez: ver que el producto tal vez ya existe antes de
    duplicarlo, y poder adoptar el nombre con el que quedó cargado, para
    que el catálogo no tenga "Cadena plata 925" y "cadena de plata 925"
    como si fueran cosas distintas.

    El parecido se resuelve palabra por palabra y no con un ILIKE sobre la
    frase entera —que es lo que hace el filtro de `listar_productos`—:
    mientras se escribe, el texto tipeado casi nunca es un fragmento
    literal de lo ya cargado. "Zapatilla Nike Air" tiene que encontrar
    "Zapatilla Nike Air Max 90", y también "Nike Air Zapatilla" si alguien
    la cargó con las palabras en otro orden. Se exigen TODAS las palabras:
    con una sola alcanzaría cualquier producto de la marca.

    Las palabras de menos de tres letras no se exigen: "de", "y" o "18k"
    aparecen en cualquier lado y no distinguen nada.

    Devuelve también los inactivos: un producto dado de baja sigue siendo
    un duplicado, y la pantalla lo marca como tal.
    """
    texto = normalizar_texto(descripcion) or ""
    if len(texto) < MINIMO_CARACTERES_SIMILARES:
        return []

    consulta = select(Producto)

    # Las dos caras de la comparación se limpian igual: la columna con
    # `translate()` en SQL y el texto tipeado en Python. Así "cafe"
    # encuentra "Café" y "café" encuentra "Cafe".
    descripcion_plana = sin_tildes_sql(Producto.descripcion)

    palabras = [p for p in texto.split() if len(p) >= _LARGO_PALABRA_UTIL]
    # Si nada llegó a tres letras es una descripción de palabras sueltas
    # ("18k 925 ar"): se busca la frase entera, que es lo único que queda.
    for palabra in palabras or [texto]:
        consulta = consulta.where(descripcion_plana.ilike(f"%{sin_tildes(palabra)}%"))

    if categoria_id is not None:
        # Incluye la descendencia, igual que el listado: los productos
        # cuelgan de las hojas, así que elegir "Zapatillas" en el formulario
        # tiene que encontrar lo que está en "Deportivas".
        from app.services.categorias import rama_de_ids

        consulta = consulta.where(Producto.categoria_id.in_(rama_de_ids(db, categoria_id)))
    if proveedor_id is not None:
        consulta = consulta.where(Producto.proveedor_id == proveedor_id)

    # Alfabético y acotado: es un desplegable de sugerencias, no un listado.
    # Sin el `id` de desempate dos descripciones iguales quedan en orden
    # arbitrario y la lista puede cambiar de una tecla a la otra.
    filas = (
        db.execute(
            consulta.order_by(func.lower(Producto.descripcion), Producto.id).limit(limite)
        )
        .unique()
        .scalars()
        .all()
    )
    return list(filas)


def listar_variantes(
    db: Session,
    busqueda: str | None = None,
    categoria_id: int | None = None,
    proveedor_id: int | None = None,
    temporada: str | None = None,
    activo: bool | None = None,
    precio_desde: Decimal | None = None,
    precio_hasta: Decimal | None = None,
    pagina: int = 1,
    tamano: int = 50,
) -> tuple[list[Variante], int]:
    """
    Listado a nivel VARIANTE, que es lo que efectivamente tiene stock y
    etiqueta. `listar_productos()` sigue existiendo para el formulario y el
    detalle, que sí trabajan sobre el producto entero.

    Los filtros son todos del producto y viajan por el join sin cambios.

    `busqueda` es un solo campo que resuelve las tres formas en que alguien
    puede referirse a un artículo:

      1. Con el código de la etiqueta, que incluye el dígito verificador
         (`SAB123R7`). Si el texto pasa la validación del dígito, se le saca
         el último carácter y se busca además el código EXACTO: es el caso
         del lector, y es el único que resuelve a una sola fila.
      2. Con el SKU del producto (`AB123`), que trae todas sus variantes.
      3. Con parte de la descripción.

    El paso 1 es lo que hace que el dígito verificador sirva para algo: un
    código mal tipeado no valida, así que no se resuelve por accidente a
    otra variante — solo queda la búsqueda por texto, que no lo encuentra.
    """
    consulta = select(Variante).join(Producto, Variante.producto_id == Producto.id)

    if busqueda:
        texto = busqueda.strip().upper()
        patron = f"%{texto}%"

        # Las tres formas se buscan SIEMPRE, y el código exacto se suma
        # cuando corresponde. Antes eran excluyentes —o código, o texto— y
        # eso hacía desaparecer resultados: un SKU también puede pasar la
        # validación del dígito por casualidad (le pasa a 1 de cada 11), y
        # ahí el buscador lo leía como etiqueta, le sacaba el último carácter
        # y comparaba contra un código que no existe. Tipear `AA009` no
        # devolvía nada, sin ninguna señal de por qué.
        condiciones = [
            Variante.codigo_completo.ilike(patron),
            Producto.sku.ilike(patron),
            Producto.descripcion.ilike(patron),
        ]

        if codigo_es_valido(texto):
            # El dígito no se persiste: la columna guarda el cuerpo.
            #
            # Sumar esta condición no relaja nada: el texto de un código
            # válido no aparece como subcadena de ningún código guardado
            # —al guardado le falta justamente el dígito— ni de un SKU ni de
            # una descripción, así que el lector sigue resolviendo a la
            # única fila de esa etiqueta.
            condiciones.append(Variante.codigo_completo == texto[:-1])

        consulta = consulta.where(or_(*condiciones))

    if categoria_id is not None:
        # Misma regla que en el listado de productos: incluye la descendencia.
        from app.services.categorias import rama_de_ids

        consulta = consulta.where(Producto.categoria_id.in_(rama_de_ids(db, categoria_id)))
    if proveedor_id is not None:
        consulta = consulta.where(Producto.proveedor_id == proveedor_id)
    if temporada:
        consulta = consulta.where(Producto.temporada == temporada)
    if activo is not None:
        consulta = consulta.where(Producto.activo.is_(activo))

    # Sobre el precio EFECTIVO: filtrar por `Producto.precio_venta` dejaría
    # afuera justamente a las variantes que tienen precio propio, que son
    # las que más motivo hay para buscar por precio.
    precio_efectivo = func.coalesce(Variante.precio_venta, Producto.precio_venta)
    if precio_desde is not None:
        consulta = consulta.where(precio_efectivo >= precio_desde)
    if precio_hasta is not None:
        consulta = consulta.where(precio_efectivo <= precio_hasta)

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()

    # Alfabético por la columna Descripción, que es como se lee la tabla.
    #
    # `lower()` para que no dependa de la mayúscula inicial, y el código
    # como desempate: las variantes de un mismo producto comparten
    # descripción, así que sin esto quedarían en orden arbitrario entre
    # ellas y el paginado podría repetir o saltear filas.
    # La descripción es NOT NULL desde la migración 0012, así que no hace
    # falta ningún COALESCE. El índice `ix_productos_descripcion_lower` está
    # creado sobre esta MISMA expresión: cambiarla acá lo deja sin usar.
    orden = func.lower(Producto.descripcion)

    filas = (
        db.execute(
            consulta.order_by(orden, Variante.codigo_completo)
            .limit(tamano)
            .offset((pagina - 1) * tamano)
        )
        .unique()
        .scalars()
        .all()
    )
    return list(filas), total


def crear_producto(
    db: Session,
    autor: Usuario,
    categoria_id: int,
    proveedor_id: int,
    precio_usd: Decimal,
    descripcion: str,
    sku_proveedor: str | None = None,
    descuento_producto: Decimal | None = None,
    peso_gramos: Decimal | None = None,
    temporada: str = Temporada.ATEMPORAL.value,
    stock_infinito: bool = False,
    stock_inicial: int | None = None,
    ip_origen: str | None = None,
) -> Producto:
    """
    Alta de producto. Genera el SKU, calcula el precio de venta y crea la
    variante BASE, todo en la misma transacción.
    """
    # En el alta el valor de partida es False: un vendedor puede mandarlo
    # apagado —es lo que hace el formulario— pero no prenderlo.
    _validar_stock_infinito(autor, stock_infinito, actual=False)

    _validar_categoria(db, categoria_id)
    proveedor = _validar_proveedor(db, proveedor_id)

    if Decimal(precio_usd) <= 0:
        raise ReglaDeNegocio("El precio en dólares debe ser mayor a cero")

    descuento = _validar_descuento(db, descuento_producto)

    if peso_gramos is not None and Decimal(peso_gramos) <= 0:
        raise ReglaDeNegocio("El peso debe ser mayor a cero")

    # Antes de reservar el SKU: si el nombre choca, el alta no tiene que
    # consumir un número del correlativo.
    descripcion_limpia = _validar_descripcion(descripcion)
    _validar_descripcion_unica(db, descripcion_limpia, categoria_id, proveedor_id)

    producto = Producto(
        sku=_siguiente_sku(db),
        sku_proveedor=normalizar_texto(sku_proveedor),
        descripcion=descripcion_limpia,
        categoria_id=categoria_id,
        proveedor_id=proveedor_id,
        precio_usd=Decimal(precio_usd),
        precio_venta=calcular_precio_venta(db, precio_usd, proveedor.dolar_actual),
        descuento_producto=descuento,
        peso_gramos=Decimal(peso_gramos) if peso_gramos is not None else None,
        temporada=Temporada(temporada),
        stock_infinito=stock_infinito,
        tiene_variantes=False,
        activo=True,
        created_at=ahora_db(),
        updated_at=ahora_db(),
    )
    db.add(producto)
    db.flush()

    # Todo producto arranca con su BASE: así el stock siempre cuelga de una
    # variante, con o sin variantes reales.
    base = _crear_variante(db, producto, sufijo=None, es_base=True)

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="producto.crear",
        entidad="productos",
        entidad_id=producto.id,
        estado_nuevo=producto,
        ip_origen=ip_origen,
    )

    if stock_inicial:
        _ingresar_stock_inicial(db, autor, base, stock_inicial, ip_origen)

    return producto


def editar_producto(
    db: Session,
    autor: Usuario,
    producto_id: int,
    descripcion: str | None = None,
    sku_proveedor: str | None = None,
    categoria_id: int | None = None,
    precio_usd: Decimal | None = None,
    descuento_producto: Decimal | None = None,
    peso_gramos: Decimal | None = None,
    temporada: str | None = None,
    stock_infinito: bool | None = None,
    ip_origen: str | None = None,
) -> Producto:
    """
    Edita el producto. El SKU y el proveedor no se cambian: el SKU está
    impreso en las etiquetas, y cambiar de proveedor cambiaría la base del
    precio sin dejar rastro de por qué.
    """
    producto = obtener_producto(db, producto_id)
    antes = snapshot(producto)

    # Antes de tocar nada: si el pedido no está permitido, la edición entera
    # se rechaza y no queda a medias.
    _validar_stock_infinito(autor, stock_infinito, actual=producto.stock_infinito)

    if categoria_id is not None:
        _validar_categoria(db, categoria_id)

    # La unicidad se controla sobre cómo va a quedar el producto, no sobre
    # cómo está: mover un producto de categoría puede hacerlo chocar con
    # otro sin que su descripción cambie, y renombrarlo también.
    #
    # Y se controla ANTES de asignar nada: con el objeto ya modificado, la
    # consulta dispara el autoflush de SQLAlchemy y el choque volvería como
    # error de integridad del índice, sin decir contra cuál chocó.
    nueva_descripcion = (
        _validar_descripcion(descripcion) if descripcion is not None else producto.descripcion
    )
    _validar_descripcion_unica(
        db,
        nueva_descripcion,
        categoria_id if categoria_id is not None else producto.categoria_id,
        producto.proveedor_id,
        excluir_id=producto.id,
    )

    if categoria_id is not None:
        producto.categoria_id = categoria_id
    if descripcion is not None:
        producto.descripcion = nueva_descripcion
    if sku_proveedor is not None:
        producto.sku_proveedor = normalizar_texto(sku_proveedor)

    if precio_usd is not None:
        if Decimal(precio_usd) <= 0:
            raise ReglaDeNegocio("El precio en dólares debe ser mayor a cero")
        producto.precio_usd = Decimal(precio_usd)
        # El precio de venta se deriva: cambiar uno sin el otro dejaría la
        # base inconsistente.
        producto.precio_venta = calcular_precio_venta(
            db, producto.precio_usd, producto.proveedor.dolar_actual
        )

    if descuento_producto is not None:
        producto.descuento_producto = _validar_descuento(db, descuento_producto)

    if peso_gramos is not None:
        if Decimal(peso_gramos) <= 0:
            raise ReglaDeNegocio("El peso debe ser mayor a cero")
        producto.peso_gramos = Decimal(peso_gramos)

    if temporada is not None:
        producto.temporada = Temporada(temporada)
    if stock_infinito is not None:
        producto.stock_infinito = stock_infinito

    producto.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="producto.editar",
        entidad="productos",
        entidad_id=producto.id,
        estado_anterior=antes,
        estado_nuevo=producto,
        ip_origen=ip_origen,
    )
    return producto


def cambiar_estado_producto(
    db: Session, autor: Usuario, producto_id: int, activo: bool, ip_origen: str | None = None
) -> Producto:
    """
    Alta o baja lógica. Los productos no se borran: quedan referenciados
    en ventas y en movimientos de stock.
    """
    producto = obtener_producto(db, producto_id)
    antes = snapshot(producto)

    producto.activo = activo
    producto.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="producto.activar" if activo else "producto.desactivar",
        entidad="productos",
        entidad_id=producto.id,
        estado_anterior=antes,
        estado_nuevo=producto,
        ip_origen=ip_origen,
    )
    return producto


# ============================================================================
# CÓDIGO DE BARRAS
# ============================================================================


def barcode_svg_para_etiqueta(db: Session, variante_id: int) -> tuple[str, str]:
    """
    SVG compacto + texto del código, para incrustar en el PDF de etiquetas.

    El SVG se genera sin texto (lo pone la plantilla HTML con tipografía
    controlada) y con módulos más finos para que quepa en 3,5 cm de ancho.

    WeasyPrint respeta los atributos ``width``/``height`` del SVG en lugar del
    CSS, así que se fuerzan a dimensiones fijas que dejan espacio para el texto
    del código debajo (5.5mm de barcode + ~3.5mm de texto = ~9mm en 1cm).
    """
    import io
    import re

    from barcode import Code128
    from barcode.writer import SVGWriter

    variante = obtener_variante(db, variante_id)
    codigo = variante.codigo_con_verificador

    buffer = io.BytesIO()
    Code128(codigo, writer=SVGWriter()).write(
        buffer,
        options={
            "module_width": 0.2,
            "module_height": 4.0,
            "write_text": False,
            "quiet_zone": 1.0,
        },
    )
    svg = buffer.getvalue().decode("utf-8")
    # Quitar la declaración XML para incrustar directo en HTML.
    svg = svg.replace('<?xml version="1.0" encoding="UTF-8"?>\n', "")

    # Quitar DOCTYPE (WeasyPrint no lo necesita y puede causar problemas).
    svg = re.sub(r"<!DOCTYPE[^>]+>", "", svg)

    # Forzar dimensiones del SVG para que ocupe ~50% del ancho de la
    # etiqueta (33mm) y deje espacio al código de texto debajo.
    # WeasyPrint respeta los atributos width/height del tag SVG, no el CSS.
    svg = re.sub(
        r'width="[\d.]+mm"\s+height="[\d.]+mm"',
        'width="16mm" height="4.5mm"',
        svg,
        count=1,
    )
    return svg, codigo


def barcode_svg(db: Session, variante_id: int) -> str:
    """
    Code128 de la variante, en SVG.

    Se codifica `codigo_completo + verificador`: el módulo 11 viaja dentro
    del código de barras, así que un escaneo también lo trae. El checksum
    módulo 103 de Code128 lo agrega la librería sola; nunca se persiste.
    """
    import io

    from barcode import Code128
    from barcode.writer import SVGWriter

    variante = obtener_variante(db, variante_id)

    buffer = io.BytesIO()
    Code128(variante.codigo_con_verificador, writer=SVGWriter()).write(buffer)
    return buffer.getvalue().decode("utf-8")
