"""
Modelos del módulo de etiquetas: rollos, impresoras Zebra y diseños.

Todo se guarda en MILÍMETROS: el motor (`app/core/etiquetas/motor.py`) los
pasa a puntos con los dpi de la ficha de cada impresora. Así, cambiar de
impresora (por ejemplo a una de 300 dpi) es cargar una ficha nueva, no
reescribir las medidas.
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class GiroFormato(str, enum.Enum):
    # El giro es parte del ROLLO, no del diseño: con el giro equivocado, en la
    # colita lo impreso cae sobre la colita en vez de sobre la parte imprimible.
    NORMAL = "normal"
    INVERTIDO = "invertido"


class EtiquetaImpresora(Base):
    """
    Ficha de una impresora Zebra. Ningún nombre de impresora está escrito en
    el código: todo sale de acá.
    """

    __tablename__ = "etiqueta_impresoras"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    # Nombre con el que la ve Zebra Browser Print en la PC (ej.
    # `\\STELLA\ZDesigner GC420t (EPL)`). Se la busca por este nombre, nunca
    # por la "predeterminada": cada rollo va a la Zebra que lo tiene puesto.
    browser_print: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    dpi: Mapped[int] = mapped_column(Integer, nullable=False, server_default="203")
    # Cada impresora y cada rollo quedan un poco corridos: se corrige acá.
    corrimiento_x_mm: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, server_default="0")
    corrimiento_y_mm: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, server_default="0")
    # `~SD` de ZPL. Cambia con la cinta: muy clara no se lee, muy oscura se empasta.
    oscuridad: Mapped[int] = mapped_column(Integer, nullable=False, server_default="14")
    # `^PR` de ZPL. Más lenta imprime más nítido en etiquetas chicas.
    velocidad: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")
    # Quitar una impresora la desactiva: la auditoría sigue apuntando a ella.
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("corrimiento_x_mm BETWEEN -10 AND 10", name="ck_etq_impresora_corrimiento_x"),
        CheckConstraint("corrimiento_y_mm BETWEEN -10 AND 10", name="ck_etq_impresora_corrimiento_y"),
        CheckConstraint("oscuridad BETWEEN 0 AND 30", name="ck_etq_impresora_oscuridad"),
        CheckConstraint("velocidad BETWEEN 2 AND 6", name="ck_etq_impresora_velocidad"),
    )

    def __repr__(self) -> str:
        return f"<EtiquetaImpresora {self.id} {self.nombre}>"


class EtiquetaFormato(Base):
    """
    Un rollo de etiquetas (múltiple 32×10, colita 66×11). Vienen sembrados
    por la migración; agregar un rollo nuevo es cargar sus medidas.
    """

    __tablename__ = "etiqueta_formatos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    clave: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    ancho_rollo_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    columnas: Mapped[int] = mapped_column(Integer, nullable=False)
    # Distancia entre el comienzo de una etiqueta y el de la siguiente de la fila.
    paso_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    ancho_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    alto_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    # Parte que se imprime, desde la punta. En la colita, el resto es la cola.
    zona_desde_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    zona_hasta_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    # Dónde se dobla, dentro de la zona imprimible. NULL = no se dobla.
    doblez_mm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    giro: Mapped[GiroFormato] = mapped_column(
        Enum(GiroFormato, name="giro_formato_etiqueta", values_callable=lambda e: [i.value for i in e]),
        nullable=False,
    )
    # La impresora que imprime este rollo. Al imprimir no se elige impresora:
    # así no se manda una colita a la Zebra que tiene puesto el rollo de la
    # múltiple. NULL = no se puede imprimir este rollo.
    impresora_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("etiqueta_impresoras.id", ondelete="RESTRICT")
    )
    impresora: Mapped[EtiquetaImpresora | None] = relationship()

    __table_args__ = (
        CheckConstraint("columnas > 0", name="ck_etq_formato_columnas"),
        CheckConstraint("zona_hasta_mm > zona_desde_mm", name="ck_etq_formato_zona"),
    )

    def __repr__(self) -> str:
        return f"<EtiquetaFormato {self.clave}>"


class EtiquetaDiseno(Base):
    """
    Diseño de etiqueta: parámetros en mm (tamaño del código cuadrado,
    letras, topes, márgenes) validados con `ParametrosDiseno`. Se editan sin
    programar; cada cambio guarda la versión anterior en
    `etiqueta_disenos_versiones`.
    """

    __tablename__ = "etiqueta_disenos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    parametros: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # Borrar = archivar: lo impreso con un diseño viejo se puede reimprimir.
    archivado: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    actualizado_por_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    versiones: Mapped[list["EtiquetaDisenoVersion"]] = relationship(
        back_populates="diseno", order_by="EtiquetaDisenoVersion.version.desc()"
    )

    def __repr__(self) -> str:
        return f"<EtiquetaDiseno {self.id} v{self.version}>"


class EtiquetaDisenoVersion(Base):
    """
    Una versión guardada de un diseño (solo inserción): quién la guardó y
    cuándo. Volver a una versión es una edición nueva con esos parámetros,
    así nunca se pierde historia.
    """

    __tablename__ = "etiqueta_disenos_versiones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    diseno_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("etiqueta_disenos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    parametros: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # NULL = la cargó el sistema (la semilla del diseño aprobado).
    usuario_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    diseno: Mapped[EtiquetaDiseno] = relationship(back_populates="versiones")
    usuario: Mapped["Usuario | None"] = relationship()  # noqa: F821  # type: ignore[name-defined]

    __table_args__ = (UniqueConstraint("diseno_id", "version", name="uq_etq_diseno_version"),)
