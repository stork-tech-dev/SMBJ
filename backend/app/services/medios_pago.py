"""
Catálogo de medios de pago y sus planes de cuotas.

Lo administra la Cuenta Maestra desde Configuración. Lo que la vendedora
ve en el cobro sale de acá ya filtrado: **ella no tiene que conocer las
reglas**, solo elegir entre lo que el sistema le ofrece. Esa es la razón de
`planes_disponibles()`, que es la función que importa de este archivo.

Recordatorio de los dos porcentajes, porque confundirlos es el error caro
del módulo: `recargo_cliente` cambia lo que paga el cliente; `costo_medio`
NO — es lo que cobra la terminal y solo aparece en reportes de costo.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import ahora_db, normalizar_texto, redondear, sin_tildes, sin_tildes_sql
from app.models.medio_pago import MedioDePago, PlanCuotas
from app.models.usuario import Usuario
from app.services.descuentos import pct
from app.services.roles import NoEncontrado, ReglaDeNegocio


# ============================================================================
# LO QUE USA EL PUNTO DE VENTA
# ============================================================================


def planes_disponibles(
    db: Session,
    medio_de_pago_id: int,
    monto: Decimal,
    habilita_sin_interes: bool = False,
) -> list[PlanCuotas]:
    """
    Los planes que se le pueden ofrecer a una venta de ese monto.

    El filtro es `monto_minimo <= monto`, y con eso alcanza para el 99% de
    los casos: un plan con mínimo 0 está siempre disponible.

    `habilita_sin_interes` es la excepción, y viene del MOTIVO de descuento
    aplicado ("Empleada", "Cumpleaños"): cuando el motivo lo habilita, los
    planes SIN INTERÉS se ofrecen aunque la venta no llegue al mínimo. Solo
    los sin interés — un motivo de descuento no puede habilitar un plan que
    le sale más caro al cliente.
    """
    medio = obtener_medio(db, medio_de_pago_id)
    if not medio.activo:
        raise ReglaDeNegocio(f"El medio de pago '{medio.nombre}' está inactivo")
    if not medio.soporta_cuotas:
        return []

    total = Decimal(monto)
    return [
        plan
        for plan in medio.planes
        if plan.disponible_para(total)
        or (habilita_sin_interes and plan.activo and plan.sin_interes)
    ]


def calcular_recargo(monto: Decimal, plan: PlanCuotas | None) -> Decimal:
    """
    Lo que suma financiar ESE monto con ese plan.

    Sobre `monto` y no sobre el total de la venta: si el cliente paga mitad
    en efectivo y mitad con tarjeta en cuotas, el interés es de la mitad
    financiada. Calcularlo sobre el total sería cobrarle intereses por la
    plata que puso en efectivo.

    Sin plan —efectivo, débito, un pago— no hay recargo.
    """
    if plan is None:
        return Decimal("0")
    return redondear(Decimal(monto) * Decimal(plan.recargo_cliente) / Decimal("100"))


def medio_de_sena(db: Session) -> MedioDePago | None:
    """
    El medio marcado como seña, si está configurado.

    Se busca por la marca `es_sena` y no por el nombre: comparar contra el
    texto "Seña" haría que renombrarlo desde Configuración rompiera el flujo
    de señas en silencio.
    """
    return db.execute(
        select(MedioDePago).where(
            MedioDePago.es_sena.is_(True), MedioDePago.activo.is_(True)
        )
    ).scalars().first()


# ============================================================================
# ABM DE MEDIOS
# ============================================================================


def obtener_medio(db: Session, medio_id: int) -> MedioDePago:
    medio = db.get(MedioDePago, medio_id)
    if medio is None:
        raise NoEncontrado("Medio de pago inexistente")
    return medio


def listar_medios(
    db: Session,
    nombre: str | None = None,
    activo: bool | None = None,
    soporta_cuotas: bool | None = None,
) -> list[MedioDePago]:
    """El catálogo con los filtros del Principio 5. Tabla chica: sin paginar."""
    consulta = select(MedioDePago)

    if nombre:
        consulta = consulta.where(
            sin_tildes_sql(MedioDePago.nombre).ilike(f"%{sin_tildes(nombre)}%")
        )
    if activo is not None:
        consulta = consulta.where(MedioDePago.activo.is_(activo))
    if soporta_cuotas is not None:
        consulta = consulta.where(MedioDePago.soporta_cuotas.is_(soporta_cuotas))

    return list(db.execute(consulta.order_by(MedioDePago.nombre)).scalars().all())


def _validar_nombre_unico(db: Session, nombre: str, excluir_id: int | None = None) -> None:
    consulta = select(MedioDePago.id).where(
        func.lower(MedioDePago.nombre) == nombre.lower()
    )
    if excluir_id is not None:
        consulta = consulta.where(MedioDePago.id != excluir_id)
    if db.execute(consulta).scalar_one_or_none():
        raise ReglaDeNegocio(f"Ya existe un medio de pago '{nombre}'")


def crear_medio(
    db: Session,
    autor: Usuario,
    *,
    nombre: str,
    soporta_cuotas: bool = False,
    es_sena: bool = False,
    ip_origen: str | None = None,
) -> MedioDePago:
    limpio = normalizar_texto(nombre)
    if not limpio:
        raise ReglaDeNegocio("El nombre del medio de pago es obligatorio")
    _validar_nombre_unico(db, limpio)

    if es_sena:
        _validar_sena_unica(db)
        if soporta_cuotas:
            raise ReglaDeNegocio(
                "Una seña se descuenta de un saldo ya cobrado: no se financia en cuotas"
            )

    medio = MedioDePago(
        nombre=limpio,
        soporta_cuotas=soporta_cuotas,
        es_sena=es_sena,
        activo=True,
        created_at=ahora_db(),
        updated_at=ahora_db(),
    )
    db.add(medio)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="medio_de_pago.crear",
        entidad="medios_de_pago",
        entidad_id=medio.id,
        estado_nuevo=medio,
        ip_origen=ip_origen,
    )
    return medio


def _validar_sena_unica(db: Session, excluir_id: int | None = None) -> None:
    """
    Un solo medio marcado como seña.

    Con dos, `medio_de_sena()` tendría que elegir uno y la elección sería
    arbitraria: la mitad de las señas entrarían por un medio y la otra mitad
    por el otro, y el arqueo de caja las contaría en dos renglones.
    """
    consulta = select(MedioDePago.nombre).where(MedioDePago.es_sena.is_(True))
    if excluir_id is not None:
        consulta = consulta.where(MedioDePago.id != excluir_id)
    otro = db.execute(consulta).scalars().first()
    if otro:
        raise ReglaDeNegocio(
            f"'{otro}' ya es el medio de pago de las señas: solo puede haber uno"
        )


def editar_medio(
    db: Session,
    autor: Usuario,
    medio_id: int,
    *,
    nombre: str | None = None,
    soporta_cuotas: bool | None = None,
    es_sena: bool | None = None,
    activo: bool | None = None,
    ip_origen: str | None = None,
) -> MedioDePago:
    medio = obtener_medio(db, medio_id)
    antes = snapshot(medio)

    if nombre is not None:
        limpio = normalizar_texto(nombre)
        if not limpio:
            raise ReglaDeNegocio("El nombre del medio de pago es obligatorio")
        _validar_nombre_unico(db, limpio, excluir_id=medio.id)
        medio.nombre = limpio

    if es_sena is not None:
        if es_sena:
            _validar_sena_unica(db, excluir_id=medio.id)
        medio.es_sena = es_sena

    if soporta_cuotas is not None:
        # Apagar las cuotas con planes cargados los dejaría invisibles pero
        # vivos: al volver a prenderlas reaparecerían planes que nadie
        # recuerda haber configurado.
        if not soporta_cuotas and medio.planes:
            raise ReglaDeNegocio(
                f"'{medio.nombre}' tiene {len(medio.planes)} plan(es) de cuotas "
                "cargados: hay que desactivarlos antes de sacarle las cuotas"
            )
        medio.soporta_cuotas = soporta_cuotas

    if activo is not None:
        medio.activo = activo

    if medio.es_sena and medio.soporta_cuotas:
        raise ReglaDeNegocio(
            "Una seña se descuenta de un saldo ya cobrado: no se financia en cuotas"
        )

    medio.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="medio_de_pago.editar",
        entidad="medios_de_pago",
        entidad_id=medio.id,
        estado_anterior=antes,
        estado_nuevo=medio,
        ip_origen=ip_origen,
    )
    return medio


def cambiar_estado_medio(
    db: Session, autor: Usuario, medio_id: int, activo: bool, ip_origen: str | None = None
) -> MedioDePago:
    """
    Prende o apaga un medio. No hay borrado: los pagos viejos lo apuntan.
    """
    medio = obtener_medio(db, medio_id)
    antes = snapshot(medio)

    medio.activo = activo
    medio.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="medio_de_pago.activar" if activo else "medio_de_pago.desactivar",
        entidad="medios_de_pago",
        entidad_id=medio.id,
        estado_anterior=antes,
        estado_nuevo=medio,
        ip_origen=ip_origen,
    )
    return medio


# ============================================================================
# ABM DE PLANES
# ============================================================================


def obtener_plan(db: Session, plan_id: int) -> PlanCuotas:
    plan = db.get(PlanCuotas, plan_id)
    if plan is None:
        raise NoEncontrado("Plan de cuotas inexistente")
    return plan


def listar_planes(
    db: Session, medio_de_pago_id: int, activo: bool | None = None
) -> list[PlanCuotas]:
    obtener_medio(db, medio_de_pago_id)
    consulta = select(PlanCuotas).where(PlanCuotas.medio_de_pago_id == medio_de_pago_id)
    if activo is not None:
        consulta = consulta.where(PlanCuotas.activo.is_(activo))
    return list(
        db.execute(consulta.order_by(PlanCuotas.cuotas, PlanCuotas.recargo_cliente))
        .scalars()
        .all()
    )


def crear_plan(
    db: Session,
    autor: Usuario,
    medio_de_pago_id: int,
    *,
    cuotas: int,
    recargo_cliente: Decimal,
    costo_medio: Decimal,
    monto_minimo: Decimal = Decimal("0"),
    ip_origen: str | None = None,
) -> PlanCuotas:
    medio = obtener_medio(db, medio_de_pago_id)
    if not medio.soporta_cuotas:
        raise ReglaDeNegocio(
            f"'{medio.nombre}' no maneja cuotas: hay que habilitárselas antes de "
            "cargarle planes"
        )

    _validar_plan_unico(db, medio_de_pago_id, cuotas, Decimal(recargo_cliente))

    plan = PlanCuotas(
        medio_de_pago_id=medio_de_pago_id,
        cuotas=cuotas,
        recargo_cliente=Decimal(recargo_cliente),
        costo_medio=Decimal(costo_medio),
        monto_minimo=Decimal(monto_minimo),
        activo=True,
        created_at=ahora_db(),
        updated_at=ahora_db(),
    )
    db.add(plan)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="plan_cuotas.crear",
        entidad="planes_cuotas",
        entidad_id=plan.id,
        estado_nuevo=plan,
        ip_origen=ip_origen,
    )
    return plan


def _validar_plan_unico(
    db: Session,
    medio_de_pago_id: int,
    cuotas: int,
    recargo: Decimal,
    excluir_id: int | None = None,
) -> None:
    """
    Dos planes idénticos serían dos opciones iguales en la lista de cobro:
    la vendedora no tendría forma de saber cuál está eligiendo.

    El mismo medio SÍ puede tener "6 cuotas al 0%" y "6 cuotas al 15%" —uno
    promocional y otro no—, por eso la unicidad incluye el recargo.
    """
    consulta = select(PlanCuotas.id).where(
        PlanCuotas.medio_de_pago_id == medio_de_pago_id,
        PlanCuotas.cuotas == cuotas,
        PlanCuotas.recargo_cliente == recargo,
    )
    if excluir_id is not None:
        consulta = consulta.where(PlanCuotas.id != excluir_id)
    if db.execute(consulta).scalar_one_or_none():
        raise ReglaDeNegocio(
            f"Ya hay un plan de {cuotas} cuota(s) al {pct(recargo)}% "
            "para ese medio de pago"
        )


def editar_plan(
    db: Session,
    autor: Usuario,
    plan_id: int,
    *,
    cuotas: int | None = None,
    recargo_cliente: Decimal | None = None,
    costo_medio: Decimal | None = None,
    monto_minimo: Decimal | None = None,
    activo: bool | None = None,
    ip_origen: str | None = None,
) -> PlanCuotas:
    """
    Cambia un plan.

    Las ventas ya cobradas no se tocan: `venta_pagos` guardó su `recargo` en
    pesos, no el porcentaje, así que retocar el plan hoy no reescribe lo que
    alguien pagó el mes pasado.
    """
    plan = obtener_plan(db, plan_id)
    antes = snapshot(plan)

    nuevas_cuotas = cuotas if cuotas is not None else plan.cuotas
    nuevo_recargo = (
        Decimal(recargo_cliente) if recargo_cliente is not None else plan.recargo_cliente
    )
    if cuotas is not None or recargo_cliente is not None:
        _validar_plan_unico(
            db, plan.medio_de_pago_id, nuevas_cuotas, nuevo_recargo, excluir_id=plan.id
        )

    plan.cuotas = nuevas_cuotas
    plan.recargo_cliente = nuevo_recargo
    if costo_medio is not None:
        plan.costo_medio = Decimal(costo_medio)
    if monto_minimo is not None:
        plan.monto_minimo = Decimal(monto_minimo)
    if activo is not None:
        plan.activo = activo

    plan.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="plan_cuotas.editar",
        entidad="planes_cuotas",
        entidad_id=plan.id,
        estado_anterior=antes,
        estado_nuevo=plan,
        ip_origen=ip_origen,
    )
    return plan


def cambiar_estado_plan(
    db: Session, autor: Usuario, plan_id: int, activo: bool, ip_origen: str | None = None
) -> PlanCuotas:
    plan = obtener_plan(db, plan_id)
    antes = snapshot(plan)

    plan.activo = activo
    plan.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="plan_cuotas.activar" if activo else "plan_cuotas.desactivar",
        entidad="planes_cuotas",
        entidad_id=plan.id,
        estado_anterior=antes,
        estado_nuevo=plan,
        ip_origen=ip_origen,
    )
    return plan
