"""
Auditoría de inventario: contar la mercadería y corregir lo que no coincide.

Flujo simplificado:

  1. `en_curso` — se abre el conteo en una ubicación.
  2. se registran los ítems — por cada código, cuántas unidades hay.
  3. `cerrada` — se finaliza el conteo. Se generan los movimientos que ajustan
     el stock a lo contado.

Es distinta de la tabla `auditoria` del Principio 3: acá se audita la
mercadería, allá las acciones de los usuarios. Cada paso de este flujo, además,
queda registrado en aquella.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.device_scope import DeviceScope
from app.core.utils import ahora_db, normalizar_texto
from app.models.auditoria_inventario import (
    AuditoriaInventario,
    AuditoriaItem,
    EstadoAuditoria,
)
from app.models.producto import Variante
from app.models.stock import TipoMovimiento
from app.models.usuario import Usuario
from app.services import stock as servicio_stock
from app.services.roles import NoEncontrado, ReglaDeNegocio


def obtener(db: Session, auditoria_id: int) -> AuditoriaInventario:
    auditoria = db.execute(
        select(AuditoriaInventario)
        .where(AuditoriaInventario.id == auditoria_id)
        .options(
            joinedload(AuditoriaInventario.punto_de_venta),
            joinedload(AuditoriaInventario.categoria),
            joinedload(AuditoriaInventario.items)
            .joinedload(AuditoriaItem.variante)
            .joinedload(Variante.producto),
        )
    ).unique().scalar_one_or_none()

    if auditoria is None:
        raise NoEncontrado("Auditoría de inventario inexistente")
    return auditoria


def iniciar(
    db: Session,
    autor: Usuario,
    scope: DeviceScope,
    *,
    punto_de_venta_id: int,
    filtro_categoria_id: int | None = None,
    notas: str | None = None,
    ip_origen: str | None = None,
) -> AuditoriaInventario:
    """
    Abre un conteo en una ubicación.

    `filtro_categoria_id` deja contar solo una rama del catálogo: contar una
    categoría entera es realista en una jornada, contar el local completo casi
    nunca lo es. Es informativo —no restringe qué códigos se pueden registrar—
    porque quien cuenta un estante encuentra ahí lo que hay, no lo que el
    filtro esperaba.
    """
    scope.exigir(punto_de_venta_id)
    servicio_stock.obtener_punto(db, punto_de_venta_id)

    if filtro_categoria_id is not None:
        from app.models.categoria import Categoria

        if db.get(Categoria, filtro_categoria_id) is None:
            raise ReglaDeNegocio("La categoría del filtro no existe")

    # Dos conteos abiertos en la misma ubicación se pisarían: el segundo
    # tomaría como "sistema" un número que el primero está por corregir.
    abierta = db.execute(
        select(AuditoriaInventario.id).where(
            AuditoriaInventario.punto_de_venta_id == punto_de_venta_id,
            AuditoriaInventario.estado == EstadoAuditoria.EN_CURSO,
        )
    ).scalar_one_or_none()
    if abierta:
        raise ReglaDeNegocio(
            f"Ya hay una auditoría sin cerrar en esa ubicación (#{abierta}): "
            "hay que cerrarla antes de abrir otra"
        )

    auditoria = AuditoriaInventario(
        punto_de_venta_id=punto_de_venta_id,
        usuario_id=autor.id,
        estado=EstadoAuditoria.EN_CURSO,
        filtro_categoria_id=filtro_categoria_id,
        fecha_inicio=ahora_db(),
        notas=normalizar_texto(notas),
        created_at=ahora_db(),
        updated_at=ahora_db(),
    )
    db.add(auditoria)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="auditoria_inventario.iniciar",
        entidad="auditorias_inventario",
        entidad_id=auditoria.id,
        estado_nuevo=auditoria,
        ip_origen=ip_origen,
    )
    return auditoria


def registrar_items(
    db: Session,
    autor: Usuario,
    scope: DeviceScope,
    auditoria_id: int,
    items: list[dict],
    ip_origen: str | None = None,
) -> AuditoriaInventario:
    """
    Carga lo contado. `items` es [{variante_id, cantidad_contada}].

    `cantidad_sistema` se captura ACÁ, al registrar cada ítem, y no al abrir
    la auditoría. La diferencia importa: si se hubiera congelado al inicio,
    una venta hecha entre la apertura y el conteo de ese estante aparecería
    como un faltante de inventario que nadie podría explicar.

    Volver a registrar la misma variante sobreescribe: contar dos veces un
    estante es normal, y lo que vale es el último conteo.
    """
    auditoria = obtener(db, auditoria_id)
    scope.exigir(auditoria.punto_de_venta_id)

    if auditoria.estado != EstadoAuditoria.EN_CURSO:
        raise ReglaDeNegocio(
            f"La auditoría está {auditoria.estado.value}: solo se cargan ítems "
            "mientras el conteo está en curso"
        )

    existentes = {i.variante_id: i for i in auditoria.items}

    for item in items:
        cantidad = int(item["cantidad_contada"])
        if cantidad < 0:
            raise ReglaDeNegocio("La cantidad contada no puede ser negativa")

        variante_id = item["variante_id"]
        servicio_stock.obtener_variante(db, variante_id)
        en_sistema = servicio_stock.cantidad_en(
            db, variante_id, auditoria.punto_de_venta_id
        )

        fila = existentes.get(variante_id)
        if fila is None:
            fila = AuditoriaItem(
                variante_id=variante_id,
                cantidad_sistema=en_sistema,
                cantidad_contada=cantidad,
            )
            # Se cuelga de la relación en vez de un `db.add` suelto: así la
            # colección en memoria queda al día. Con el add, `auditoria.items`
            # seguía vacía en la misma transacción, y el conteo parecía no
            # tener nada —lo que hacía fallar el cierre y duplicar el ítem al
            # recontarlo—.
            auditoria.items.append(fila)
            existentes[variante_id] = fila
        else:
            # También se refresca el sistema: si se recuenta media hora
            # después, la foto contra la que se compara es la de ahora.
            fila.cantidad_sistema = en_sistema
            fila.cantidad_contada = cantidad

    auditoria.updated_at = ahora_db()
    db.flush()
    return obtener(db, auditoria_id)


def editar_item(
    db: Session,
    autor: Usuario,
    scope: DeviceScope,
    auditoria_id: int,
    item_id: int,
    cantidad_contada: int,
    ip_origen: str | None = None,
) -> AuditoriaInventario:
    """Corrige la cantidad contada de un ítem ya registrado."""
    auditoria = obtener(db, auditoria_id)
    scope.exigir(auditoria.punto_de_venta_id)

    if auditoria.estado != EstadoAuditoria.EN_CURSO:
        raise ReglaDeNegocio(
            f"La auditoría está {auditoria.estado.value}: solo se editan ítems "
            "mientras el conteo está en curso"
        )

    if cantidad_contada < 0:
        raise ReglaDeNegocio("La cantidad contada no puede ser negativa")

    item = next((i for i in auditoria.items if i.id == item_id), None)
    if item is None:
        raise NoEncontrado("Ítem no encontrado en esta auditoría")

    # Se refresca el sistema: si se corrige una hora después, la foto
    # contra la que se compara es la de ahora.
    item.cantidad_sistema = servicio_stock.cantidad_en(
        db, item.variante_id, auditoria.punto_de_venta_id
    )
    item.cantidad_contada = cantidad_contada
    auditoria.updated_at = ahora_db()
    db.flush()
    return obtener(db, auditoria_id)


def eliminar_item(
    db: Session,
    autor: Usuario,
    scope: DeviceScope,
    auditoria_id: int,
    item_id: int,
    ip_origen: str | None = None,
) -> AuditoriaInventario:
    """Quita un ítem del conteo — por ejemplo, cargado por error."""
    auditoria = obtener(db, auditoria_id)
    scope.exigir(auditoria.punto_de_venta_id)

    if auditoria.estado != EstadoAuditoria.EN_CURSO:
        raise ReglaDeNegocio(
            f"La auditoría está {auditoria.estado.value}: solo se eliminan ítems "
            "mientras el conteo está en curso"
        )

    item = next((i for i in auditoria.items if i.id == item_id), None)
    if item is None:
        raise NoEncontrado("Ítem no encontrado en esta auditoría")

    db.delete(item)
    auditoria.updated_at = ahora_db()
    db.flush()
    return obtener(db, auditoria_id)


def finalizar(
    db: Session,
    autor: Usuario,
    scope: DeviceScope,
    auditoria_id: int,
    ip_origen: str | None = None,
) -> AuditoriaInventario:
    """
    Cierra el conteo y ajusta el stock a lo contado.

    Un movimiento `ajuste_auditoria` por cada ítem con diferencia distinta de
    cero. Los que coinciden no generan nada: no hubo nada que corregir, y una
    fila por cada código contado llenaría el historial de ruido.
    """
    auditoria = obtener(db, auditoria_id)
    scope.exigir(auditoria.punto_de_venta_id)

    if auditoria.estado != EstadoAuditoria.EN_CURSO:
        raise ReglaDeNegocio(
            f"La auditoría ya está {auditoria.estado.value}: no se puede volver a cerrar"
        )
    if not auditoria.items:
        raise ReglaDeNegocio("No se contó ningún código: la auditoría está vacía")

    antes = snapshot(auditoria)

    for item in auditoria.items:
        if item.diferencia == 0:
            continue

        # El signo de la diferencia elige la punta: contado de más entra,
        # contado de menos sale. La cantidad viaja siempre positiva.
        kwargs_comunes = dict(
            db=db,
            autor=autor,
            tipo=TipoMovimiento.AJUSTE_AUDITORIA,
            variante_id=item.variante_id,
            cantidad=abs(item.diferencia),
            auditoria_id=auditoria.id,
            notas=(
                f"Ajuste por auditoría #{auditoria.id}: "
                f"sistema {item.cantidad_sistema}, contado {item.cantidad_contada}"
            ),
            ip_origen=ip_origen,
        )
        if item.diferencia > 0:
            servicio_stock.aplicar_movimiento(
                **kwargs_comunes,  # type: ignore[arg-type]
                punto_venta_destino_id=auditoria.punto_de_venta_id,
            )
        else:
            servicio_stock.aplicar_movimiento(
                **kwargs_comunes,  # type: ignore[arg-type]
                punto_venta_origen_id=auditoria.punto_de_venta_id,
            )

    auditoria.estado = EstadoAuditoria.CERRADA
    auditoria.fecha_fin = ahora_db()
    auditoria.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="auditoria_inventario.cerrar",
        entidad="auditorias_inventario",
        entidad_id=auditoria.id,
        estado_anterior=antes,
        estado_nuevo=auditoria,
        ip_origen=ip_origen,
    )
    return obtener(db, auditoria_id)


def listar(
    db: Session,
    scope: DeviceScope,
    estado: str | None = None,
    punto_de_venta_id: int | None = None,
    pagina: int = 1,
    tamano: int = 50,
) -> tuple[list[AuditoriaInventario], int]:
    """Filtros del Principio 5, con el aislamiento por dispositivo aplicado."""
    consulta = select(AuditoriaInventario).options(
        joinedload(AuditoriaInventario.punto_de_venta),
        joinedload(AuditoriaInventario.categoria),
    )

    if scope.restringido:
        if scope.sin_asignacion:
            return [], 0
        consulta = consulta.where(
            AuditoriaInventario.punto_de_venta_id == scope.punto_de_venta_id
        )

    if estado:
        consulta = consulta.where(AuditoriaInventario.estado == EstadoAuditoria(estado))
    if punto_de_venta_id is not None:
        consulta = consulta.where(
            AuditoriaInventario.punto_de_venta_id == punto_de_venta_id
        )

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()

    filas = (
        db.execute(
            consulta.order_by(
                AuditoriaInventario.fecha_inicio.desc(), AuditoriaInventario.id.desc()
            )
            .limit(tamano)
            .offset((pagina - 1) * tamano)
        )
        .unique()
        .scalars()
        .all()
    )
    return list(filas), total
