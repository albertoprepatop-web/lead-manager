from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

ACADEMIAS = ['PREPATOP', 'PREPARASECUNDARIA', 'PREPARAANDALUCIA']
ESTADOS = ['nuevo', 'contactado', 'interesado', 'matriculado', 'perdido']
TIPOS_NOTA = ['llamada', 'email', 'reunion', 'otro']
MODALIDADES = ['presencial', 'online', 'mixta']
ESTADOS_PAGO = ['pendiente', 'parcial', 'completo']


class Lead(db.Model):
    __tablename__ = 'leads'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(200))
    academia = db.Column(db.String(50), nullable=False)
    estado = db.Column(db.String(20), nullable=False, default='nuevo')
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
    curso = db.Column(db.String(200), default='')
    modalidad = db.Column(db.String(20), default='presencial')
    estado_pago = db.Column(db.String(20), default='pendiente')
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
            'curso': self.curso,
            'modalidad': self.modalidad,
            'estado_pago': self.estado_pago,
            'notas': self.notas,
            'lead_id': self.lead_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
