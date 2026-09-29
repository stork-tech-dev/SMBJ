"""
Señas: plata que el cliente ya entregó y todavía no gastó.

Dos reglas la definen:

- **No existe seña sin cliente.** Es plata de alguien, y al cobrar hay que
  saber a quién ofrecérsela.
- **El saldo solo baja usándola en una venta.** No hay endpoint para
  editarlo a mano: se descuenta desde `consumir()`, dentro de la misma
  transacción que confirma la venta. Un saldo editable sería plata que
  aparece y desaparece sin que ninguna venta lo explique.

- **Se usa entera.** En la venta donde se aplica, la seña se consume toda:
  cubre hasta el total de la venta y, si la compra es por menos, la
  diferencia se pierde. La anulación de esa venta la devuelve completa.

Además:

- **Vence.** A los `dias_vigencia_sena` días del alta (60 por defecto) deja
  de ofrecerse; la fecha queda fija en `vence_el`. No hay proceso que las
  "apague": el filtro de vigencia alcanza, y una seña vencida con saldo
  sigue explicando lo que el cliente perdió.
- **Entra a la caja.** La plata se recibe con un medio de pago, en el turno
  abierto del local, y el arqueo de ese turno la suma a ese medio.
- **Una a la vez.** Un cliente con una seña vigente no puede dejar otra.

Cuando el saldo llega a cero la seña se apaga sola. No se borra: las ventas
donde se usó la apuntan.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import ahora_db, normalizar_texto, redondear
from app.models.sena import Sena
from app.models.usuario import Usuario
from app.services import clientes as servicio_clientes
from app.services import configuracion as servicio_configuracion
from app.services import medios_pago as servicio_medios
from app.services.roles import NoEncontrado, ReglaDeNegocio
from app.services.turnos import turno_para_operar


def hoy() -> date:
    """La fecha del negocio (UTC-03), la misma contra la que vence una seña."""
    return ahora_db().date()


def es_vigente(sena: Sena, dia: date | None = None) -> bool:
    """Si la seña se puede usar hoy: activa, con saldo y sin vencer."""
    return bool(sena.activo) and Decimal(sena.saldo) > 0 and sena.vence_el >= (dia or hoy())


def _vigentes(cliente_id: int):
    """
    Condición única de "seña usable": la comparten el cobro, el saldo y el
    control de "una a la vez", así no pueden discrepar entre sí.
    """
    return (
        Sena.cliente_id == cliente_id,
        Sena.activo.is_(True),
        Sena.saldo > 0,
        Sena.vence_el >= hoy(),
    )


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
    Las señas que este cliente puede usar hoy: con saldo y sin vencer.

    Normalmente es una sola —no se registra otra mientras haya una vigente—,
    pero la anulación de una venta puede devolverle saldo a una vieja cuando
    el cliente ya dejó otra. Por eso es lista y el cobro las usa todas.
    """
    return list(
        db.execute(
            select(Sena).where(*_vigentes(cliente_id)).order_by(Sena.vence_el, Sena.id)
        )
        .scalars()
        .all()
    )


def saldo_total(db: Session, cliente_id: int) -> Decimal:
    """Cuánta plata en señas vigentes tiene el cliente, sumando todas."""
    return Decimal(
        db.execute(
            select(func.coalesce(func.sum(Sena.saldo), 0)).where(*_vigentes(cliente_id))
        ).scalar_one()
    )


def registrar_sena(
    db: Session,
    autor: Usuario,
    *,
    punto_de_venta_id: int,
    medio_de_pago_id: int,
    monto: Decimal,
    cliente_id: int | None = None,
    cliente_nuevo: dict | None = None,
    descripcion: str | None = None,
    ip_origen: str | None = None,
) -> Sena:
    """
    Da de alta una seña. El saldo arranca igual al monto: recién entregada,
    no se usó nada.

    El cliente es uno existente (`cliente_id`) o se crea en el momento
    (`cliente_nuevo`: nombre, dni, teléfono…), en la misma transacción: si
    la seña no se puede registrar, tampoco queda un cliente suelto.

    La plata entra al turno abierto del local con el medio elegido: sin
    turno no hay caja donde recibirla, y se rechaza igual que un cobro de
    joyero (`turno_para_operar`).
    """
    if (cliente_id is None) == (cliente_nuevo is None):
        raise ReglaDeNegocio("Indicá un cliente existente o los datos de uno nuevo")

    turno = turno_para_operar(punto_de_venta_id, db)

    medio = servicio_medios.obtener_medio(db, medio_de_pago_id)
    if not medio.activo:
        raise ReglaDeNegocio(f"El medio de pago '{medio.nombre}' está inactivo")
    if medio.es_sena:
        raise ReglaDeNegocio("Una seña no se puede pagar con otra seña")

    importe = redondear(Decimal(monto))
    if importe <= 0:
        raise ReglaDeNegocio("El monto de la seña tiene que ser mayor a cero")

    if cliente_nuevo is not None:
        cliente = servicio_clientes.crear_cliente(
            db, autor, ip_origen=ip_origen, **cliente_nuevo
        )
    else:
        cliente = servicio_clientes.obtener_cliente(db, cliente_id)
        if not cliente.activo:
            raise ReglaDeNegocio(
                f"{cliente.nombre} está dado de baja: no se le puede registrar una seña"
            )
        vigente = senas_disponibles(db, cliente.id)
        if vigente:
            raise ReglaDeNegocio(
                f"{cliente.nombre} ya tiene una seña de ${vigente[0].saldo} que vence el "
                f"{vigente[0].vence_el:%d/%m/%Y}: tiene que usarla antes de dejar otra"
            )

    dia = hoy()
    sena = Sena(
        cliente_id=cliente.id,
        monto=importe,
        saldo=importe,
        descripcion=normalizar_texto(descripcion),
        usuario_id=autor.id,
        medio_de_pago_id=medio.id,
        turno_id=turno.id,
        punto_de_venta_id=punto_de_venta_id,
        vence_el=dia + timedelta(days=servicio_configuracion.dias_vigencia_sena(db)),
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


def repartir_en_venta(
    db: Session, cliente_id: int, a_cobrar: Decimal
) -> list[tuple[Sena, Decimal, Decimal]]:
    """
    Cómo cubren las señas vigentes del cliente una venta de *a_cobrar*.

    Devuelve `(seña, aplicado, consumido)` por seña: `aplicado` es lo que
    paga de la venta y `consumido` lo que se descuenta de su saldo —siempre
    el saldo entero (uso total)—. Si las señas suman más que la venta, la
    diferencia se pierde: la última aplica solo lo que falta y se consume
    igual. Las que ya no hacen falta porque la venta quedó cubierta no se
    tocan.

    No modifica nada: lo que se descuenta de verdad lo hace `consumir()` al
    confirmar la venta.
    """
    reparto = []
    falta = redondear(Decimal(a_cobrar))
    for sena in senas_disponibles(db, cliente_id):
        if falta <= 0:
            break
        saldo = Decimal(sena.saldo)
        aplicado = min(saldo, falta)
        reparto.append((sena, aplicado, saldo))
        falta -= aplicado
    return reparto


def consumir(
    db: Session,
    autor: Usuario,
    sena: Sena,
    *,
    venta_id: int | None = None,
    ip_origen: str | None = None,
) -> Decimal:
    """
    Consume la seña ENTERA y devuelve cuánto se descontó.

    Uso total: aunque la venta la cubra solo en parte, el saldo queda en 0 y
    lo que sobra se pierde. Eso lo decide el negocio, no el sistema: la seña
    es un adelanto de una compra, no una billetera.

    Se revalida la vigencia acá aunque se haya validado al registrar los
    pagos: entre una cosa y la otra puede haber pasado la medianoche.

    No hace commit: se ejecuta dentro de la transacción que confirma la
    venta, para que el saldo y el pago se guarden o se descarten juntos.
    """
    if not es_vigente(sena):
        raise ReglaDeNegocio("Esa seña ya no está disponible: se usó o venció")

    antes = snapshot(sena)
    consumido = Decimal(sena.saldo)

    sena.saldo = Decimal("0")
    # Una seña sin saldo deja de ofrecerse. Se apaga acá y no con un job:
    # si dependiera de un proceso aparte, entre el consumo y el barrido
    # quedaría ofreciéndose una seña de $0.
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
        estado_nuevo={**snapshot(sena), "venta_id": venta_id},
        ip_origen=ip_origen,
    )
    return consumido


def devolver(
    db: Session,
    autor: Usuario,
    sena: Sena,
    monto: Decimal,
    *,
    ip_origen: str | None = None,
) -> None:
    """
    Le devuelve saldo a la seña. Lo usa la ANULACIÓN de una venta, con lo
    que se había consumido (incluida la parte que se perdió): anular la venta
    deja la seña como estaba. Si en el medio venció, vuelve con saldo pero no
    se ofrece —el vencimiento corre desde el alta, no desde la venta—.

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
