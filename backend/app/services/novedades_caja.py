"""
Novedades de caja (sesión 09).

Ajustan el efectivo esperado del arqueo cuando hay una diferencia legítima
(un gasto pagado desde la caja, una falla del sistema). El control es el
responsable: cada novedad lleva un autorizador elegido de la lista de
usuarios con `es_autorizador` —la misma lista que autoriza los cambios por
falla—.

El tipo (entrada / salida) lo fija el concepto; quien carga la novedad no lo
elige. Se copia a la novedad para que un cambio posterior del concepto no
altere lo ya registrado.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import ahora_db, normalizar_texto, redondear, sin_tildes, sin_tildes_sql
from app.models.operaciones_caja import ConceptoNovedad, NovedadCaja, TipoNovedad
from app.models.usuario import Usuario
from app.services.roles import NoEncontrado, ReglaDeNegocio
from app.services.turnos import turno_para_operar

# ============================================================================
# CONCEPTOS (Cuenta Maestra)
# ============================================================================


def obtener_concepto(db: Session, concepto_id: int) -> ConceptoNovedad:
    concepto = db.get(ConceptoNovedad, concepto_id)
    if concepto is None:
        raise NoEncontrado("Concepto de novedad inexistente")
    return concepto


def listar_conceptos(
    db: Session,
    nombre: str | None = None,
    tipo: str | None = None,
    activo: bool | None = None,
) -> list[ConceptoNovedad]:
    """Tabla chica: sin paginar, orden alfabético."""
    consulta = select(ConceptoNovedad)
    if nombre:
        consulta = consulta.where(
            sin_tildes_sql(ConceptoNovedad.nombre).ilike(f"%{sin_tildes(nombre)}%")
        )
    if tipo:
        consulta = consulta.where(ConceptoNovedad.tipo == TipoNovedad(tipo))
    if activo is not None:
        consulta = consulta.where(ConceptoNovedad.activo.is_(activo))
    return list(db.execute(consulta.order_by(ConceptoNovedad.nombre)).scalars().all())


def _validar_nombre(db: Session, nombre: str, excluir_id: int | None = None) -> str:
    limpio = normalizar_texto(nombre)
    if not limpio:
        raise ReglaDeNegocio("El nombre del concepto es obligatorio")
    consulta = select(ConceptoNovedad.id).where(
        func.lower(ConceptoNovedad.nombre) == limpio.lower()
    )
    if excluir_id is not None:
        consulta = consulta.where(ConceptoNovedad.id != excluir_id)
    if db.execute(consulta).first():
        raise ReglaDeNegocio(f"Ya existe un concepto '{limpio}'")
    return limpio


def crear_concepto(
    db: Session, autor: Usuario, nombre: str, tipo: str, ip_origen: str | None = None
) -> ConceptoNovedad:
    ahora = ahora_db()
    concepto = ConceptoNovedad(
        nombre=_validar_nombre(db, nombre),
        tipo=TipoNovedad(tipo),
        activo=True,
        created_at=ahora,
        updated_at=ahora,
    )
    db.add(concepto)
    db.flush()
    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="concepto_novedad.crear",
        entidad="conceptos_novedad",
        entidad_id=concepto.id,
        estado_nuevo=concepto,
        ip_origen=ip_origen,
    )
    return concepto


def editar_concepto(
    db: Session,
    autor: Usuario,
    concepto_id: int,
    nombre: str | None = None,
    tipo: str | None = None,
    ip_origen: str | None = None,
) -> ConceptoNovedad:
    """
    Cambiar el tipo de un concepto no altera las novedades ya registradas:
    cada una conserva el tipo que tenía al cargarse.
    """
    concepto = obtener_concepto(db, concepto_id)
    antes = snapshot(concepto)
    if nombre is not None:
        concepto.nombre = _validar_nombre(db, nombre, excluir_id=concepto.id)
    if tipo is not None:
        concepto.tipo = TipoNovedad(tipo)
    concepto.updated_at = ahora_db()
    db.flush()
    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="concepto_novedad.editar",
        entidad="conceptos_novedad",
        entidad_id=concepto.id,
        estado_anterior=antes,
        estado_nuevo=concepto,
        ip_origen=ip_origen,
    )
    return concepto


def cambiar_estado_concepto(
    db: Session, autor: Usuario, concepto_id: int, activo: bool, ip_origen: str | None = None
) -> ConceptoNovedad:
    concepto = obtener_concepto(db, concepto_id)
    antes = snapshot(concepto)
    concepto.activo = activo
    concepto.updated_at = ahora_db()
    db.flush()
    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="concepto_novedad.activar" if activo else "concepto_novedad.desactivar",
        entidad="conceptos_novedad",
        entidad_id=concepto.id,
        estado_anterior=antes,
        estado_nuevo=concepto,
        ip_origen=ip_origen,
    )
    return concepto


# ============================================================================
# NOVEDADES
# ============================================================================


def registrar_novedad(
    db: Session,
    autor: Usuario,
    *,
    punto_de_venta_id: int,
    concepto_id: int,
    monto: Decimal,
    autorizador_id: int,
    notas: str | None = None,
    ip_origen: str | None = None,
) -> NovedadCaja:
    turno = turno_para_operar(punto_de_venta_id, db)

    concepto = obtener_concepto(db, concepto_id)
    if not concepto.activo:
        raise ReglaDeNegocio(f"El concepto '{concepto.nombre}' está inactivo")

    importe = redondear(Decimal(monto))
    if importe <= 0:
        raise ReglaDeNegocio("El monto de la novedad tiene que ser mayor a cero")

    autorizador = db.get(Usuario, autorizador_id)
    if autorizador is None or not autorizador.activo or not autorizador.es_autorizador:
        raise ReglaDeNegocio("El autorizador elegido no está habilitado para autorizar")

    novedad = NovedadCaja(
        turno_id=turno.id,
        punto_de_venta_id=punto_de_venta_id,
        concepto_id=concepto.id,
        monto=importe,
        tipo=concepto.tipo,
        autorizador_id=autorizador.id,
        registrado_por_id=autor.id,
        timestamp=ahora_db(),
        notas=normalizar_texto(notas),
    )
    db.add(novedad)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="caja.novedad_registrada",
        entidad="novedades_caja",
        entidad_id=novedad.id,
        estado_nuevo={
            "concepto": concepto.nombre,
            "tipo": concepto.tipo.value,
            "monto": importe,
            "autorizador": autorizador.nombre,
            "autorizador_id": autorizador.id,
            "turno_id": turno.id,
        },
        ip_origen=ip_origen,
    )
    return novedad


def listar_novedades(
    db: Session,
    *,
    turno_id: int | None = None,
    punto_de_venta_id: int | None = None,
    concepto_id: int | None = None,
    autorizador_id: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    pagina: int = 1,
    tamano: int = 10,
) -> tuple[list[NovedadCaja], int]:
    consulta = select(NovedadCaja).options(
        joinedload(NovedadCaja.concepto),
        joinedload(NovedadCaja.autorizador),
        joinedload(NovedadCaja.registrado_por),
        joinedload(NovedadCaja.punto_de_venta),
    )
    if turno_id is not None:
        consulta = consulta.where(NovedadCaja.turno_id == turno_id)
    if punto_de_venta_id is not None:
        consulta = consulta.where(NovedadCaja.punto_de_venta_id == punto_de_venta_id)
    if concepto_id is not None:
        consulta = consulta.where(NovedadCaja.concepto_id == concepto_id)
    if autorizador_id is not None:
        consulta = consulta.where(NovedadCaja.autorizador_id == autorizador_id)
    if desde is not None:
        consulta = consulta.where(func.date(NovedadCaja.timestamp) >= desde)
    if hasta is not None:
        consulta = consulta.where(func.date(NovedadCaja.timestamp) <= hasta)

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()
    filas = (
        db.execute(
            consulta.order_by(NovedadCaja.timestamp.desc(), NovedadCaja.id.desc())
            .limit(tamano)
            .offset((pagina - 1) * tamano)
        )
        .unique()
        .scalars()
        .all()
    )
    return list(filas), total
