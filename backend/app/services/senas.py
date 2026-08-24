"""
Señas: plata que el cliente ya entregó y todavía no gastó.

Dos reglas la definen:

- **No existe seña sin cliente.** Es plata de alguien, y al cobrar hay que
  saber a quién ofrecérsela.
- **El saldo solo baja usándola en una venta.** No hay endpoint para
  editarlo a mano: se descuenta desde `consumir()`, dentro de la misma
  transacción que confirma la venta. Un saldo editable sería plata que
  aparece y desaparece sin que ninguna venta lo explique.

Cuando el saldo llega a cero la seña se apaga sola. No se borra: las ventas
donde se usó la apuntan.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import ahora_db, normalizar_texto, redondear
from app.models.sena import Sena
from app.models.usuario import Usuario
from app.services import clientes as servicio_clientes
from app.services.roles import NoEncontrado, ReglaDeNegocio


def obtener_sena(db: Session, sena_id: int) -> Sena:
    sena = db.get(Sena, sena_id)
    if sena is None:
        raise NoEncontrado("Seña inexistente")
    return sena


def listar_senas(
    db: Session,
    *,
    cliente_id: int | None = None,
    activo: bool | None = None,
    con_saldo: bool | None = None,
    pagina: int = 1,
    tamano: int = 50,
) -> tuple[list[Sena], int]:
    """
    Listado con los filtros del Principio 5, resueltos en el backend.

    `con_saldo` no es lo mismo que `activo`: sirve para encontrar las que ya
    se gastaron enteras, que son las que uno busca cuando el cliente
    pregunta en qué se le fue la seña.
    """
    consulta = select(Sena)

    if cliente_id is not None:
        consulta = consulta.where(Sena.cliente_id == cliente_id)
    if activo is not None:
        consulta = consulta.where(Sena.activo.is_(activo))
    if con_saldo is True:
        consulta = consulta.where(Sena.saldo > 0)
    elif con_saldo is False:
        consulta = consulta.where(Sena.saldo == 0)

    total = db.execute(select(func.count()).select_from(consulta.subquery())).scalar_one()

    filas = (
        db.execute(
            consulta.order_by(Sena.created_at.desc(), Sena.id.desc())
            .offset((pagina - 1) * tamano)
            .limit(tamano)
        )
        .scalars()
        .all()
    )
    return list(filas), total


def senas_disponibles(db: Session, cliente_id: int) -> list[Sena]:
    """
    Las señas que este cliente puede usar hoy.

    Es lo que el punto de venta ofrece como medio de pago. Solo las que
    tienen saldo: una seña gastada en la lista sería una opción que no
    cubre nada.
    """
    return list(
        db.execute(
            select(Sena)
            .where(
                Sena.cliente_id == cliente_id,
                Sena.activo.is_(True),
                Sena.saldo > 0,
            )
            .order_by(Sena.created_at)
        )
        .scalars()
        .all()
    )


def saldo_total(db: Session, cliente_id: int) -> Decimal:
    """Cuánta plata en señas tiene disponible el cliente, sumando todas."""
    return Decimal(
        db.execute(
            select(func.coalesce(func.sum(Sena.saldo), 0)).where(
                Sena.cliente_id == cliente_id, Sena.activo.is_(True)
            )
        ).scalar_one()
    )


def registrar_sena(
    db: Session,
    autor: Usuario,
    *,
    cliente_id: int,
    monto: Decimal,
    descripcion: str | None = None,
    ip_origen: str | None = None,
) -> Sena:
    """
    Da de alta una seña. El saldo arranca igual al monto: recién entregada,
    no se usó nada.
    """
    cliente = servicio_clientes.obtener_cliente(db, cliente_id)
    if not cliente.activo:
        raise ReglaDeNegocio(
            f"{cliente.nombre} está dado de baja: no se le puede registrar una seña"
        )

    importe = redondear(Decimal(monto))
    if importe <= 0:
        raise ReglaDeNegocio("El monto de la seña tiene que ser mayor a cero")

    sena = Sena(
        cliente_id=cliente_id,
        monto=importe,
        saldo=importe,
        descripcion=normalizar_texto(descripcion),
        usuario_id=autor.id,
        activo=True,
        created_at=ahora_db(),
        updated_at=ahora_db(),
    )
    db.add(sena)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="sena.crear",
        entidad="senas",
        entidad_id=sena.id,
        estado_nuevo=sena,
        ip_origen=ip_origen,
    )
    return sena


def consumir(
    db: Session,
    autor: Usuario,
    sena: Sena,
    monto: Decimal,
    *,
    venta_id: int | None = None,
    ip_origen: str | None = None,
) -> Decimal:
    """
    Descuenta de la seña y devuelve **cuánto pudo cubrir**.

    Si el saldo no alcanza, usa lo que hay y devuelve eso: el resto lo cubre
    el otro medio de pago. Es deliberado que no falle — el caso "la seña
    cubre una parte" es normal, no un error, y hacer que la vendedora
    calcule la diferencia a mano sería pedirle que haga la cuenta que el
    sistema tiene que hacer.

    No hace commit: se ejecuta dentro de la transacción que confirma la
    venta, para que el saldo y el pago se guarden o se descarten juntos.
    """
    if not sena.activo or sena.saldo <= 0:
        raise ReglaDeNegocio("Esa seña ya no tiene saldo disponible")

    pedido = redondear(Decimal(monto))
    if pedido <= 0:
        raise ReglaDeNegocio("El monto a usar de la seña tiene que ser mayor a cero")

    antes = snapshot(sena)
    aplicado = min(pedido, Decimal(sena.saldo))

    sena.saldo = Decimal(sena.saldo) - aplicado
    # Una seña sin saldo deja de ofrecerse. Se apaga acá y no con un job:
    # si dependiera de un proceso aparte, entre el consumo y el barrido
    # quedaría ofreciéndose una seña de $0.
    if sena.saldo <= 0:
        sena.activo = False
    sena.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="sena.consumir",
        entidad="senas",
        entidad_id=sena.id,
        estado_anterior=antes,
        estado_nuevo=sena,
        ip_origen=ip_origen,
    )
    return aplicado


def devolver(
    db: Session,
    autor: Usuario,
    sena: Sena,
    monto: Decimal,
    *,
    ip_origen: str | None = None,
) -> None:
    """
    Le devuelve saldo a la seña. Lo usa la ANULACIÓN de una venta.

    El tope es el monto original: devolverle más de lo que se entregó sería
    inventar plata. Lo ata además un CHECK en la base.
    """
    antes = snapshot(sena)

    devuelto = min(redondear(Decimal(monto)), Decimal(sena.monto) - Decimal(sena.saldo))
    if devuelto <= 0:
        return

    sena.saldo = Decimal(sena.saldo) + devuelto
    # Vuelve a ofrecerse: tiene saldo otra vez.
    if sena.saldo > 0:
        sena.activo = True
    sena.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="sena.devolver",
        entidad="senas",
        entidad_id=sena.id,
        estado_anterior=antes,
        estado_nuevo=sena,
        ip_origen=ip_origen,
    )
