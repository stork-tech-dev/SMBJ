"""
Retiros de efectivo con código personal (sesión 09).

Quien retira se identifica con un código numérico de 4 dígitos, distinto de
su contraseña: así la credencial real nunca se tipea en el celular del local.
El código solo dice QUIÉN retiró; no da acceso al sistema.

El tope del retiro es el efectivo esperado de la caja en ese momento, con la
misma cuenta que usa el arqueo (`arqueo.efectivo_esperado`): si fueran dos
cuentas, el retiro podría dejar la caja en un número que el cierre no ve.
"""

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.auditoria import registrar_auditoria
from app.core.permisos import ROL_VENDEDOR
from app.core.utils import ahora_db, redondear
from app.models.turno import RetiroEfectivo
from app.models.usuario import Usuario
from app.services.arqueo import efectivo_esperado
from app.services.auth import hash_password, verificar_password
from app.services.roles import NoEncontrado, ReglaDeNegocio
from app.services.turnos import turno_para_operar

_FORMATO_CODIGO = re.compile(r"^\d{4}$")

# Mismo mensaje para "no existe" y "es de otro": no se revela si un código
# está en uso.
MENSAJE_CODIGO_INVALIDO = "Código de autorización incorrecto"


class CodigoInvalido(Exception):
    """El código de retiro no corresponde a ningún usuario habilitado."""


# ============================================================================
# ADMINISTRACIÓN DE CÓDIGOS (Cuenta Maestra)
# ============================================================================


def _usuario_del_codigo(db: Session, codigo: str, excluir_id: int | None = None) -> Usuario | None:
    """
    El usuario activo y habilitado cuyo código coincide, o None.

    Hay que verificar con bcrypt uno por uno —el hash lleva sal, no se puede
    buscar por igualdad—, pero son pocos usuarios con código (hoy, los Dueños).
    """
    consulta = select(Usuario).where(
        Usuario.activo.is_(True),
        Usuario.puede_retirar.is_(True),
        Usuario.codigo_retiro_hash.is_not(None),
    )
    if excluir_id is not None:
        consulta = consulta.where(Usuario.id != excluir_id)
    for usuario in db.execute(consulta).unique().scalars():
        if verificar_password(codigo, usuario.codigo_retiro_hash):
            return usuario
    return None


def asignar_codigo(
    db: Session, autor: Usuario, usuario_id: int, codigo: str, ip_origen: str | None = None
) -> Usuario:
    """
    Asigna o cambia el código de retiro de un usuario y lo habilita a retirar.

    No se habilita a un Vendedor: la vendedora carga el retiro, pero no puede
    ser quien lo autoriza con su propio código.
    """
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        raise NoEncontrado("Usuario inexistente")
    if usuario.rol is not None and usuario.rol.nombre == ROL_VENDEDOR:
        raise ReglaDeNegocio("No se puede habilitar a retirar efectivo a un usuario con rol vendedor")
    if not _FORMATO_CODIGO.match(codigo or ""):
        raise ReglaDeNegocio("El código de retiro son 4 dígitos")
    # Dos usuarios con el mismo código harían imposible saber quién retiró.
    if _usuario_del_codigo(db, codigo, excluir_id=usuario.id) is not None:
        raise ReglaDeNegocio("Ese código ya lo usa otra persona: elegí otro")

    usuario.codigo_retiro_hash = hash_password(codigo)
    usuario.puede_retirar = True
    usuario.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="usuario.codigo_retiro_asignar",
        entidad="usuarios",
        entidad_id=usuario.id,
        estado_nuevo={"username": usuario.username, "puede_retirar": True},
        ip_origen=ip_origen,
    )
    return usuario


def revocar_codigo(
    db: Session, autor: Usuario, usuario_id: int, ip_origen: str | None = None
) -> Usuario:
    """Quita el código y la habilitación para retirar."""
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        raise NoEncontrado("Usuario inexistente")

    usuario.codigo_retiro_hash = None
    usuario.puede_retirar = False
    usuario.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="usuario.codigo_retiro_revocar",
        entidad="usuarios",
        entidad_id=usuario.id,
        estado_nuevo={"username": usuario.username, "puede_retirar": False},
        ip_origen=ip_origen,
    )
    return usuario


# ============================================================================
# RETIROS
# ============================================================================


def efectivo_disponible(db: Session, punto_de_venta_id: int) -> tuple[int, Decimal]:
    """(turno_id, efectivo disponible) del turno abierto del local."""
    turno = turno_para_operar(punto_de_venta_id, db)
    return turno.id, efectivo_esperado(turno.id, db)


def registrar_retiro(
    db: Session,
    autor: Usuario,
    *,
    punto_de_venta_id: int,
    monto: Decimal,
    codigo: str,
    ip_origen: str | None = None,
) -> RetiroEfectivo:
    """
    Registra un retiro de efectivo en el turno abierto del local.

    El monto se valida ANTES que el código: si no hay plata, no tiene sentido
    pedirle a nadie que se identifique.

    Un código incorrecto lanza `CodigoInvalido` después de dejar el intento
    en la auditoría; quien llama tiene que commitear igual (mismo criterio
    que el login fallido), porque el registro del intento no puede depender
    de que la operación salga bien.
    """
    turno = turno_para_operar(punto_de_venta_id, db)

    monto = redondear(Decimal(monto))
    if monto <= 0:
        raise ReglaDeNegocio("El monto del retiro tiene que ser mayor a cero")
    disponible = efectivo_esperado(turno.id, db)
    if monto > disponible:
        raise ReglaDeNegocio(
            f"El monto supera el efectivo disponible en caja (${disponible})"
        )

    usuario = _usuario_del_codigo(db, codigo or "") if _FORMATO_CODIGO.match(codigo or "") else None
    if usuario is None:
        registrar_auditoria(
            db,
            usuario_id=autor.id,
            accion="caja.retiro_efectivo_fallido",
            entidad="retiros_efectivo",
            estado_nuevo={
                "turno_id": turno.id,
                "punto_de_venta_id": punto_de_venta_id,
                "monto": monto,
            },
            ip_origen=ip_origen,
        )
        raise CodigoInvalido(MENSAJE_CODIGO_INVALIDO)

    retiro = RetiroEfectivo(
        turno_id=turno.id,
        punto_de_venta_id=punto_de_venta_id,
        usuario_id=usuario.id,
        monto=monto,
        registrado_por_id=autor.id,
        timestamp=ahora_db(),
    )
    db.add(retiro)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="caja.retiro_efectivo",
        entidad="retiros_efectivo",
        entidad_id=retiro.id,
        estado_nuevo=retiro,
        ip_origen=ip_origen,
    )
    return retiro


def listar_retiros(
    db: Session,
    *,
    turno_id: int | None = None,
    punto_de_venta_id: int | None = None,
    usuario_id: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    pagina: int = 1,
    tamano: int = 10,
) -> tuple[list[RetiroEfectivo], int]:
    """Historial con los filtros del Principio 5, más reciente primero."""
    consulta = select(RetiroEfectivo).options(
        joinedload(RetiroEfectivo.usuario),
        joinedload(RetiroEfectivo.registrado_por),
        joinedload(RetiroEfectivo.punto_de_venta),
    )
    if turno_id is not None:
        consulta = consulta.where(RetiroEfectivo.turno_id == turno_id)
    if punto_de_venta_id is not None:
        consulta = consulta.where(RetiroEfectivo.punto_de_venta_id == punto_de_venta_id)
    if usuario_id is not None:
        consulta = consulta.where(RetiroEfectivo.usuario_id == usuario_id)
    if desde is not None:
        consulta = consulta.where(func.date(RetiroEfectivo.timestamp) >= desde)
    if hasta is not None:
        consulta = consulta.where(func.date(RetiroEfectivo.timestamp) <= hasta)

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()
    filas = (
        db.execute(
            consulta.order_by(RetiroEfectivo.timestamp.desc(), RetiroEfectivo.id.desc())
            .limit(tamano)
            .offset((pagina - 1) * tamano)
        )
        .unique()
        .scalars()
        .all()
    )
    return list(filas), total
