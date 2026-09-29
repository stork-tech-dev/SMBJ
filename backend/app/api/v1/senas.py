"""
Endpoints de señas.

Registrar una seña es cobrar: se hace desde el celular de un local, con
turno abierto, y la plata entra a esa caja con el medio elegido. Por eso el
alta pide el permiso de vender y no el de administrar clientes —la hace la
vendedora en el mostrador—, y el cliente se puede crear en el mismo paso.

No hay endpoint para editar el saldo, y es deliberado: el saldo solo baja
usándolo en una venta (`ventas.confirmar`) y solo sube al anularla. Un saldo
editable a mano sería plata que aparece y desaparece sin que ninguna venta
lo explique.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.device_deps import get_active_device
from app.core.device_scope import DeviceScope, get_device_scope
from app.core.permisos import Modulo, requiere_permiso
from app.core.utils import ip_de_request
from app.models.venta import Venta, VentaPago
from app.schemas.comunes import RespuestaPaginada
from app.schemas.senas import (
    MedioParaSena,
    SenaCrear,
    SenaDetalle,
    SenaResponse,
    UsoDeSena,
)
from app.services import medios_pago as servicio_medios
from app.services import senas as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/senas", tags=["senas"])


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=RespuestaPaginada[SenaResponse], summary="Listado")
def listar(
    cliente_id: int | None = Query(default=None),
    activo: bool | None = Query(default=None),
    con_saldo: bool | None = Query(
        default=None, description="True: solo con saldo. False: solo las gastadas"
    ),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CLIENTES, "ver")),
):
    filas, total = servicio.listar_senas(
        db,
        cliente_id=cliente_id,
        activo=activo,
        con_saldo=con_saldo,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[SenaResponse](
        total=total, pagina=pagina, tamano=tamano, resultados=filas  # type: ignore[arg-type]
    )


@router.get(
    "/medios-de-pago",
    response_model=list[MedioParaSena],
    summary="Medios con los que se puede dejar una seña",
)
def medios_de_pago(
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    """
    Los activos menos la seña misma. Declarado antes de `/{sena_id}` para
    que no se lea como un id.
    """
    return servicio_medios.medios_para_cobro_directo(db)


@router.get("/{sena_id}", response_model=SenaDetalle, summary="Detalle con sus usos")
def detalle(
    sena_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CLIENTES, "ver")),
):
    """
    La seña y en qué ventas se usó.

    El historial sale de `venta_pagos`, que es donde quedó cada aplicación:
    por eso el saldo puede persistirse sin perder el detalle de cómo llegó a
    ser el que es.
    """
    try:
        sena = servicio.obtener_sena(db, sena_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc

    usos = db.execute(
        select(VentaPago.monto, Venta.id, Venta.numero, Venta.created_at)
        .join(Venta, Venta.id == VentaPago.venta_id)
        .where(VentaPago.sena_id == sena_id)
        .order_by(Venta.created_at)
    ).all()

    respuesta = SenaDetalle.model_validate(sena)
    respuesta.usos = [
        UsoDeSena(venta_id=venta_id, numero=numero, monto=Decimal(monto), fecha=fecha)
        for monto, venta_id, numero, fecha in usos
    ]
    return respuesta


@router.post(
    "",
    response_model=SenaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una seña",
)
def registrar(
    datos: SenaCrear,
    request: Request,
    db: Session = Depends(get_db),
    dispositivo=Depends(get_active_device),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    """
    El saldo arranca igual al monto: recién entregada, no se usó nada. Vence
    a los días de vigencia configurados, y el cliente no puede tener otra
    vigente.
    """
    scope.exigir(dispositivo.punto_de_venta_id)
    try:
        sena = servicio.registrar_sena(
            db,
            autor,
            punto_de_venta_id=dispositivo.punto_de_venta_id,
            medio_de_pago_id=datos.medio_de_pago_id,
            monto=datos.monto,
            cliente_id=datos.cliente_id,
            cliente_nuevo=(
                datos.cliente_nuevo.model_dump() if datos.cliente_nuevo else None
            ),
            descripcion=datos.descripcion,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return sena
