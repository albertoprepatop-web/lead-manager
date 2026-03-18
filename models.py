from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

ACADEMIAS = ['PREPATOP', 'PREPARASECUNDARIA', 'PREPARAANDALUCIA']
ESTADOS = ['nuevo', 'contactado', 'no_coge', 'interesado', 'a_espera_de_pago', 'matriculado', 'perdido']
TIPOS_NOTA = ['llamada', 'email', 'reunion', 'otro']
MODALIDADES = ['presencial', 'online', 'mixta']
ESTADOS_PAGO = ['pendiente', 'parcial', 'completo']
METODOS_PAGO = ['efectivo', 'recibo']
SOCIOS = ['Alberto', 'Esteban']


class Lead(db.Model):
    __tablename__ = 'leads'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(200))
    academia = db.Column(db.String(50), nullable=False)
    estado = db.Column(db.String(20), nullable=False, default='nuevo')
    especialidad = db.Column(db.String(100), default='')
    fecha_contacto = db.Column(db.DateTime, nullable=True)
    notas = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    seguimientos = db.relationship('Seguimiento', backref='lead', lazy=True, cascade='all, delete-orphan')
    notas_actividad = db.relationship('NotaActividad', backref='lead', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'telefono': self.telefono,
            'email': self.email,
            'academia': self.academia,
            'estado': self.estado,
            'especialidad': self.especialidad,
            'fecha_contacto': self.fecha_contacto.isoformat() if self.fecha_contacto else None,
            'notas': self.notas,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class Seguimiento(db.Model):
    __tablename__ = 'seguimientos'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False)
    fecha = db.Column(db.DateTime, nullable=False)
    nota = db.Column(db.Text, default='')
    completado = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'lead_id': self.lead_id,
            'lead_nombre': self.lead.nombre if self.lead else None,
            'lead_academia': self.lead.academia if self.lead else None,
            'fecha': self.fecha.isoformat() if self.fecha else None,
            'nota': self.nota,
            'completado': self.completado,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class NotaActividad(db.Model):
    __tablename__ = 'notas_actividad'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False)
    contenido = db.Column(db.Text, nullable=False)
    tipo = db.Column(db.String(20), default='otro')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'lead_id': self.lead_id,
            'contenido': self.contenido,
            'tipo': self.tipo,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Alumno(db.Model):
    __tablename__ = 'alumnos'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(200))
    academia = db.Column(db.String(50), nullable=False)
    fecha_matricula = db.Column(db.DateTime, default=datetime.utcnow)
    especialidad = db.Column(db.String(100), default='')
    curso = db.Column(db.String(200), default='')
    modalidad = db.Column(db.String(20), default='presencial')
    estado_pago = db.Column(db.String(20), default='pendiente')
    cuota = db.Column(db.Float, default=0)
    notas = db.Column(db.Text, default='')
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    lead = db.relationship('Lead', backref='alumno', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'telefono': self.telefono,
            'email': self.email,
            'academia': self.academia,
            'fecha_matricula': self.fecha_matricula.isoformat() if self.fecha_matricula else None,
            'especialidad': self.especialidad,
            'curso': self.curso,
            'modalidad': self.modalidad,
            'estado_pago': self.estado_pago,
            'cuota': self.cuota or 0,
            'notas': self.notas,
            'lead_id': self.lead_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class Pago(db.Model):
    __tablename__ = 'pagos'

    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey('alumnos.id'), nullable=False)
    mes = db.Column(db.String(7), nullable=False)  # "2026-04"
    metodo = db.Column(db.String(20), nullable=False)  # efectivo / recibo
    cantidad = db.Column(db.Float, nullable=False, default=0)
    recogido_por = db.Column(db.String(50), nullable=True)  # Alberto / Esteban (solo efectivo)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    alumno = db.relationship('Alumno', backref='pagos', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'alumno_id': self.alumno_id,
            'alumno_nombre': self.alumno.nombre if self.alumno else None,
            'alumno_academia': self.alumno.academia if self.alumno else None,
            'mes': self.mes,
            'metodo': self.metodo,
            'cantidad': self.cantidad,
            'recogido_por': self.recogido_por,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class MesActivo(db.Model):
    __tablename__ = 'meses_activos'

    id = db.Column(db.Integer, primary_key=True)
    mes = db.Column(db.String(7), nullable=False)  # "2026-04"
    academia = db.Column(db.String(50), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'mes': self.mes,
            'academia': self.academia,
        }
