"""
Clientes y su cuenta de puntos.

El cliente es OPCIONAL en la venta. Existe para lo que necesita un nombre
atrás —los puntos, las señas, las promociones asignadas— y no para llenar
una ficha: en el mostrador la mayoría compra sin identificarse, y obligar a
cargarlo frenaría la caja.

El saldo de puntos no es una columna: se calcula sumando `puntos_cliente`
(Principio 4). Esa tabla es de solo inserción y la base lo garantiza con un
trigger, así que corregir un movimiento mal cargado se hace con un `ajuste`
de signo contrario, nunca editando el original.
"""

from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import (
    ahora_db,
    normalizar_texto,
    sin_tildes,
    sin_tildes_sql,
)
from app.models.cliente import Cliente, PuntoCliente, TipoPunto
from app.models.usuario import Usuario
from app.services.roles import NoEncontrado, ReglaDeNegocio

# Cuántos pesos de venta valen un punto.
#
# SUPUESTO A CONFIRMAR: el prompt del módulo pide sumar puntos pero no fija
# la equivalencia. Queda acá, en una constante con nombre, y no repartida en
# la fórmula: el día que el negocio la defina —o la quiera configurable— se
# cambia en un solo lugar y no hay que salir a buscar dónde se multiplicaba.
PESOS_POR_PUNTO = Decimal("1000")


def puntos_por_venta(total: Decimal) -> int:
    """
    Cuántos puntos deja una venta de ese total.

    Trunca hacia abajo: media compra no da medio punto. Una venta de $0
    —todo cubierto por promoción— no da ninguno, que es lo correcto: los
    puntos premian lo que se gastó.
    """
    if PESOS_POR_PUNTO <= 0:
        return 0
    return int(Decimal(total) // PESOS_POR_PUNTO)


# ============================================================================
# CONSULTA
# ============================================================================


def obtener_cliente(db: Session, cliente_id: int) -> Cliente:
    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise NoEncontrado("Cliente inexistente")
    return cliente


def saldo_puntos(db: Session, cliente_id: int) -> int:
    """
    Los puntos que le quedan: la suma de todos sus movimientos.

    Se calcula y no se guarda (Principio 4). Un saldo persistido sería un
    segundo número capaz de quedar viejo, y el historial es justamente lo
    que permite explicar por qué el saldo es el que es.
    """
    return int(
        db.execute(
            select(func.coalesce(func.sum(PuntoCliente.cantidad), 0)).where(
                PuntoCliente.cliente_id == cliente_id
            )
        ).scalar_one()
    )


def saldos_puntos(db: Session, ids: list[int]) -> dict[int, int]:
    """
    El saldo de varios clientes de una sola consulta.

    El listado muestra los puntos de cada fila: pedirlos de a uno serían
    cincuenta consultas por página. Los clientes sin ningún movimiento no
    vuelven en el resultado, y quien llama los completa con 0.
    """
    if not ids:
        return {}
    filas = db.execute(
        select(PuntoCliente.cliente_id, func.sum(PuntoCliente.cantidad))
        .where(PuntoCliente.cliente_id.in_(ids))
        .group_by(PuntoCliente.cliente_id)
    ).all()
    return {cliente_id: int(total) for cliente_id, total in filas}


def historial_puntos(
    db: Session, cliente_id: int, limite: int = 200
) -> list[PuntoCliente]:
    """Los movimientos del cliente, del más nuevo al más viejo."""
    obtener_cliente(db, cliente_id)
    return list(
        db.execute(
            select(PuntoCliente)
            .where(PuntoCliente.cliente_id == cliente_id)
            .order_by(PuntoCliente.timestamp.desc(), PuntoCliente.id.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )


def listar_clientes(
    db: Session,
    *,
    busqueda: str | None = None,
    localidad: str | None = None,
    activo: bool | None = None,
    pagina: int = 1,
    tamano: int = 50,
) -> tuple[list[Cliente], int]:
    """
    Listado con los filtros por defecto del Principio 5, resueltos en el
    backend.

    `busqueda` es un solo campo que barre nombre y DNI, y no dos filtros
    separados: quien busca a alguien tiene el dato que tiene, y no debería
    tener que elegir en qué casillero escribirlo.
    """
    consulta = select(Cliente)

    if busqueda:
        texto = busqueda.strip()
        consulta = consulta.where(
            or_(
                sin_tildes_sql(Cliente.nombre).ilike(f"%{sin_tildes(texto)}%"),
                Cliente.dni.ilike(f"%{texto}%"),
            )
        )
    if localidad:
        consulta = consulta.where(
            sin_tildes_sql(Cliente.localidad).ilike(f"%{sin_tildes(localidad)}%")
        )
    if activo is not None:
        consulta = consulta.where(Cliente.activo.is_(activo))

    total = db.execute(
        select(func.count()).select_from(consulta.subquery())
    ).scalar_one()

    filas = (
        db.execute(
            consulta.order_by(func.lower(Cliente.nombre))
            .offset((pagina - 1) * tamano)
            .limit(tamano)
        )
        .scalars()
        .all()
    )
    return list(filas), total


def buscar(db: Session, texto: str, limite: int = 10) -> list[Cliente]:
    """
    Búsqueda rápida para el punto de venta: por nombre o por DNI.

    Solo activos y acotada: es un desplegable de sugerencias mientras la
    vendedora tipea, no un listado. Un cliente dado de baja no se puede
    asociar a una venta nueva, así que ofrecerlo sería ofrecer un error.
    """
    limpio = (texto or "").strip()
    if not limpio:
        return []

    return list(
        db.execute(
            select(Cliente)
            .where(
                Cliente.activo.is_(True),
                or_(
                    sin_tildes_sql(Cliente.nombre).ilike(f"%{sin_tildes(limpio)}%"),
                    Cliente.dni.ilike(f"{limpio}%"),
                ),
            )
            .order_by(func.lower(Cliente.nombre))
            .limit(limite)
        )
        .scalars()
        .all()
    )


# ============================================================================
# ABM
# ============================================================================


def _validar_dni_unico(db: Session, dni: str, excluir_id: int | None = None) -> None:
    """
    Dos clientes con el mismo DNI serían la misma persona dos veces: los
    puntos y las señas quedarían partidos entre las dos fichas.

    La base también lo garantiza con un UNIQUE; esto existe para devolver un
    mensaje entendible en vez de un error de integridad.
    """
    consulta = select(Cliente.nombre).where(Cliente.dni == dni)
    if excluir_id is not None:
        consulta = consulta.where(Cliente.id != excluir_id)
    duenio = db.execute(consulta).scalar_one_or_none()
    if duenio:
        raise ReglaDeNegocio(f"El DNI {dni} ya está cargado en el cliente '{duenio}'")


def _limpiar_dni(dni: str | None) -> str | None:
    """
    Deja solo los dígitos.

    "20.123.456" y "20123456" son el mismo documento, y guardarlos distinto
    haría que el UNIQUE no sirva para nada y que la búsqueda del punto de
    venta no encuentre a quien está cargado con puntos.
    """
    limpio = normalizar_texto(dni)
    if limpio is None:
        return None
    solo_digitos = "".join(c for c in limpio if c.isdigit())
    if not solo_digitos:
        raise ReglaDeNegocio(f"El DNI '{dni}' no tiene ningún número")
    return solo_digitos


def crear_cliente(
    db: Session,
    autor: Usuario,
    *,
    nombre: str,
    dni: str | None = None,
    domicilio: str | None = None,
    codigo_postal: str | None = None,
    localidad: str | None = None,
    telefono: str | None = None,
    email: str | None = None,
    ip_origen: str | None = None,
) -> Cliente:
    limpio = normalizar_texto(nombre)
    if not limpio:
        raise ReglaDeNegocio("El nombre del cliente es obligatorio")

    documento = _limpiar_dni(dni)
    if documento:
        _validar_dni_unico(db, documento)

    cliente = Cliente(
        nombre=limpio,
        dni=documento,
        domicilio=normalizar_texto(domicilio),
        codigo_postal=normalizar_texto(codigo_postal),
        localidad=normalizar_texto(localidad),
        telefono=normalizar_texto(telefono),
        email=normalizar_texto(email),
        activo=True,
        created_at=ahora_db(),
        updated_at=ahora_db(),
    )
    db.add(cliente)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="cliente.crear",
        entidad="clientes",
        entidad_id=cliente.id,
        estado_nuevo=cliente,
        ip_origen=ip_origen,
    )
    return cliente


# Los campos de texto que se editan igual: se normalizan y se guardan tal
# cual. Van en una tupla para no repetir doce veces el mismo `if`.
_CAMPOS_TEXTO = ("domicilio", "codigo_postal", "localidad", "telefono", "email")


def editar_cliente(
    db: Session,
    autor: Usuario,
    cliente_id: int,
    *,
    nombre: str | None = None,
    dni: str | None = None,
    editar_dni: bool = False,
    ip_origen: str | None = None,
    **campos,
) -> Cliente:
    """
    Edita la ficha.

    `editar_dni` distingue "no lo mandes" de "borralo": None es ambiguo y
    acá NULL significa algo concreto —el cliente se queda sin documento
    cargado—, igual que `editar_precio` en el módulo de productos.
    """
    cliente = obtener_cliente(db, cliente_id)
    antes = snapshot(cliente)

    if nombre is not None:
        limpio = normalizar_texto(nombre)
        if not limpio:
            raise ReglaDeNegocio("El nombre del cliente es obligatorio")
        cliente.nombre = limpio

    if editar_dni:
        documento = _limpiar_dni(dni)
        if documento:
            _validar_dni_unico(db, documento, excluir_id=cliente.id)
        cliente.dni = documento

    for campo in _CAMPOS_TEXTO:
        if campo in campos and campos[campo] is not None:
            setattr(cliente, campo, normalizar_texto(campos[campo]))

    cliente.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="cliente.editar",
        entidad="clientes",
        entidad_id=cliente.id,
        estado_anterior=antes,
        estado_nuevo=cliente,
        ip_origen=ip_origen,
    )
    return cliente


def cambiar_estado(
    db: Session,
    autor: Usuario,
    cliente_id: int,
    activo: bool,
    ip_origen: str | None = None,
) -> Cliente:
    """
    Baja lógica y reactivación.

    No hay borrado físico: las ventas, las señas y los puntos lo apuntan.
    Un cliente inactivo no se ofrece en el punto de venta y sigue
    explicando su historial.
    """
    cliente = obtener_cliente(db, cliente_id)
    antes = snapshot(cliente)

    cliente.activo = activo
    cliente.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="cliente.activar" if activo else "cliente.desactivar",
        entidad="clientes",
        entidad_id=cliente.id,
        estado_anterior=antes,
        estado_nuevo=cliente,
        ip_origen=ip_origen,
    )
    return cliente


# ============================================================================
# PUNTOS
# ============================================================================


def registrar_movimiento_puntos(
    db: Session,
    autor: Usuario,
    *,
    cliente_id: int,
    tipo: TipoPunto,
    cantidad: int,
    venta_id: int | None = None,
    descripcion: str | None = None,
    ip_origen: str | None = None,
) -> PuntoCliente:
    """
    ÚNICO camino por el que se mueven los puntos de un cliente.

    No hace commit: la acumulación de una venta se confirma en la MISMA
    transacción que descuenta el stock, o la venta quedaría con puntos que
    no corresponden a nada (o al revés).

    El canje entra con cantidad positiva y se guarda en negativo: quien
    llama piensa en "canjeó 500 puntos", no en "sumale -500". El signo lo
    pone la regla, no el que la usa — la misma idea que en los movimientos
    de stock.
    """
    cliente = obtener_cliente(db, cliente_id)

    if cantidad == 0:
        raise ReglaDeNegocio("Un movimiento de puntos no puede ser de cero")

    if tipo == TipoPunto.CANJE:
        magnitud = abs(cantidad)
        disponible = saldo_puntos(db, cliente_id)
        if magnitud > disponible:
            raise ReglaDeNegocio(
                f"{cliente.nombre} tiene {disponible} puntos: no alcanzan para "
                f"canjear {magnitud}"
            )
        efectiva = -magnitud
    elif tipo == TipoPunto.ACUMULACION:
        efectiva = abs(cantidad)
    else:
        # El ajuste es el único que respeta el signo que le mandan: puede
        # corregir para arriba o para abajo.
        efectiva = cantidad
        if not normalizar_texto(descripcion):
            raise ReglaDeNegocio("Un ajuste de puntos necesita un motivo escrito")
        # Un ajuste no puede dejar el saldo negativo: serían puntos que el
        # cliente debe, y eso no existe en el negocio.
        if saldo_puntos(db, cliente_id) + efectiva < 0:
            raise ReglaDeNegocio(
                "El ajuste dejaría el saldo de puntos en negativo"
            )

    movimiento = PuntoCliente(
        cliente_id=cliente_id,
        venta_id=venta_id,
        tipo=tipo,
        cantidad=efectiva,
        descripcion=normalizar_texto(descripcion),
        usuario_id=autor.id,
        timestamp=ahora_db(),
    )
    db.add(movimiento)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion=f"cliente.puntos_{tipo.value}",
        entidad="puntos_cliente",
        entidad_id=movimiento.id,
        estado_nuevo=movimiento,
        ip_origen=ip_origen,
    )
    return movimiento
