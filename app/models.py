from sqlalchemy import BigInteger, Boolean, CheckConstraint, Computed, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Usuario(Base):
    __tablename__ = "USUARIOS"
    id: Mapped[int] = mapped_column("ID", BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column("NOMBRE", String(120), nullable=False)
    email: Mapped[str] = mapped_column("EMAIL", String(160), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column("PASSWORD_HASH", String(255), nullable=False)
    rol: Mapped[str] = mapped_column("ROL", String(20), nullable=False)
    activo: Mapped[bool] = mapped_column("ACTIVO", Boolean, nullable=False, default=True)
    created_at: Mapped[object] = mapped_column("CREATED_AT", DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[object] = mapped_column("UPDATED_AT", DateTime, server_default=func.current_timestamp())
    __table_args__ = (CheckConstraint("ROL IN ('DUENO','BIBLIOTECARIO','RECLAMADOR')"),)

class Libro(Base):
    __tablename__ = "LIBROS"
    id: Mapped[int] = mapped_column("ID", BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column("CODIGO", String(40), unique=True, nullable=False)
    titulo: Mapped[str] = mapped_column("TITULO", String(250), nullable=False)
    titulo_normalizado: Mapped[str] = mapped_column("TITULO_NORMALIZADO", String(250), unique=True, nullable=False)
    autor: Mapped[str] = mapped_column("AUTOR", String(180), nullable=False)
    anio_impresion: Mapped[int] = mapped_column("ANIO_IMPRESION", Integer, nullable=False)
    estado: Mapped[str] = mapped_column("ESTADO", String(15), nullable=False, default="DISPONIBLE")
    activo: Mapped[bool] = mapped_column("ACTIVO", Boolean, nullable=False, default=True)

class Lector(Base):
    __tablename__ = "LECTORES"
    id: Mapped[int] = mapped_column("ID", BigInteger, primary_key=True)
    dni: Mapped[str] = mapped_column("DNI", String(8), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column("NOMBRE", String(180), nullable=False)
    direccion: Mapped[str] = mapped_column("DIRECCION", String(250), nullable=False)
    telefono: Mapped[str] = mapped_column("TELEFONO", String(20), nullable=False)
    activo: Mapped[bool] = mapped_column("ACTIVO", Boolean, nullable=False, default=True)

class Prestamo(Base):
    __tablename__ = "PRESTAMOS"
    id: Mapped[int] = mapped_column("ID", BigInteger, primary_key=True)
    libro_id: Mapped[int] = mapped_column("LIBRO_ID", ForeignKey("LIBROS.ID"), nullable=False)
    lector_id: Mapped[int] = mapped_column("LECTOR_ID", ForeignKey("LECTORES.ID"), nullable=False)
    fecha_prestamo: Mapped[object] = mapped_column("FECHA_PRESTAMO", Date, nullable=False)
    fecha_vencimiento: Mapped[object] = mapped_column("FECHA_VENCIMIENTO", Date, nullable=False)
    fecha_devolucion: Mapped[object] = mapped_column("FECHA_DEVOLUCION", Date)
    estado: Mapped[str] = mapped_column("ESTADO", String(15), nullable=False, default="ACTIVO")
    dias_atraso: Mapped[int] = mapped_column("DIAS_ATRASO", Integer, nullable=False, default=0)
    multa_monto: Mapped[float] = mapped_column("MULTA_MONTO", Numeric(10,2), nullable=False, default=0)
    multa_estado: Mapped[str] = mapped_column("MULTA_ESTADO", String(15), nullable=False, default="NO_APLICA")
    fecha_pago: Mapped[object] = mapped_column("FECHA_PAGO", Date)
    pago_registrado_por_usuario_id: Mapped[int] = mapped_column("PAGO_REGISTRADO_POR_USUARIO_ID", ForeignKey("USUARIOS.ID"))
    registrado_por_usuario_id: Mapped[int] = mapped_column("REGISTRADO_POR_USUARIO_ID", ForeignKey("USUARIOS.ID"), nullable=False)
    activo_key: Mapped[int] = mapped_column("ACTIVO_KEY", BigInteger, Computed("CASE WHEN ESTADO = 'ACTIVO' THEN LIBRO_ID ELSE NULL END"))
    __table_args__ = (Index("UQ_PRESTAMOS_ACTIVO_KEY", "ACTIVO_KEY", unique=True),)

class OrdenReclamo(Base):
    __tablename__ = "ORDENES_RECLAMO"
    id: Mapped[int] = mapped_column("ID", BigInteger, primary_key=True)
    prestamo_id: Mapped[int] = mapped_column("PRESTAMO_ID", ForeignKey("PRESTAMOS.ID"), nullable=False)
    lector_id: Mapped[int] = mapped_column("LECTOR_ID", ForeignKey("LECTORES.ID"), nullable=False)
    direccion_snapshot: Mapped[str] = mapped_column("DIRECCION_SNAPSHOT", String(250), nullable=False)
    telefono_snapshot: Mapped[str] = mapped_column("TELEFONO_SNAPSHOT", String(20), nullable=False)
    estado: Mapped[str] = mapped_column("ESTADO", String(25), nullable=False, default="PENDIENTE")
    asignado_a_usuario_id: Mapped[int] = mapped_column("ASIGNADO_A_USUARIO_ID", ForeignKey("USUARIOS.ID"))
    fecha_asignacion: Mapped[object] = mapped_column("FECHA_ASIGNACION", DateTime)
    fecha_visita: Mapped[object] = mapped_column("FECHA_VISITA", DateTime)
    resultado: Mapped[str] = mapped_column("RESULTADO", String(40))
    observaciones: Mapped[str] = mapped_column("OBSERVACIONES", Text)
    evidencia_url: Mapped[str] = mapped_column("EVIDENCIA_URL", String(500))
    intentos: Mapped[int] = mapped_column("INTENTOS", Integer, nullable=False, default=0)
    abierta_key: Mapped[int] = mapped_column("ABIERTA_KEY", BigInteger, Computed("CASE WHEN ESTADO IN ('PENDIENTE','ASIGNADA','EN_RUTA') THEN PRESTAMO_ID ELSE NULL END"))
    __table_args__ = (Index("UQ_ORDENES_ABIERTA_KEY", "ABIERTA_KEY", unique=True),)

class Configuracion(Base):
    __tablename__ = "CONFIGURACION"
    clave: Mapped[str] = mapped_column("CLAVE", String(40), primary_key=True)
    valor: Mapped[str] = mapped_column("VALOR", String(160), nullable=False)
    descripcion: Mapped[str] = mapped_column("DESCRIPCION", String(250))
