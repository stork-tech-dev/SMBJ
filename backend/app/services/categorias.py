"""
Reglas de negocio del árbol de categorías.

El prompt define la estructura pero no las reglas que la mantienen sana.
Las que se aplican acá:

- El nivel se DERIVA del padre, nunca lo elige el usuario: una raíz es
  nivel 1, y cualquier otra es `padre.nivel + 1`.
- No se puede pasar del nivel 5, ni al crear ni al mover una rama.
- No se borra una categoría con hijos ni con productos colgando.
- Mover una rama arrastra el nivel de toda su descendencia.

Todas valen para cualquier consumidor de la API, no solo para la pantalla.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import ahora_db, normalizar_texto
from app.models.categoria import NIVEL_MAXIMO, Categoria
from app.models.usuario import Usuario
from app.services.roles import NoEncontrado, ReglaDeNegocio


def obtener_categoria(db: Session, categoria_id: int) -> Categoria:
    categoria = db.get(Categoria, categoria_id)
    if categoria is None:
        raise NoEncontrado("Categoría inexistente")
    return categoria


# ============================================================================
# CONSULTAS
# ============================================================================


def listar_categorias(
    db: Session,
    nombre: str | None = None,
    nivel: int | None = None,
    parent_id: int | None = None,
) -> list[Categoria]:
    """
    Listado plano con los filtros del Principio 5, resueltos en el backend.

    El árbol lo arma `arbol()`; esto sirve para búsquedas y selectores.
    """
    consulta = select(Categoria)

    if nombre:
        consulta = consulta.where(Categoria.nombre.ilike(f"%{nombre}%"))
    if nivel is not None:
        consulta = consulta.where(Categoria.nivel == nivel)
    if parent_id is not None:
        consulta = consulta.where(Categoria.parent_id == parent_id)

    return list(
        db.execute(consulta.order_by(Categoria.nivel, Categoria.orden, Categoria.nombre))
        .scalars()
        .all()
    )


def arbol(db: Session) -> list[dict]:
    """
    Árbol completo, listo para la pantalla.

    Trae TODAS las categorías en una sola query y arma la jerarquía en
    memoria: el árbol tiene 5 niveles como máximo y unos pocos cientos de
    nodos, así que una consulta recursiva o un lazy load por nodo serían
    más caros y más frágiles que esto.
    """
    todas = list(
        db.execute(
            select(Categoria).order_by(Categoria.nivel, Categoria.orden, Categoria.nombre)
        )
        .scalars()
        .all()
    )

    nodos: dict[int, dict] = {
        c.id: {
            "id": c.id,
            "nombre": c.nombre,
            "nivel": c.nivel,
            "parent_id": c.parent_id,
            "orden": c.orden,
            "hijos": [],
        }
        for c in todas
    }

    raices: list[dict] = []
    for c in todas:
        if c.parent_id is None:
            raices.append(nodos[c.id])
        else:
            # El padre siempre existe y ya fue procesado: el orden por
            # nivel garantiza que se ve antes que sus hijos.
            nodos[c.parent_id]["hijos"].append(nodos[c.id])

    return raices


def _descendientes(db: Session, categoria: Categoria) -> list[Categoria]:
    """Toda la descendencia de un nodo, en anchura."""
    encontrados: list[Categoria] = []
    frontera = [categoria.id]

    while frontera:
        hijos = list(
            db.execute(select(Categoria).where(Categoria.parent_id.in_(frontera)))
            .scalars()
            .all()
        )
        if not hijos:
            break
        encontrados.extend(hijos)
        frontera = [h.id for h in hijos]

    return encontrados


def rama_de_ids(db: Session, categoria_id: int) -> list[int]:
    """
    La categoría más toda su descendencia, como lista de ids.

    Sirve para filtrar "todo lo que cuelga de acá": elegir Zapatillas tiene
    que traer también lo de Deportivas y Urbanas. Sin esto, filtrar por un
    nodo intermedio devolvería casi siempre cero resultados, porque los
    productos suelen colgar de las hojas.

    Si la categoría no existe devuelve solo el id recibido, para que el
    filtro no traiga de más ante un id inválido.
    """
    categoria = db.get(Categoria, categoria_id)
    if categoria is None:
        return [categoria_id]

    return [categoria.id] + [d.id for d in _descendientes(db, categoria)]


# ============================================================================
# VALIDACIONES DEL ÁRBOL
# ============================================================================


def _nivel_para(db: Session, parent_id: int | None) -> int:
    """
    Nivel que le corresponde a una categoría según su padre.

    El nivel no es un dato que elija el usuario: si lo fuera se podría
    crear un nivel 3 colgando de un nivel 1 y el árbol quedaría mintiendo.
    """
    if parent_id is None:
        return 1

    padre = obtener_categoria(db, parent_id)
    nivel = padre.nivel + 1

    if nivel > NIVEL_MAXIMO:
        raise ReglaDeNegocio(
            f"No se puede anidar más de {NIVEL_MAXIMO} niveles: "
            f"'{padre.nombre}' ya está en el nivel {padre.nivel}"
        )
    return nivel


def _validar_nombre_unico_entre_hermanos(
    db: Session, nombre: str, parent_id: int | None, excluir_id: int | None = None
) -> None:
    """
    Dos hermanos no pueden llamarse igual. Entre ramas distintas sí: puede
    haber "Verano" bajo Calzado y bajo Ropa.

    La base también lo garantiza con un índice único; esto existe para
    devolver un mensaje entendible en vez de un error de integridad.
    """
    consulta = select(Categoria.id).where(
        Categoria.nombre.ilike(nombre),
        Categoria.parent_id.is_(parent_id) if parent_id is None else Categoria.parent_id == parent_id,
    )
    if excluir_id is not None:
        consulta = consulta.where(Categoria.id != excluir_id)

    if db.execute(consulta).scalar_one_or_none():
        ubicacion = "en el primer nivel" if parent_id is None else "dentro de esa categoría"
        raise ReglaDeNegocio(f"Ya existe una categoría '{nombre}' {ubicacion}")


def _profundidad_de_rama(db: Session, categoria: Categoria) -> int:
    """Cuántos niveles cuelgan del nodo, contándolo a él como 1."""
    descendientes = _descendientes(db, categoria)
    if not descendientes:
        return 1
    return max(d.nivel for d in descendientes) - categoria.nivel + 1


# ============================================================================
# ABM
# ============================================================================


def crear_categoria(
    db: Session,
    autor: Usuario,
    nombre: str,
    parent_id: int | None = None,
    orden: int = 0,
    ip_origen: str | None = None,
) -> Categoria:
    """Alta de categoría. El nivel se deriva del padre, no se recibe."""
    nombre_limpio = normalizar_texto(nombre)
    if not nombre_limpio:
        raise ReglaDeNegocio("El nombre es obligatorio")

    nivel = _nivel_para(db, parent_id)
    _validar_nombre_unico_entre_hermanos(db, nombre_limpio, parent_id)

    categoria = Categoria(
        nombre=nombre_limpio,
        nivel=nivel,
        parent_id=parent_id,
        orden=orden,
        created_at=ahora_db(),
        updated_at=ahora_db(),
    )
    db.add(categoria)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="categoria.crear",
        entidad="categorias",
        entidad_id=categoria.id,
        estado_nuevo=categoria,
        ip_origen=ip_origen,
    )
    return categoria


def editar_categoria(
    db: Session,
    autor: Usuario,
    categoria_id: int,
    nombre: str | None = None,
    orden: int | None = None,
    ip_origen: str | None = None,
) -> Categoria:
    """
    Edita nombre y orden. Mover de padre es otra operación (`mover`):
    cambia el nivel de toda la rama y merece su propia validación.
    """
    categoria = obtener_categoria(db, categoria_id)
    antes = snapshot(categoria)

    if nombre is not None:
        nombre_limpio = normalizar_texto(nombre)
        if not nombre_limpio:
            raise ReglaDeNegocio("El nombre es obligatorio")
        _validar_nombre_unico_entre_hermanos(
            db, nombre_limpio, categoria.parent_id, excluir_id=categoria.id
        )
        categoria.nombre = nombre_limpio

    if orden is not None:
        categoria.orden = orden

    categoria.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="categoria.editar",
        entidad="categorias",
        entidad_id=categoria.id,
        estado_anterior=antes,
        estado_nuevo=categoria,
        ip_origen=ip_origen,
    )
    return categoria


def mover_categoria(
    db: Session,
    autor: Usuario,
    categoria_id: int,
    nuevo_parent_id: int | None,
    ip_origen: str | None = None,
) -> Categoria:
    """
    Cambia una rama de lugar y reacomoda el nivel de toda su descendencia.

    Es la operación más delicada del módulo: hay tres formas de dejar el
    árbol roto y las tres se validan acá.
    """
    categoria = obtener_categoria(db, categoria_id)
    antes = snapshot(categoria)

    if nuevo_parent_id == categoria.id:
        raise ReglaDeNegocio("Una categoría no puede ser su propio padre")

    descendientes = _descendientes(db, categoria)

    # Colgar una rama de su propia descendencia la desconectaría del árbol:
    # el ciclo resultante ya no sería alcanzable desde ninguna raíz.
    if nuevo_parent_id is not None and nuevo_parent_id in {d.id for d in descendientes}:
        raise ReglaDeNegocio("No se puede mover una categoría dentro de su propia rama")

    nivel_nuevo = _nivel_para(db, nuevo_parent_id)

    # La rama entera tiene que entrar bajo el nivel máximo, no solo su raíz.
    profundidad = _profundidad_de_rama(db, categoria)
    if nivel_nuevo + profundidad - 1 > NIVEL_MAXIMO:
        raise ReglaDeNegocio(
            f"La rama tiene {profundidad} niveles y no entra a partir del nivel "
            f"{nivel_nuevo}: se pasaría del máximo de {NIVEL_MAXIMO}"
        )

    _validar_nombre_unico_entre_hermanos(
        db, categoria.nombre, nuevo_parent_id, excluir_id=categoria.id
    )

    # El desplazamiento se aplica a toda la descendencia de una vez.
    desplazamiento = nivel_nuevo - categoria.nivel
    categoria.parent_id = nuevo_parent_id
    categoria.nivel = nivel_nuevo
    categoria.updated_at = ahora_db()

    for d in descendientes:
        d.nivel += desplazamiento
        d.updated_at = ahora_db()

    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="categoria.mover",
        entidad="categorias",
        entidad_id=categoria.id,
        estado_anterior=antes,
        estado_nuevo=categoria,
        ip_origen=ip_origen,
    )
    return categoria


def eliminar_categoria(
    db: Session, autor: Usuario, categoria_id: int, ip_origen: str | None = None
) -> None:
    """
    Baja definitiva. Solo procede si el nodo está vacío: sin hijos y sin
    productos. Las categorías no tienen baja lógica porque no son un dato
    histórico —no quedan referenciadas en comprobantes—, a diferencia de
    proveedores o usuarios, que se desactivan.
    """
    categoria = obtener_categoria(db, categoria_id)

    hijos = db.execute(
        select(func.count(Categoria.id)).where(Categoria.parent_id == categoria.id)
    ).scalar_one()
    if hijos:
        raise ReglaDeNegocio(
            f"La categoría tiene {hijos} subcategoría(s): hay que moverlas o "
            "eliminarlas primero"
        )

    if _tiene_productos(db, categoria.id):
        raise ReglaDeNegocio("La categoría tiene productos asociados")

    antes = snapshot(categoria)
    db.delete(categoria)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="categoria.eliminar",
        entidad="categorias",
        entidad_id=categoria_id,
        estado_anterior=antes,
        ip_origen=ip_origen,
    )


def _tiene_productos(db: Session, categoria_id: int) -> bool:
    """
    Si hay productos colgando de la categoría.

    La tabla `productos` llega en la fase 2 de este módulo. Hasta entonces
    la consulta no se puede hacer y la respuesta es "no hay". Se pregunta
    por la tabla en vez de importar el modelo para que esto siga
    funcionando igual antes y después de que exista.
    """
    from sqlalchemy import inspect, text

    if not inspect(db.get_bind()).has_table("productos"):
        return False

    total = db.execute(
        text("SELECT count(*) FROM productos WHERE categoria_id = :id"),
        {"id": categoria_id},
    ).scalar_one()
    return bool(total)
