"""
Construcción y actualización del árbol de permisos.

Un solo lugar arma el árbol para roles y para usuarios: la única
diferencia es que el de usuario informa además qué viene heredado del rol
y qué es override (Principio 2: DRY).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria
from app.core.permisos import (
    ACCIONES,
    ACCIONES_DE_RECURSO,
    LABEL_MODULO,
    LABEL_RECURSO,
    Modulo,
    Recurso,
    catalogo_accesos,
    recursos_de_modulo,
)
from app.models.permiso import RolPermiso, UsuarioPermiso
from app.models.rol import Rol
from app.models.usuario import Usuario


def _indexar(filas) -> dict[tuple[str, str | None], object]:
    """Indexa filas de permisos por (modulo, recurso) para lookup O(1)."""
    return {(f.modulo, f.recurso): f for f in filas}


def _flags(fila, acciones_validas: tuple[str, ...]) -> dict[str, bool | None]:
    """
    Los cuatro booleanos de una fila de permisos. Las acciones que no
    aplican al recurso devuelven None, y el frontend las pinta como "—".
    """
    resultado: dict[str, bool | None] = {}
    for accion in ACCIONES:
        if accion not in acciones_validas:
            resultado[f"puede_{accion}"] = None
        else:
            resultado[f"puede_{accion}"] = bool(getattr(fila, f"puede_{accion}")) if fila else False
    return resultado


def arbol_de_rol(db: Session, rol_id: int) -> list[dict]:
    """
    Árbol completo de permisos de un rol: todos los módulos del Enum, cada
    uno con sus recursos específicos. Los módulos sin fila en la base
    aparecen con todo en FALSE.
    """
    filas = _indexar(
        db.execute(select(RolPermiso).where(RolPermiso.rol_id == rol_id)).scalars().all()
    )

    arbol = []
    for modulo in Modulo:
        general = filas.get((modulo.value, None))
        nodo: dict[str, Any] = {
            "modulo": modulo.value,
            "label": LABEL_MODULO[modulo],
            **_flags(general, ACCIONES),
            "recursos": [],
        }
        for recurso in recursos_de_modulo(modulo):
            fila = filas.get((modulo.value, recurso.value))
            nodo["recursos"].append(
                {
                    "recurso": recurso.value,
                    "label": LABEL_RECURSO[recurso],
                    **_flags(fila, ACCIONES_DE_RECURSO[recurso]),
                }
            )
        arbol.append(nodo)

    return arbol


def arbol_de_usuario(db: Session, usuario: Usuario) -> list[dict]:
    """
    Árbol de permisos EFECTIVOS de un usuario.

    Por cada nodo devuelve tres cosas:
      - `puede_*`     → permiso efectivo (rol OR override)
      - `heredado_*`  → lo que da el rol (gris, no editable acá)
      - `override_*`  → lo que agrega el override individual (azul)

    Así la pantalla de overrides puede mostrar la herencia sin recalcular
    nada del lado del cliente.
    """
    del_rol = _indexar(
        db.execute(select(RolPermiso).where(RolPermiso.rol_id == usuario.rol_id)).scalars().all()
    )
    overrides = _indexar(
        db.execute(
            select(UsuarioPermiso).where(UsuarioPermiso.usuario_id == usuario.id)
        ).scalars().all()
    )

    def _nodo(clave, acciones_validas) -> dict:
        fila_rol = del_rol.get(clave)
        fila_ovr = overrides.get(clave)
        datos: dict[str, bool | None] = {}
        for accion in ACCIONES:
            if accion not in acciones_validas:
                datos[f"puede_{accion}"] = None
                datos[f"heredado_{accion}"] = None
                datos[f"override_{accion}"] = None
                continue
            heredado = bool(getattr(fila_rol, f"puede_{accion}")) if fila_rol else False
            override = bool(getattr(fila_ovr, f"puede_{accion}")) if fila_ovr else False
            datos[f"heredado_{accion}"] = heredado
            datos[f"override_{accion}"] = override
            # Los overrides solo suman: el efectivo es el OR.
            datos[f"puede_{accion}"] = heredado or override
        return datos

    arbol = []
    for modulo in Modulo:
        nodo = {
            "modulo": modulo.value,
            "label": LABEL_MODULO[modulo],
            **_nodo((modulo.value, None), ACCIONES),
            "recursos": [
                {
                    "recurso": recurso.value,
                    "label": LABEL_RECURSO[recurso],
                    **_nodo((modulo.value, recurso.value), ACCIONES_DE_RECURSO[recurso]),
                }
                for recurso in recursos_de_modulo(modulo)
            ],
        }
        arbol.append(nodo)

    return arbol


def _validar_entrada(modulo: str, recurso: str | None) -> tuple[Modulo, Recurso | None]:
    """Convierte strings de la request en Enums, rechazando lo que no exista."""
    try:
        mod = Modulo(modulo)
    except ValueError as exc:
        raise ValueError(f"Módulo desconocido: {modulo!r}") from exc

    if recurso is None:
        return mod, None

    try:
        rec = Recurso(recurso)
    except ValueError as exc:
        raise ValueError(f"Recurso desconocido: {recurso!r}") from exc

    from app.core.permisos import MODULO_DE_RECURSO

    if MODULO_DE_RECURSO[rec] != mod:
        raise ValueError(f"El recurso {recurso!r} no pertenece al módulo {modulo!r}")

    return mod, rec


def _aplicar(db: Session, modelo, filtro_col, propietario_id: int, entradas: list[dict]) -> None:
    """
    Upsert de filas de permisos. Compartido por roles y usuarios: cambia
    solo el modelo y la columna del propietario.
    """
    existentes = _indexar(
        db.execute(select(modelo).where(filtro_col == propietario_id)).scalars().all()
    )

    for entrada in entradas:
        mod, rec = _validar_entrada(entrada["modulo"], entrada.get("recurso"))
        acciones_validas = ACCIONES if rec is None else ACCIONES_DE_RECURSO[rec]
        clave = (mod.value, rec.value if rec else None)

        fila = existentes.get(clave)
        if fila is None:
            fila = modelo(modulo=mod.value, recurso=rec.value if rec else None)
            setattr(fila, filtro_col.key, propietario_id)
            db.add(fila)
            existentes[clave] = fila

        for accion in ACCIONES:
            # Una acción que no aplica al recurso queda siempre en FALSE,
            # sin importar lo que mande el cliente.
            valor = bool(entrada.get(f"puede_{accion}", False)) if accion in acciones_validas else False
            setattr(fila, f"puede_{accion}", valor)

    db.flush()


def actualizar_permisos_rol(
    db: Session, rol: Rol, entradas: list[dict], autor_id: int, ip_origen: str | None = None
) -> list[dict]:
    """Reemplaza los permisos de un rol y audita el cambio completo."""
    antes = arbol_de_rol(db, rol.id)
    _aplicar(db, RolPermiso, RolPermiso.rol_id, rol.id, entradas)
    despues = arbol_de_rol(db, rol.id)

    registrar_auditoria(
        db,
        usuario_id=autor_id,
        accion="rol.permisos_actualizar",
        entidad="rol_permisos",
        entidad_id=rol.id,
        estado_anterior={"rol": rol.nombre, "permisos": antes},
        estado_nuevo={"rol": rol.nombre, "permisos": despues},
        ip_origen=ip_origen,
    )
    return despues


def actualizar_permisos_usuario(
    db: Session, usuario: Usuario, entradas: list[dict], autor_id: int, ip_origen: str | None = None
) -> list[dict]:
    """Reemplaza los overrides de un usuario y audita el cambio completo."""
    antes = arbol_de_usuario(db, usuario)
    _aplicar(db, UsuarioPermiso, UsuarioPermiso.usuario_id, usuario.id, entradas)
    despues = arbol_de_usuario(db, usuario)

    registrar_auditoria(
        db,
        usuario_id=autor_id,
        accion="usuario.permisos_actualizar",
        entidad="usuario_permisos",
        entidad_id=usuario.id,
        estado_anterior={"usuario": usuario.username, "permisos": antes},
        estado_nuevo={"usuario": usuario.username, "permisos": despues},
        ip_origen=ip_origen,
    )
    return despues


# ============================================================================
# ACCESOS INDIVIDUALES (sección "Accesos permitidos" del formulario)
# ============================================================================


def _fila(db: Session, modelo, columna, propietario_id: int, modulo: str, recurso: str | None):
    """Busca la fila de permisos de un (propietario, módulo, recurso)."""
    return db.execute(
        select(modelo).where(
            columna == propietario_id,
            modelo.modulo == modulo,
            modelo.recurso.is_(None) if recurso is None else modelo.recurso == recurso,
        )
    ).scalar_one_or_none()


def accesos_de_rol(db: Session, rol_id: int) -> list[dict]:
    """
    Catálogo de accesos con lo que otorga el rol.

    Se usa en el alta, cuando el usuario todavía no existe: muestra qué va
    a heredar según el rol elegido.
    """
    filas = _indexar(
        db.execute(select(RolPermiso).where(RolPermiso.rol_id == rol_id)).scalars().all()
    )

    resultado = []
    for acceso in catalogo_accesos():
        clave_fila = (acceso["modulo"].value, acceso["recurso"].value if acceso["recurso"] else None)
        fila = filas.get(clave_fila)
        heredado = bool(getattr(fila, f"puede_{acceso['accion']}")) if fila else False
        resultado.append(
            {
                "clave": acceso["clave"],
                "label": acceso["label"],
                "heredado": heredado,
                "override": False,
                "permitido": heredado,
            }
        )
    return resultado


def accesos_de_usuario(db: Session, usuario: Usuario) -> list[dict]:
    """
    Catálogo de accesos con lo heredado del rol y lo agregado como override.

    `permitido` es el efectivo (heredado OR override); `heredado` marca lo
    que no se puede desmarcar desde acá, porque viene del rol.
    """
    del_rol = _indexar(
        db.execute(select(RolPermiso).where(RolPermiso.rol_id == usuario.rol_id)).scalars().all()
    )
    overrides = _indexar(
        db.execute(
            select(UsuarioPermiso).where(UsuarioPermiso.usuario_id == usuario.id)
        ).scalars().all()
    )

    resultado = []
    for acceso in catalogo_accesos():
        clave_fila = (acceso["modulo"].value, acceso["recurso"].value if acceso["recurso"] else None)
        columna = f"puede_{acceso['accion']}"

        fila_rol = del_rol.get(clave_fila)
        fila_ovr = overrides.get(clave_fila)
        heredado = bool(getattr(fila_rol, columna)) if fila_rol else False
        override = bool(getattr(fila_ovr, columna)) if fila_ovr else False

        resultado.append(
            {
                "clave": acceso["clave"],
                "label": acceso["label"],
                "heredado": heredado,
                "override": override,
                "permitido": heredado or override,
            }
        )
    return resultado


def actualizar_accesos_usuario(
    db: Session,
    usuario: Usuario,
    claves_marcadas: list[str],
    autor_id: int,
    ip_origen: str | None = None,
) -> list[dict]:
    """
    Guarda los accesos marcados como overrides individuales.

    Solo toca la acción concreta de cada acceso: si el usuario tiene otros
    overrides en el mismo módulo (por ejemplo desde la pantalla completa de
    permisos), quedan intactos.

    Lo heredado del rol no se persiste como override: marcar algo que el
    rol ya da no crea una fila, y desmarcarlo tampoco lo quita (el rol
    manda). Es la misma regla aditiva de `resolver_permiso`.
    """
    antes = accesos_de_usuario(db, usuario)
    marcadas = set(claves_marcadas)

    for acceso in catalogo_accesos():
        modulo = acceso["modulo"].value
        recurso = acceso["recurso"].value if acceso["recurso"] else None
        columna = f"puede_{acceso['accion']}"

        fila_rol = _fila(db, RolPermiso, RolPermiso.rol_id, usuario.rol_id, modulo, recurso)
        heredado = bool(getattr(fila_rol, columna)) if fila_rol else False

        # Lo que ya da el rol no necesita override.
        quiere = acceso["clave"] in marcadas and not heredado

        fila = _fila(db, UsuarioPermiso, UsuarioPermiso.usuario_id, usuario.id, modulo, recurso)

        if quiere:
            if fila is None:
                fila = UsuarioPermiso(usuario_id=usuario.id, modulo=modulo, recurso=recurso)
                db.add(fila)
            setattr(fila, columna, True)
        elif fila is not None:
            setattr(fila, columna, False)

    db.flush()
    despues = accesos_de_usuario(db, usuario)

    registrar_auditoria(
        db,
        usuario_id=autor_id,
        accion="usuario.accesos_actualizar",
        entidad="usuario_permisos",
        entidad_id=usuario.id,
        estado_anterior={
            "usuario": usuario.username,
            "accesos": [a["clave"] for a in antes if a["permitido"]],
        },
        estado_nuevo={
            "usuario": usuario.username,
            "accesos": [a["clave"] for a in despues if a["permitido"]],
        },
        ip_origen=ip_origen,
    )
    return despues


def crear_permisos_vacios(db: Session, rol: Rol) -> None:
    """
    Al crear un rol nuevo: una fila por módulo del Enum con todos los
    permisos en FALSE. Sin acceso a nada hasta que alguien lo configure.
    """
    for modulo in Modulo:
        db.add(RolPermiso(rol_id=rol.id, modulo=modulo.value, recurso=None))
    db.flush()
