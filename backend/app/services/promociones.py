"""
Promociones 2x1 y 3x2: el catálogo y la regla que las aplica.

Una promoción no es un descuento. El descuento baja el precio de una unidad
un porcentaje; la promoción agrupa unidades y deja alguna en $0. Por eso son
excluyentes sobre el mismo ítem —serían dos beneficios apilados— y por eso
la lógica vive acá y no en `descuentos.py`.

La regla del negocio en una línea: **siempre se cobran las más caras**. Lo
que queda gratis es lo más barato de cada grupo completo, y lo que no llega
a completar un grupo se cobra entero. Aplicarlo al revés —regalar lo caro—
sería regalar plata, y hacerlo "en el orden en que se cargó" haría que el
total dependiera de en qué orden la vendedora pasó los productos por el
lector.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import ahora_db, normalizar_texto, sin_tildes, sin_tildes_sql
from app.models.cliente import ClientePromocion
from app.models.categoria import Categoria
from app.models.producto import Producto
from app.models.promocion import Promocion, PromocionAlcance, TipoAlcance, TipoPromocion
from app.models.usuario import Usuario
from app.services import categorias as servicio_categorias
from app.services.roles import NoEncontrado, ReglaDeNegocio


# ============================================================================
# LA REGLA
# ============================================================================


def unidades_gratis(cantidad: int, promocion: Promocion) -> int:
    """
    Cuántas unidades quedan en $0 con esa cantidad de ítems alcanzados.

    Solo cuentan los grupos COMPLETOS: con un 3x2 y 5 productos hay un grupo
    de 3 (una unidad gratis) y sobran 2, que se cobran enteras. La división
    entera es la regla, no un redondeo casual.
    """
    grupos = cantidad // promocion.tamano_grupo
    return grupos * (promocion.tamano_grupo - promocion.pagas_por_grupo)


def elegir_unidades_gratis(items: list, promocion: Promocion) -> list:
    """
    Cuáles de esos ítems quedan en $0.

    `items` son objetos con `precio_unitario` y `orden` (en la práctica,
    `VentaItem`). Devuelve la sublista que va a $0, sin tocar nada: quien
    llama decide qué hacer con eso.

    El orden de la decisión: precio DESCENDENTE, y el `orden` de carga como
    desempate. El desempate no es un detalle — sin él, dos corridas sobre el
    mismo carrito podrían regalar unidades distintas del mismo precio, y el
    total daría igual pero el detalle de la venta no sería reproducible.

    Se regala la más barata DE CADA GRUPO, no las más baratas del carrito.
    No es lo mismo y la diferencia es plata: con un 2x1 y precios
    [100, 90, 80, 70, 60], por grupo se regalan 90 y 70 (se cobran 240), y
    tomando las dos más baratas del total se regalarían 70 y 60 (se cobran
    270). La promoción se pactó por grupos, así que el sobrante —el más
    barato, que no completa ninguno— es el que se cobra entero.
    """
    if unidades_gratis(len(items), promocion) <= 0:
        return []

    # De más cara a más barata. Los grupos se arman en ese orden, así que el
    # que sobra al final es siempre el más barato.
    ordenados = sorted(items, key=lambda i: (-Decimal(i.precio_unitario), i.orden))

    tamano = promocion.tamano_grupo
    paga = promocion.pagas_por_grupo
    gratis: list = []
    for inicio in range(0, (len(ordenados) // tamano) * tamano, tamano):
        grupo = ordenados[inicio : inicio + tamano]
        # El grupo ya viene de mayor a menor: lo que queda después de las
        # que se pagan son las más baratas.
        gratis.extend(grupo[paga:])
    return gratis


# ============================================================================
# ALCANCE: sobre qué productos aplica
# ============================================================================


def productos_alcanzados(db: Session, promocion: Promocion) -> set[int]:
    """
    Los `producto_id` que la promoción cubre.

    Se resuelve una vez por promoción y no una consulta por ítem: el carrito
    es chico pero la pantalla recalcula el total en cada escaneo, y una
    consulta por unidad por promoción se nota.

    Una categoría alcanza también a sus DESCENDIENTES: quien pone "Plata" en
    una promo espera que entren "Plata > Anillos" y "Plata > Cadenas". Lo
    contrario obligaría a cargar hoja por hoja y a acordarse de volver acá
    cada vez que se agrega una subcategoría.
    """
    ids_producto: set[int] = set()
    ids_categoria: set[int] = set()

    for alcance in promocion.alcances:
        if alcance.tipo_alcance == TipoAlcance.PRODUCTO:
            ids_producto.add(alcance.referencia_id)
        else:
            ids_categoria.update(servicio_categorias.rama_de_ids(db, alcance.referencia_id))

    if ids_categoria:
        filas = db.execute(
            select(Producto.id).where(Producto.categoria_id.in_(ids_categoria))
        ).scalars()
        ids_producto.update(filas)

    return ids_producto


def promociones_aplicables(
    db: Session, cliente_id: int | None = None, dia: date | None = None
) -> list[Promocion]:
    """
    Las promociones que hoy se pueden ofrecer en una venta.

    Son las generales —activas y en fecha— más las asignadas puntualmente a
    este cliente. Las del cliente NO se filtran distinto: también tienen que
    estar activas y vigentes, porque una promo vencida no revive por estar
    asignada a alguien.
    """
    dia = dia or ahora_db().date()

    generales = list(
        db.execute(select(Promocion).where(Promocion.activo.is_(True))).scalars().all()
    )
    vigentes = [p for p in generales if p.vigente_el(dia)]

    # Las asignadas al cliente ya están en `generales` si son globales; la
    # diferencia es que una promo puede existir SOLO para ciertos clientes.
    # Ese caso se resuelve en `es_exclusiva_de_clientes()`, abajo.
    if cliente_id is None:
        return [p for p in vigentes if not es_exclusiva_de_clientes(db, p)]

    asignadas = set(
        db.execute(
            select(ClientePromocion.promocion_id).where(
                ClientePromocion.cliente_id == cliente_id
            )
        ).scalars()
    )
    return [
        p
        for p in vigentes
        if p.id in asignadas or not es_exclusiva_de_clientes(db, p)
    ]


def es_exclusiva_de_clientes(db: Session, promocion: Promocion) -> bool:
    """
    Si la promoción está asignada a algún cliente en particular.

    Con al menos una asignación, deja de ser del catálogo y pasa a ser un
    beneficio de esas personas: no se le ofrece a una venta sin cliente ni a
    un cliente que no la tiene. Sin ninguna, es para todos.
    """
    return bool(
        db.execute(
            select(func.count())
            .select_from(ClientePromocion)
            .where(ClientePromocion.promocion_id == promocion.id)
        ).scalar_one()
    )


# ============================================================================
# ABM
# ============================================================================


def obtener_promocion(db: Session, promocion_id: int) -> Promocion:
    promocion = db.get(Promocion, promocion_id)
    if promocion is None:
        raise NoEncontrado("Promoción inexistente")
    return promocion


def listar_promociones(
    db: Session,
    nombre: str | None = None,
    tipo: TipoPromocion | None = None,
    activo: bool | None = None,
    vigente: bool | None = None,
) -> list[Promocion]:
    """
    El catálogo con los filtros del Principio 5. Tabla chica: sin paginación.

    `vigente` no es lo mismo que `activo`: una promo activa con fecha de fin
    pasada no rige hoy, y esa es justamente la que hay que poder encontrar
    para entender por qué no se está aplicando.
    """
    consulta = select(Promocion)

    if nombre:
        consulta = consulta.where(
            sin_tildes_sql(Promocion.nombre).ilike(f"%{sin_tildes(nombre)}%")
        )
    if tipo is not None:
        consulta = consulta.where(Promocion.tipo == tipo)
    if activo is not None:
        consulta = consulta.where(Promocion.activo.is_(activo))

    filas = list(db.execute(consulta.order_by(Promocion.nombre)).scalars().all())

    if vigente is not None:
        hoy = ahora_db().date()
        filas = [p for p in filas if p.vigente_el(hoy) is vigente]

    return filas


def _validar_alcances(db: Session, alcances: list[dict]) -> None:
    """
    Que cada referencia exista de verdad.

    `promocion_alcance.referencia_id` no lleva FK —apunta a dos tablas
    distintas según el tipo—, así que la validación que la base no puede
    hacer se hace acá. Sin esto, un id tipeado mal daría una promoción que
    nunca aplica y nada avisaría por qué.
    """
    for alcance in alcances:
        tipo = alcance["tipo_alcance"]
        referencia = alcance["referencia_id"]
        modelo = Producto if tipo == TipoAlcance.PRODUCTO else Categoria
        if db.get(modelo, referencia) is None:
            etiqueta = "producto" if tipo == TipoAlcance.PRODUCTO else "categoría"
            raise ReglaDeNegocio(f"No existe el {etiqueta} {referencia}")


def _validar_nombre_unico(db: Session, nombre: str, excluir_id: int | None = None) -> None:
    consulta = select(Promocion.id).where(func.lower(Promocion.nombre) == nombre.lower())
    if excluir_id is not None:
        consulta = consulta.where(Promocion.id != excluir_id)
    if db.execute(consulta).scalar_one_or_none():
        raise ReglaDeNegocio(f"Ya existe una promoción '{nombre}'")


def crear_promocion(
    db: Session,
    autor: Usuario,
    *,
    nombre: str,
    tipo: TipoPromocion,
    alcances: list[dict],
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    ip_origen: str | None = None,
) -> Promocion:
    limpio = normalizar_texto(nombre)
    if not limpio:
        raise ReglaDeNegocio("El nombre de la promoción es obligatorio")
    _validar_nombre_unico(db, limpio)

    # Una promoción sin alcance no aplica a nada: sería una fila que existe
    # para no hacer nada, y en la pantalla se vería activa.
    if not alcances:
        raise ReglaDeNegocio(
            "La promoción tiene que alcanzar al menos un producto o una categoría"
        )
    _validar_alcances(db, alcances)

    if fecha_inicio and fecha_fin and fecha_inicio > fecha_fin:
        raise ReglaDeNegocio("La fecha de fin no puede ser anterior a la de inicio")

    promocion = Promocion(
        nombre=limpio,
        tipo=tipo,
        activo=True,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        created_at=ahora_db(),
        updated_at=ahora_db(),
    )
    promocion.alcances = [
        PromocionAlcance(
            tipo_alcance=a["tipo_alcance"], referencia_id=a["referencia_id"]
        )
        for a in _sin_repetidos(alcances)
    ]
    db.add(promocion)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="promocion.crear",
        entidad="promociones",
        entidad_id=promocion.id,
        estado_nuevo=promocion,
        ip_origen=ip_origen,
    )
    return promocion


def _sin_repetidos(alcances: list[dict]) -> list[dict]:
    """
    Quita los alcances duplicados antes de llegar a la base.

    El UNIQUE los rechazaría igual, pero con un error de integridad ilegible.
    Y mandar dos veces la misma categoría no es un error del usuario: es lo
    que pasa cuando la pantalla arma la lista desde dos lados.
    """
    vistos: set[tuple] = set()
    unicos = []
    for a in alcances:
        clave = (a["tipo_alcance"], a["referencia_id"])
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(a)
    return unicos


def editar_promocion(
    db: Session,
    autor: Usuario,
    promocion_id: int,
    *,
    nombre: str | None = None,
    tipo: TipoPromocion | None = None,
    alcances: list[dict] | None = None,
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    editar_fechas: bool = False,
    ip_origen: str | None = None,
) -> Promocion:
    """
    Cambia la definición de la promoción.

    `editar_fechas` distingue "no las mandes" de "ponelas en NULL": None es
    ambiguo y acá NULL significa algo concreto —sacarle el límite de fecha—,
    igual que `editar_precio` en el módulo de productos.

    Las ventas ya confirmadas no se tocan: guardaron su `promocion_id` y sus
    precios, así que cambiar la promo hoy no reescribe lo que se cobró ayer.
    """
    promocion = obtener_promocion(db, promocion_id)
    antes = snapshot(promocion)

    if nombre is not None:
        limpio = normalizar_texto(nombre)
        if not limpio:
            raise ReglaDeNegocio("El nombre de la promoción es obligatorio")
        _validar_nombre_unico(db, limpio, excluir_id=promocion.id)
        promocion.nombre = limpio

    if tipo is not None:
        promocion.tipo = tipo

    if editar_fechas:
        if fecha_inicio and fecha_fin and fecha_inicio > fecha_fin:
            raise ReglaDeNegocio("La fecha de fin no puede ser anterior a la de inicio")
        promocion.fecha_inicio = fecha_inicio
        promocion.fecha_fin = fecha_fin

    if alcances is not None:
        if not alcances:
            raise ReglaDeNegocio(
                "La promoción tiene que alcanzar al menos un producto o una categoría"
            )
        _validar_alcances(db, alcances)
        # Se reemplaza la lista entera y no se hace un diff: el alcance es
        # una definición, no un historial, y el `delete-orphan` de la
        # relación se ocupa de las filas que salen.
        promocion.alcances = [
            PromocionAlcance(
                tipo_alcance=a["tipo_alcance"], referencia_id=a["referencia_id"]
            )
            for a in _sin_repetidos(alcances)
        ]

    promocion.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="promocion.editar",
        entidad="promociones",
        entidad_id=promocion.id,
        estado_anterior=antes,
        estado_nuevo=promocion,
        ip_origen=ip_origen,
    )
    return promocion


def cambiar_estado(
    db: Session,
    autor: Usuario,
    promocion_id: int,
    activo: bool,
    ip_origen: str | None = None,
) -> Promocion:
    """
    Prende o apaga la promoción.

    No hay borrado: las ventas confirmadas la apuntan, y borrarla dejaría
    ítems en $0 sin decir por qué estaban en $0.
    """
    promocion = obtener_promocion(db, promocion_id)
    antes = snapshot(promocion)

    promocion.activo = activo
    promocion.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="promocion.activar" if activo else "promocion.desactivar",
        entidad="promociones",
        entidad_id=promocion.id,
        estado_anterior=antes,
        estado_nuevo=promocion,
        ip_origen=ip_origen,
    )
    return promocion


# ============================================================================
# ASIGNACIÓN A CLIENTES
# ============================================================================


def asignar_a_cliente(
    db: Session, autor: Usuario, cliente_id: int, promocion_id: int,
    ip_origen: str | None = None,
) -> ClientePromocion:
    promocion = obtener_promocion(db, promocion_id)

    ya_esta = db.execute(
        select(ClientePromocion).where(
            ClientePromocion.cliente_id == cliente_id,
            ClientePromocion.promocion_id == promocion_id,
        )
    ).scalar_one_or_none()
    if ya_esta is not None:
        return ya_esta

    fila = ClientePromocion(cliente_id=cliente_id, promocion_id=promocion_id)
    db.add(fila)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="cliente.promocion_asignar",
        entidad="cliente_promociones",
        entidad_id=fila.id,
        estado_nuevo={"cliente_id": cliente_id, "promocion": promocion.nombre},
        ip_origen=ip_origen,
    )
    return fila


def quitar_de_cliente(
    db: Session, autor: Usuario, cliente_id: int, promocion_id: int,
    ip_origen: str | None = None,
) -> None:
    fila = db.execute(
        select(ClientePromocion).where(
            ClientePromocion.cliente_id == cliente_id,
            ClientePromocion.promocion_id == promocion_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("El cliente no tiene asignada esa promoción")

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="cliente.promocion_quitar",
        entidad="cliente_promociones",
        entidad_id=fila.id,
        estado_anterior=fila,
        ip_origen=ip_origen,
    )
    db.delete(fila)
    db.flush()


def promociones_de_cliente(db: Session, cliente_id: int) -> list[Promocion]:
    return list(
        db.execute(
            select(Promocion)
            .join(ClientePromocion, ClientePromocion.promocion_id == Promocion.id)
            .where(ClientePromocion.cliente_id == cliente_id)
            .order_by(Promocion.nombre)
        )
        .scalars()
        .all()
    )
