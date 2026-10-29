"""
Fidelización: categorías por puntos y descuento en el mes del cumpleaños.

- La **categoría** de un cliente es la de mayor `puntos_desde` que alcanzan
  sus puntos **históricos**: todo lo que sumó comprando, sin restar canjes
  (canjear no le baja la categoría). Las anulaciones sí restan: su ajuste
  negativo revierte una acumulación que no ocurrió.
- En el **mes de su cumpleaños**, si su categoría tiene %, ese descuento se
  aplica solo en todas sus compras del mes (`ventas._recalcular`).

Las categorías las edita la Cuenta Maestra en Ajustes, y se reemplazan en
bloque: son una tabla chica que se piensa entera (los rangos dependen unos de
otros), no fila por fila.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria
from app.core.utils import ahora_db, normalizar_texto
from app.models.cliente import Cliente, PuntoCliente, TipoPunto
from app.models.fidelizacion import CategoriaFidelizacion
from app.models.venta import MotivoDescuento
from app.services.roles import ReglaDeNegocio


@dataclass(frozen=True)
class BeneficioCumpleanos:
    categoria: str
    porcentaje: Decimal


def listar_categorias(db: Session) -> list[CategoriaFidelizacion]:
    """De la más baja a la más alta."""
    return list(
        db.execute(select(CategoriaFidelizacion).order_by(CategoriaFidelizacion.puntos_desde))
        .scalars()
        .all()
    )


def puntos_historicos(db: Session, cliente_id: int) -> int:
    """Todo lo sumado por compras (y ajustes), sin restar los canjes."""
    return int(
        db.execute(
            select(func.coalesce(func.sum(PuntoCliente.cantidad), 0)).where(
                PuntoCliente.cliente_id == cliente_id,
                PuntoCliente.tipo != TipoPunto.CANJE,
            )
        ).scalar_one()
    )


def categoria_de(db: Session, cliente_id: int) -> CategoriaFidelizacion | None:
    """La categoría del cliente, o None si no llega a la primera."""
    puntos = puntos_historicos(db, cliente_id)
    return db.execute(
        select(CategoriaFidelizacion)
        .where(CategoriaFidelizacion.puntos_desde <= puntos)
        .order_by(CategoriaFidelizacion.puntos_desde.desc())
        .limit(1)
    ).scalar_one_or_none()


def beneficio_cumpleanos(db: Session, cliente: Cliente | None) -> BeneficioCumpleanos | None:
    """
    El descuento de cumpleaños que le corresponde HOY al cliente, o None.

    Vale todo el mes (no solo el día): el cliente no siempre pasa por el local
    justo ese día. Sin fecha de nacimiento, sin categoría o con 0%, no hay.
    """
    if cliente is None or cliente.fecha_nacimiento is None:
        return None
    if cliente.fecha_nacimiento.month != ahora_db().month:
        return None
    categoria = categoria_de(db, cliente.id)
    if categoria is None or Decimal(categoria.porcentaje_cumpleanos) <= 0:
        return None
    return BeneficioCumpleanos(categoria.nombre, Decimal(categoria.porcentaje_cumpleanos))


def motivo_cumpleanos(db: Session) -> MotivoDescuento | None:
    """El motivo al que apuntan los descuentos automáticos de cumpleaños."""
    return db.execute(
        select(MotivoDescuento).where(MotivoDescuento.es_descuento_cumpleanos.is_(True))
    ).scalar_one_or_none()


def _foto(categorias: list[CategoriaFidelizacion]) -> list[dict]:
    return [
        {"nombre": c.nombre, "puntos_desde": c.puntos_desde,
         "porcentaje_cumpleanos": Decimal(c.porcentaje_cumpleanos)}
        for c in categorias
    ]


def reemplazar_categorias(
    db: Session, autor_id: int, categorias: list[dict], ip_origen: str | None = None
) -> list[CategoriaFidelizacion]:
    """
    Reemplaza todas las categorías por *categorias* (lista de dicts con
    `nombre`, `puntos_desde`, `porcentaje_cumpleanos`) y deja una auditoría
    con la lista anterior y la nueva. Una lista vacía las borra todas.

    Borrar es seguro: la categoría no queda guardada en ningún cliente ni en
    ninguna venta (las ventas guardan el % aplicado en sus ítems).
    """
    limpias = []
    for c in categorias:
        nombre = normalizar_texto(c.get("nombre"))
        if not nombre:
            raise ReglaDeNegocio("Cada categoría necesita un nombre")
        puntos = int(c["puntos_desde"])
        pct = Decimal(str(c["porcentaje_cumpleanos"]))
        if puntos < 0:
            raise ReglaDeNegocio(f"'{nombre}': los puntos no pueden ser negativos")
        if not Decimal("0") <= pct <= Decimal("100"):
            raise ReglaDeNegocio(f"'{nombre}': el descuento tiene que estar entre 0% y 100%")
        limpias.append({"nombre": nombre, "puntos_desde": puntos, "porcentaje_cumpleanos": pct})

    nombres = [c["nombre"].lower() for c in limpias]
    if len(set(nombres)) != len(nombres):
        raise ReglaDeNegocio("Hay dos categorías con el mismo nombre")
    umbrales = [c["puntos_desde"] for c in limpias]
    if len(set(umbrales)) != len(umbrales):
        raise ReglaDeNegocio("Hay dos categorías que arrancan en los mismos puntos")

    anteriores = _foto(listar_categorias(db))
    limpias.sort(key=lambda c: c["puntos_desde"])
    if anteriores == limpias:
        return listar_categorias(db)

    db.execute(delete(CategoriaFidelizacion))
    ahora = ahora_db()
    for c in limpias:
        db.add(CategoriaFidelizacion(**c, created_at=ahora, updated_at=ahora))
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor_id,
        accion="fidelizacion.categorias",
        entidad="categorias_fidelizacion",
        entidad_id=None,
        estado_anterior={"categorias": anteriores},
        estado_nuevo={"categorias": limpias},
        ip_origen=ip_origen,
    )
    return listar_categorias(db)
