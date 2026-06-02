import csv
import io
import json
import os
import functools
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request, Response, session, redirect, url_for
from flask_cors import CORS
from models import db, Lead, Seguimiento, NotaActividad, Alumno, Pago, MesActivo, RegistroEfectivo, ACADEMIAS, ESTADOS, SOCIOS
from database import seed_database, ESPECIALIDADES

app = Flask(__name__)  # v2 economic tabs
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')

# Database: PostgreSQL in production (Railway), SQLite locally
db_url = os.environ.get('DATABASE_URL', 'sqlite:///leads.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

ACCESS_CODE = os.environ.get('ACCESS_CODE', 'admin')

CORS(app)
db.init_app(app)

@app.after_request
def add_no_cache(response):
    if 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

with app.app_context():
    db.create_all()
    seed_database()
    # Auto-migrate: add missing columns
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)
        columns = [c['name'] for c in inspector.get_columns('alumnos')]
        if 'cuota' not in columns:
            db.session.execute(text('ALTER TABLE alumnos ADD COLUMN cuota FLOAT DEFAULT 0'))
        if 'grupo' not in columns:
            db.session.execute(text("ALTER TABLE alumnos ADD COLUMN grupo VARCHAR(100) DEFAULT ''"))
        if 'metodo_pago' not in columns:
            db.session.execute(text("ALTER TABLE alumnos ADD COLUMN metodo_pago VARCHAR(20) DEFAULT 'efectivo'"))
        # Leads columns
        lead_columns = [c['name'] for c in inspector.get_columns('leads')]
        if 'fecha_cita' not in lead_columns:
            db.session.execute(text('ALTER TABLE leads ADD COLUMN fecha_cita TIMESTAMP'))
        if 'hora_preferida' not in lead_columns:
            db.session.execute(text("ALTER TABLE leads ADD COLUMN hora_preferida VARCHAR(50) DEFAULT ''"))
        db.session.commit()
    except Exception:
        db.session.rollback()


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'No autorizado'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ── Auth ───────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        code = request.form.get('code', '')
        if code == ACCESS_CODE:
            session['authenticated'] = True
            return redirect(url_for('index'))
        error = 'Codigo incorrecto'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/api/especialidades')
@login_required
def get_especialidades():
    return jsonify(ESPECIALIDADES)


# ── Pages ──────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    return render_template('index.html')


# ── Dashboard ──────────────────────────────────────────────────────────────

@app.route('/api/dashboard')
@login_required
def dashboard():
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    total = Lead.query.count()
    nuevos_semana = Lead.query.filter(Lead.created_at >= week_ago).count()
    total_alumnos = Alumno.query.filter(db.or_(Alumno.grupo == '', Alumno.grupo.is_(None))).count()
    seguimientos_pendientes = Seguimiento.query.filter(
        Seguimiento.completado == False,
        Seguimiento.fecha <= now
    ).count()

    por_academia = {}
    for academia in ACADEMIAS:
        leads_academia = Lead.query.filter_by(academia=academia)
        total_ac = leads_academia.count()
        por_estado = {}
        for estado in ESTADOS:
            por_estado[estado] = leads_academia.filter_by(estado=estado).count()
        alumnos_ac = Alumno.query.filter_by(academia=academia).filter(db.or_(Alumno.grupo == '', Alumno.grupo.is_(None))).count()
        por_academia[academia] = {
            'total': total_ac,
            'por_estado': por_estado,
            'alumnos': alumnos_ac,
        }

    # Leads por semana (desde 1 marzo 2026)
    por_semana = []
    inicio_marzo = datetime(2026, 3, 1)
    # Find the Monday of the week containing March 1
    start_week = inicio_marzo - timedelta(days=inicio_marzo.weekday())
    current_week = start_week
    while current_week <= now:
        week_end = current_week + timedelta(days=7)
        count = Lead.query.filter(
            Lead.created_at >= current_week,
            Lead.created_at < week_end
        ).count()
        label = f"{current_week.strftime('%d/%m')} - {(week_end - timedelta(days=1)).strftime('%d/%m')}"
        por_semana.append({
            'semana': label,
            'count': count,
        })
        current_week = week_end

    # Seguimientos proximos
    seguimientos_proximos = Seguimiento.query.filter(
        Seguimiento.completado == False
    ).order_by(Seguimiento.fecha.asc()).limit(10).all()

    # Alumnos por mes (ultimos 6 meses) - only 26/27 students (exclude PREPATOP 25/26)
    alumnos_por_mes = []
    for i in range(5, -1, -1):
        mes_inicio = (now.replace(day=1) - timedelta(days=30 * i)).replace(day=1)
        if i > 0:
            mes_fin = (now.replace(day=1) - timedelta(days=30 * (i - 1))).replace(day=1)
        else:
            mes_fin = now + timedelta(days=1)
        count = Alumno.query.filter(
            Alumno.fecha_matricula >= mes_inicio,
            Alumno.fecha_matricula < mes_fin,
            db.or_(Alumno.grupo == '', Alumno.grupo.is_(None))
        ).count()
        alumnos_por_mes.append({
            'mes': mes_inicio.strftime('%b %Y'),
            'count': count,
        })

    # Alumnos por especialidad y academia
    por_especialidad = {}
    for academia_name, especialidades_list in ESPECIALIDADES.items():
        por_especialidad[academia_name] = {}
        for esp in especialidades_list:
            count = Alumno.query.filter_by(academia=academia_name, especialidad=esp).count()
            por_especialidad[academia_name][esp] = count

    # PREPATOP 25/26 stats
    alumnos_2526 = Alumno.query.filter(
        Alumno.academia == 'PREPATOP',
        Alumno.grupo != '',
        Alumno.grupo.isnot(None)
    )
    total_alumnos_2526 = alumnos_2526.count()
    pagos_efectivo_2526 = db.session.query(db.func.sum(Pago.cantidad)).join(Alumno).filter(
        Alumno.academia == 'PREPATOP',
        Alumno.grupo != '',
        Alumno.grupo.isnot(None),
        Pago.metodo == 'efectivo',
    ).scalar() or 0
    pagos_recibo_2526 = db.session.query(db.func.sum(Pago.cantidad)).join(Alumno).filter(
        Alumno.academia == 'PREPATOP',
        Alumno.grupo != '',
        Alumno.grupo.isnot(None),
        Pago.metodo == 'recibo',
    ).scalar() or 0

    # Citas agendadas (hemos_quedado con fecha_cita)
    citas = Lead.query.filter(
        Lead.estado == 'hemos_quedado',
        Lead.fecha_cita.isnot(None),
    ).order_by(Lead.fecha_cita.asc()).all()

    return jsonify({
        'total_leads': total,
        'nuevos_semana': nuevos_semana,
        'total_alumnos': total_alumnos,
        'seguimientos_pendientes': seguimientos_pendientes,
        'por_academia': por_academia,
        'por_semana': por_semana,
        'alumnos_por_mes': alumnos_por_mes,
        'por_especialidad': por_especialidad,
        'seguimientos_proximos': [s.to_dict() for s in seguimientos_proximos],
        'citas': [{'id': c.id, 'nombre': c.nombre, 'academia': c.academia, 'fecha_cita': c.fecha_cita.isoformat(), 'telefono': c.telefono} for c in citas],
        'prepatop_2526': {
            'alumnos': total_alumnos_2526,
            'efectivo': pagos_efectivo_2526,
            'recibo': pagos_recibo_2526,
        },
    })


# ── Leads CRUD ─────────────────────────────────────────────────────────────

@app.route('/api/leads')
@login_required
def list_leads():
    query = Lead.query

    academia = request.args.get('academia')
    if academia:
        query = query.filter_by(academia=academia)

    estado = request.args.get('estado')
    if estado:
        query = query.filter_by(estado=estado)

    busqueda = request.args.get('busqueda')
    if busqueda:
        pattern = f'%{busqueda}%'
        query = query.filter(
            db.or_(
                Lead.nombre.ilike(pattern),
                Lead.email.ilike(pattern),
                Lead.telefono.ilike(pattern),
            )
        )

    fecha_desde = request.args.get('fecha_desde')
    if fecha_desde:
        query = query.filter(Lead.created_at >= datetime.fromisoformat(fecha_desde))

    fecha_hasta = request.args.get('fecha_hasta')
    if fecha_hasta:
        query = query.filter(Lead.created_at <= datetime.fromisoformat(fecha_hasta))

    order = request.args.get('order', 'desc')
    if order == 'asc':
        query = query.order_by(Lead.created_at.asc())
    else:
        query = query.order_by(Lead.created_at.desc())

    leads = query.all()
    result = []
    for l in leads:
        d = l.to_dict()
        d['llamadas'] = NotaActividad.query.filter_by(lead_id=l.id, tipo='llamada').count()
        result.append(d)
    return jsonify(result)


@app.route('/api/leads', methods=['POST'])
@login_required
def create_lead():
    data = request.get_json()
    if not data.get('nombre') or not data.get('academia'):
        return jsonify({'error': 'Nombre y academia son obligatorios'}), 400
    if data['academia'] not in ACADEMIAS:
        return jsonify({'error': f'Academia no valida. Opciones: {ACADEMIAS}'}), 400

    lead = Lead(
        nombre=data['nombre'],
        telefono=data.get('telefono', ''),
        email=data.get('email', ''),
        academia=data['academia'],
        estado=data.get('estado', 'nuevo'),
        especialidad=data.get('especialidad', ''),
        hora_preferida=data.get('hora_preferida', ''),
        notas=data.get('notas', ''),
    )
    db.session.add(lead)
    db.session.commit()
    return jsonify(lead.to_dict()), 201


@app.route('/api/leads/<int:lead_id>')
@login_required
def get_lead(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    data = lead.to_dict()
    data['seguimientos'] = [s.to_dict() for s in lead.seguimientos]
    data['notas_actividad'] = [n.to_dict() for n in sorted(lead.notas_actividad, key=lambda x: x.created_at, reverse=True)]
    return jsonify(data)


@app.route('/api/leads/<int:lead_id>', methods=['PUT'])
@login_required
def update_lead(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    data = request.get_json()

    if 'nombre' in data:
        lead.nombre = data['nombre']
    if 'telefono' in data:
        lead.telefono = data['telefono']
    if 'email' in data:
        lead.email = data['email']
    if 'academia' in data:
        if data['academia'] not in ACADEMIAS:
            return jsonify({'error': f'Academia no valida'}), 400
        lead.academia = data['academia']
    if 'especialidad' in data:
        lead.especialidad = data['especialidad']
    if 'estado' in data:
        if data['estado'] not in ESTADOS:
            return jsonify({'error': f'Estado no valido'}), 400
        old_estado = lead.estado
        new_estado = data['estado']
        lead.estado = new_estado

        # Auto-create follow-up when contacted (remind in 3 days)
        if new_estado == 'contactado' and old_estado != 'contactado':
            # Set fecha_contacto to now if not explicitly provided
            if data.get('fecha_contacto'):
                lead.fecha_contacto = datetime.fromisoformat(data['fecha_contacto'])
            else:
                lead.fecha_contacto = datetime.utcnow()
            seg = Seguimiento(
                lead_id=lead.id,
                fecha=datetime.utcnow() + timedelta(days=3),
                nota='Recordatorio: volver a contactar (3 dias desde ultimo contacto)',
                completado=False,
            )
            db.session.add(seg)
            nota = NotaActividad(
                lead_id=lead.id,
                contenido=f'Estado cambiado a: Contactado ({lead.fecha_contacto.strftime("%d/%m/%Y %H:%M") if lead.fecha_contacto else ""})',
                tipo='llamada',
            )
            db.session.add(nota)

        # Log no_coge
        elif new_estado == 'no_coge':
            nota = NotaActividad(
                lead_id=lead.id,
                contenido='Llamado - No coge el telefono',
                tipo='llamada',
            )
            db.session.add(nota)
            seg = Seguimiento(
                lead_id=lead.id,
                fecha=datetime.utcnow() + timedelta(days=2),
                nota='Recordatorio: volver a llamar (no cogio la ultima vez)',
                completado=False,
            )
            db.session.add(seg)

        # Log a_espera_de_pago
        elif new_estado == 'a_espera_de_pago':
            nota = NotaActividad(
                lead_id=lead.id,
                contenido='Lead interesado - A espera de pago',
                tipo='otro',
            )
            db.session.add(nota)

        # Other state changes
        elif new_estado != old_estado:
            nota = NotaActividad(
                lead_id=lead.id,
                contenido=f'Estado cambiado de {old_estado} a {new_estado}',
                tipo='otro',
            )
            db.session.add(nota)

    if 'fecha_contacto' in data and data['fecha_contacto']:
        lead.fecha_contacto = datetime.fromisoformat(data['fecha_contacto'])
    if 'fecha_cita' in data and data['fecha_cita']:
        lead.fecha_cita = datetime.fromisoformat(data['fecha_cita'])
    if 'hora_preferida' in data:
        lead.hora_preferida = data['hora_preferida'] or ''
    if 'notas' in data:
        lead.notas = data['notas']

    lead.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(lead.to_dict())


@app.route('/api/leads/<int:lead_id>/pagado', methods=['POST'])
@login_required
def marcar_pagado(lead_id):
    """Mark lead as paid and auto-enroll as student."""
    lead = Lead.query.get_or_404(lead_id)
    data = request.get_json() or {}

    alumno = Alumno(
        nombre=lead.nombre,
        telefono=lead.telefono,
        email=lead.email,
        academia=lead.academia,
        especialidad=lead.especialidad,
        fecha_matricula=datetime.utcnow(),
        curso=data.get('curso', ''),
        modalidad=data.get('modalidad', 'presencial'),
        estado_pago='completo',
        notas=data.get('notas', ''),
        lead_id=lead.id,
    )
    db.session.add(alumno)

    lead.estado = 'matriculado'
    lead.updated_at = datetime.utcnow()

    nota = NotaActividad(
        lead_id=lead.id,
        contenido=f'PAGADO - Matriculado automaticamente. Curso: {alumno.curso}, Modalidad: {alumno.modalidad}',
        tipo='otro',
    )
    db.session.add(nota)

    db.session.commit()
    return jsonify({'lead': lead.to_dict(), 'alumno': alumno.to_dict()}), 201


@app.route('/api/leads/<int:lead_id>', methods=['DELETE'])
@login_required
def delete_lead(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    db.session.delete(lead)
    db.session.commit()
    return jsonify({'message': 'Lead eliminado'})


# ── Matriculacion: Lead -> Alumno ──────────────────────────────────────────

@app.route('/api/leads/<int:lead_id>/matricular', methods=['POST'])
@login_required
def matricular_lead(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    data = request.get_json() or {}

    alumno = Alumno(
        nombre=lead.nombre,
        telefono=lead.telefono,
        email=lead.email,
        academia=lead.academia,
        especialidad=lead.especialidad,
        fecha_matricula=datetime.utcnow(),
        curso=data.get('curso', ''),
        modalidad=data.get('modalidad', 'presencial'),
        estado_pago=data.get('estado_pago', 'pendiente'),
        notas=data.get('notas', ''),
        lead_id=lead.id,
    )
    db.session.add(alumno)

    lead.estado = 'matriculado'
    lead.updated_at = datetime.utcnow()

    nota = NotaActividad(
        lead_id=lead.id,
        contenido=f'Matriculado como alumno - Curso: {alumno.curso}, Modalidad: {alumno.modalidad}',
        tipo='otro',
    )
    db.session.add(nota)

    db.session.commit()
    return jsonify(alumno.to_dict()), 201


# ── Alumnos CRUD ───────────────────────────────────────────────────────────

@app.route('/api/alumnos')
@login_required
def list_alumnos():
    query = Alumno.query

    academia = request.args.get('academia')
    if academia:
        query = query.filter_by(academia=academia)

    # Exclude students managed in economic view (have grupo set) unless explicitly requested
    include_gestion = request.args.get('include_gestion')
    if not include_gestion:
        query = query.filter(db.or_(Alumno.grupo == '', Alumno.grupo.is_(None)))

    busqueda = request.args.get('busqueda')
    if busqueda:
        pattern = f'%{busqueda}%'
        query = query.filter(
            db.or_(
                Alumno.nombre.ilike(pattern),
                Alumno.email.ilike(pattern),
                Alumno.curso.ilike(pattern),
            )
        )

    estado_pago = request.args.get('estado_pago')
    if estado_pago:
        query = query.filter_by(estado_pago=estado_pago)

    alumnos = query.order_by(Alumno.fecha_matricula.desc()).all()
    return jsonify([a.to_dict() for a in alumnos])


@app.route('/api/alumnos/<int:alumno_id>')
@login_required
def get_alumno(alumno_id):
    alumno = Alumno.query.get_or_404(alumno_id)
    return jsonify(alumno.to_dict())


@app.route('/api/alumnos/<int:alumno_id>', methods=['PUT'])
@login_required
def update_alumno(alumno_id):
    alumno = Alumno.query.get_or_404(alumno_id)
    data = request.get_json()

    for field in ['nombre', 'telefono', 'email', 'especialidad', 'curso', 'modalidad', 'estado_pago', 'notas', 'metodo_pago', 'grupo']:
        if field in data:
            setattr(alumno, field, data[field])
    if 'cuota' in data:
        alumno.cuota = float(data['cuota']) if data['cuota'] else 0

    alumno.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(alumno.to_dict())


@app.route('/api/alumnos/<int:alumno_id>', methods=['DELETE'])
@login_required
def delete_alumno(alumno_id):
    alumno = Alumno.query.get_or_404(alumno_id)
    db.session.delete(alumno)
    db.session.commit()
    return jsonify({'message': 'Alumno eliminado'})


@app.route('/api/alumnos', methods=['POST'])
@login_required
def create_alumno():
    data = request.get_json()
    if not data.get('nombre') or not data.get('academia'):
        return jsonify({'error': 'Nombre y academia son obligatorios'}), 400

    alumno = Alumno(
        nombre=data['nombre'],
        telefono=data.get('telefono', ''),
        email=data.get('email', ''),
        academia=data['academia'],
        especialidad=data.get('especialidad', ''),
        fecha_matricula=datetime.utcnow(),
        curso=data.get('curso', ''),
        modalidad=data.get('modalidad', 'presencial'),
        estado_pago=data.get('estado_pago', 'pendiente'),
        cuota=float(data.get('cuota', 0)) if data.get('cuota') else 0,
        notas=data.get('notas', ''),
    )
    db.session.add(alumno)
    db.session.commit()
    return jsonify(alumno.to_dict()), 201


# ── Seguimientos ───────────────────────────────────────────────────────────

@app.route('/api/seguimientos')
@login_required
def list_seguimientos():
    query = Seguimiento.query

    pendientes = request.args.get('pendientes')
    if pendientes == 'true':
        query = query.filter_by(completado=False)

    lead_id = request.args.get('lead_id')
    if lead_id:
        query = query.filter_by(lead_id=int(lead_id))

    academia = request.args.get('academia')
    if academia:
        query = query.join(Lead).filter(Lead.academia == academia)

    seguimientos = query.order_by(Seguimiento.fecha.asc()).all()
    return jsonify([s.to_dict() for s in seguimientos])


@app.route('/api/seguimientos', methods=['POST'])
@login_required
def create_seguimiento():
    data = request.get_json()
    if not data.get('lead_id') or not data.get('fecha'):
        return jsonify({'error': 'lead_id y fecha son obligatorios'}), 400

    Lead.query.get_or_404(data['lead_id'])

    seg = Seguimiento(
        lead_id=data['lead_id'],
        fecha=datetime.fromisoformat(data['fecha']),
        nota=data.get('nota', ''),
        completado=data.get('completado', False),
    )
    db.session.add(seg)
    db.session.commit()
    return jsonify(seg.to_dict()), 201


@app.route('/api/seguimientos/<int:seg_id>', methods=['PUT'])
@login_required
def update_seguimiento(seg_id):
    seg = Seguimiento.query.get_or_404(seg_id)
    data = request.get_json()

    if 'fecha' in data:
        seg.fecha = datetime.fromisoformat(data['fecha'])
    if 'nota' in data:
        seg.nota = data['nota']
    if 'completado' in data:
        seg.completado = data['completado']

    db.session.commit()
    return jsonify(seg.to_dict())


@app.route('/api/seguimientos/<int:seg_id>', methods=['DELETE'])
@login_required
def delete_seguimiento(seg_id):
    seg = Seguimiento.query.get_or_404(seg_id)
    db.session.delete(seg)
    db.session.commit()
    return jsonify({'message': 'Seguimiento eliminado'})


# ── Notas de Actividad ────────────────────────────────────────────────────

@app.route('/api/notas', methods=['POST'])
@login_required
def create_nota():
    data = request.get_json()
    if not data.get('lead_id') or not data.get('contenido'):
        return jsonify({'error': 'lead_id y contenido son obligatorios'}), 400

    Lead.query.get_or_404(data['lead_id'])

    nota = NotaActividad(
        lead_id=data['lead_id'],
        contenido=data['contenido'],
        tipo=data.get('tipo', 'otro'),
    )
    db.session.add(nota)
    db.session.commit()
    return jsonify(nota.to_dict()), 201


@app.route('/api/leads/<int:lead_id>/notas')
@login_required
def get_notas_lead(lead_id):
    Lead.query.get_or_404(lead_id)
    notas = NotaActividad.query.filter_by(lead_id=lead_id).order_by(
        NotaActividad.created_at.desc()
    ).all()
    return jsonify([n.to_dict() for n in notas])


# ── Export CSV ─────────────────────────────────────────────────────────────

@app.route('/api/export/csv')
@login_required
def export_csv():
    query = Lead.query

    academia = request.args.get('academia')
    if academia:
        query = query.filter_by(academia=academia)

    estado = request.args.get('estado')
    if estado:
        query = query.filter_by(estado=estado)

    leads = query.order_by(Lead.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Nombre', 'Telefono', 'Email', 'Academia', 'Estado', 'Notas', 'Fecha Creacion'])

    for lead in leads:
        writer.writerow([
            lead.id, lead.nombre, lead.telefono, lead.email,
            lead.academia, lead.estado, lead.notas,
            lead.created_at.strftime('%Y-%m-%d %H:%M') if lead.created_at else '',
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=leads_export.csv'},
    )


@app.route('/api/export/alumnos/csv')
@login_required
def export_alumnos_csv():
    query = Alumno.query

    academia = request.args.get('academia')
    if academia:
        query = query.filter_by(academia=academia)

    alumnos = query.order_by(Alumno.fecha_matricula.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Nombre', 'Telefono', 'Email', 'Academia', 'Curso', 'Modalidad', 'Estado Pago', 'Fecha Matricula'])

    for a in alumnos:
        writer.writerow([
            a.id, a.nombre, a.telefono, a.email,
            a.academia, a.curso, a.modalidad, a.estado_pago,
            a.fecha_matricula.strftime('%Y-%m-%d') if a.fecha_matricula else '',
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=alumnos_export.csv'},
    )


# ── Gestion Economica ─────────────────────────────────────────────────────

@app.route('/api/meses')
@login_required
def list_meses():
    academia = request.args.get('academia')
    query = MesActivo.query
    if academia:
        query = query.filter_by(academia=academia)
    meses = query.order_by(MesActivo.mes.asc()).all()
    return jsonify([m.to_dict() for m in meses])


@app.route('/api/meses', methods=['POST'])
@login_required
def create_mes():
    data = request.get_json()
    mes = data.get('mes')  # "2026-04"
    academia = data.get('academia')
    if not mes or not academia:
        return jsonify({'error': 'mes y academia son obligatorios'}), 400
    existing = MesActivo.query.filter_by(mes=mes, academia=academia).first()
    if existing:
        return jsonify({'error': 'Ese mes ya existe para esa academia'}), 400
    m = MesActivo(mes=mes, academia=academia)
    db.session.add(m)
    db.session.commit()
    return jsonify(m.to_dict()), 201


@app.route('/api/gestion-economica')
@login_required
def gestion_economica():
    academia = request.args.get('academia')
    if not academia:
        return jsonify({'error': 'academia es obligatorio'}), 400

    # Get active months for this academy
    meses = MesActivo.query.filter_by(academia=academia).order_by(MesActivo.mes.asc()).all()
    meses_list = [m.mes for m in meses]

    # Get all students for this academy
    alumnos = Alumno.query.filter_by(academia=academia).order_by(Alumno.nombre.asc()).all()

    # Get all payments for these students
    alumno_ids = [a.id for a in alumnos]
    pagos = Pago.query.filter(Pago.alumno_id.in_(alumno_ids)).all() if alumno_ids else []

    # Build payments lookup: {alumno_id: {mes: pago_dict}}
    pagos_map = {}
    for p in pagos:
        if p.alumno_id not in pagos_map:
            pagos_map[p.alumno_id] = {}
        pagos_map[p.alumno_id][p.mes] = p.to_dict()

    # Group by grupo, sorted: efectivo first then domiciliacion
    grupos = {}
    grupo_order = ['EF LUNES', 'EF MARTES', 'EF MIÉRCOLES', 'EF JUEVES',
                   'AL', 'INGLÉS', 'INFANTIL', 'PT PRESENCIAL', 'PRIMARIA', 'PT ONLINE', 'PT JÉSSICA 2 AÑOS']
    for a in alumnos:
        g = a.grupo or a.especialidad or 'Sin grupo'
        if g not in grupos:
            grupos[g] = []
        grupos[g].append({
            'id': a.id,
            'nombre': a.nombre,
            'especialidad': a.especialidad,
            'grupo': g,
            'metodo_pago': a.metodo_pago or 'efectivo',
            'cuota': a.cuota or 0,
            'pagos': pagos_map.get(a.id, {}),
        })

    # Sort each group: efectivo first, then domiciliacion
    for g in grupos:
        grupos[g].sort(key=lambda x: (0 if x['metodo_pago'] == 'efectivo' else 1, x['nombre']))

    # Order groups
    ordered_grupos = []
    for g in grupo_order:
        if g in grupos:
            ordered_grupos.append({'nombre': g, 'alumnos': grupos[g]})
    for g in grupos:
        if g not in grupo_order:
            ordered_grupos.append({'nombre': g, 'alumnos': grupos[g]})

    # Totals per month
    totales = {}
    for mes in meses_list:
        efectivo = sum(p.cantidad for p in pagos if p.mes == mes and p.metodo == 'efectivo')
        recibo = sum(p.cantidad for p in pagos if p.mes == mes and p.metodo == 'recibo')
        totales[mes] = {'efectivo': efectivo, 'recibo': recibo, 'total': efectivo + recibo}

    return jsonify({
        'meses': meses_list,
        'grupos': ordered_grupos,
        'totales': totales,
    })


@app.route('/api/pagos', methods=['POST'])
@login_required
def create_pago():
    data = request.get_json()
    alumno_id = data.get('alumno_id')
    mes = data.get('mes')
    metodo = data.get('metodo')
    cantidad = data.get('cantidad', 0)

    if not alumno_id or not mes or not metodo:
        return jsonify({'error': 'alumno_id, mes y metodo son obligatorios'}), 400

    # Check if payment already exists for this alumno+mes
    existing = Pago.query.filter_by(alumno_id=alumno_id, mes=mes).first()
    if existing:
        return jsonify({'error': 'Ya existe un pago para este alumno en este mes'}), 400

    pago = Pago(
        alumno_id=alumno_id,
        mes=mes,
        metodo=metodo,
        cantidad=float(cantidad),
        recogido_por=data.get('recogido_por') if metodo == 'efectivo' else None,
    )
    db.session.add(pago)
    db.session.commit()
    return jsonify(pago.to_dict()), 201


@app.route('/api/pagos/<int:pago_id>', methods=['PUT'])
@login_required
def update_pago(pago_id):
    pago = Pago.query.get_or_404(pago_id)
    data = request.get_json()

    if 'metodo' in data:
        pago.metodo = data['metodo']
    if 'cantidad' in data:
        pago.cantidad = float(data['cantidad'])
    if 'recogido_por' in data:
        pago.recogido_por = data['recogido_por'] if pago.metodo == 'efectivo' else None

    db.session.commit()
    return jsonify(pago.to_dict())


@app.route('/api/pagos/<int:pago_id>', methods=['DELETE'])
@login_required
def delete_pago(pago_id):
    pago = Pago.query.get_or_404(pago_id)
    db.session.delete(pago)
    db.session.commit()
    return jsonify({'message': 'Pago eliminado'})


@app.route('/api/socios')
@login_required
def socios():
    # Get all ledger entries
    registros = RegistroEfectivo.query.order_by(RegistroEfectivo.created_at.desc()).all()

    socios_data = {}
    for socio in SOCIOS:
        registros_socio = [r for r in registros if r.socio == socio]
        total = sum(r.cantidad for r in registros_socio)
        socios_data[socio] = {'total': total}

    # Calculate expected cash: count of efectivo payments * 180
    efectivo_pagos = Pago.query.join(Alumno).filter(
        Alumno.academia == 'PREPATOP',
        Alumno.grupo != '',
        Alumno.grupo.isnot(None),
        Pago.metodo == 'efectivo',
    ).count()
    efectivo_esperado = efectivo_pagos * 180

    return jsonify({
        'socios': socios_data,
        'registros': [r.to_dict() for r in registros],
        'efectivo_esperado': efectivo_esperado,
    })


@app.route('/api/registro-efectivo', methods=['POST'])
@login_required
def create_registro_efectivo():
    data = request.get_json()
    socio = data.get('socio')
    alumno_nombre = data.get('alumno_nombre')
    cantidad = data.get('cantidad')

    if not socio or not alumno_nombre or not cantidad:
        return jsonify({'error': 'socio, alumno y cantidad son obligatorios'}), 400

    registro = RegistroEfectivo(
        socio=socio,
        alumno_nombre=alumno_nombre,
        cantidad=float(cantidad),
        nota=data.get('nota', ''),
    )
    db.session.add(registro)
    db.session.commit()
    return jsonify(registro.to_dict()), 201


@app.route('/api/registro-efectivo/<int:registro_id>', methods=['DELETE'])
@login_required
def delete_registro_efectivo(registro_id):
    registro = RegistroEfectivo.query.get_or_404(registro_id)
    db.session.delete(registro)
    db.session.commit()
    return jsonify({'message': 'Registro eliminado'})


@app.route('/api/bulk-set-domiciliacion', methods=['POST'])
@login_required
def bulk_set_domiciliacion():
    """Set metodo_pago='domiciliacion' for students matching names (accent-insensitive)."""
    import unicodedata

    def normalize(s):
        """Remove accents and lowercase."""
        nfkd = unicodedata.normalize('NFKD', s)
        return ''.join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

    data = request.get_json()
    names = data.get('names', [])

    # Get all PREPATOP students
    alumnos = Alumno.query.filter(
        Alumno.academia == 'PREPATOP',
    ).all()

    # Build normalized lookup
    alumno_map = {}
    for a in alumnos:
        alumno_map[normalize(a.nombre)] = a

    updated = []
    not_found = []
    for name in names:
        norm = normalize(name)
        if norm in alumno_map:
            alumno_map[norm].metodo_pago = 'domiciliacion'
            updated.append(alumno_map[norm].nombre)
        else:
            not_found.append(name)
    db.session.commit()
    return jsonify({'updated': updated, 'not_found': not_found})


@app.route('/api/llamada-registrada', methods=['POST'])
def llamada_registrada():
    """Webhook for MacroDroid to register outgoing calls automatically.
    Auth via shared token in header X-Token or query param token.
    Body JSON: {phone, duration_seconds, timestamp (optional ISO), socio (optional: Alberto/Esteban)}
    """
    token = request.headers.get('X-Token') or request.args.get('token')
    expected = os.environ.get('CALL_WEBHOOK_TOKEN', 'crm-calls-2026')
    if token != expected:
        return jsonify({'error': 'unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    # MacroDroid may also send form-encoded
    if not data:
        data = request.form.to_dict()

    phone = str(data.get('phone', '')).strip()
    if not phone:
        return jsonify({'error': 'phone required'}), 400
    try:
        duration = int(float(data.get('duration_seconds', 0)))
    except Exception:
        duration = 0
    socio = data.get('socio', '')
    ts_str = data.get('timestamp', '')
    try:
        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00')) if ts_str else datetime.utcnow()
    except Exception:
        ts = datetime.utcnow()

    # Normalize phone: keep only digits, last 9 are the local part
    digits = ''.join(c for c in phone if c.isdigit())
    last9 = digits[-9:] if len(digits) >= 9 else digits

    # Find lead by phone (match last 9 digits)
    lead = None
    for candidate in Lead.query.filter(Lead.telefono != '').all():
        cdigits = ''.join(c for c in (candidate.telefono or '') if c.isdigit())
        if cdigits.endswith(last9) and len(last9) >= 7:
            lead = candidate
            break

    if not lead:
        return jsonify({'matched': False, 'phone': phone, 'message': 'No lead with that phone'}), 200

    # Register call as nota
    nota_text = f'Llamada {"saliente" if not socio else f"de {socio}"}: {duration}s'
    nota = NotaActividad(lead_id=lead.id, tipo='llamada', contenido=nota_text, created_at=ts)
    db.session.add(nota)

    # Auto-update estado based on duration
    estado_changed = None
    if lead.estado in ('nuevo', 'no_coge', 'contactado'):
        if duration == 0:
            if lead.estado != 'no_coge':
                lead.estado = 'no_coge'
                estado_changed = 'no_coge'
        elif duration > 30:
            if lead.estado != 'contactado':
                lead.estado = 'contactado'
                lead.fecha_contacto = ts
                estado_changed = 'contactado'

    db.session.commit()
    return jsonify({
        'matched': True,
        'lead_id': lead.id,
        'lead_name': lead.nombre,
        'duration': duration,
        'estado': lead.estado,
        'estado_changed': estado_changed,
    }), 201


@app.route('/api/upload-sepa', methods=['POST'])
@login_required
def upload_sepa():
    """Extract student data from a filled SEPA PDF form and create alumno."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    academia = request.form.get('academia', 'PREPARAANDALUCIA')
    especialidad = request.form.get('especialidad', '')

    try:
        from pypdf import PdfReader
        reader = PdfReader(file)
        fields = reader.get_form_text_fields() or {}

        # Try to extract data from form fields
        nombre = fields.get('Nombre', '').strip()
        apellidos = fields.get('Apellidos', '').strip()
        nif = fields.get('NIFNIE', '') or fields.get('NIF/NIE', '') or ''
        telefono = fields.get('Teléfono', '') or fields.get('Telefono', '') or ''
        email = fields.get('Correo electrónico', '') or fields.get('Correo electronico', '') or ''
        iban = fields.get('IBAN', '').strip()
        direccion = fields.get('Dirección', '') or fields.get('Direccion', '') or ''
        cp_ciudad = fields.get('Código postal y ciudad', '') or fields.get('Codigo postal y ciudad', '') or ''

        # If fields are empty, try all fields and return them for debugging
        if not nombre and not apellidos:
            return jsonify({
                'error': 'No se pudieron extraer los datos del PDF. Campos encontrados:',
                'fields': {k: v for k, v in fields.items() if v},
                'all_field_names': list(fields.keys()),
            }), 400

        full_name = f"{nombre} {apellidos}".strip()

        # Create alumno
        alumno = Alumno(
            nombre=full_name,
            telefono=telefono.strip(),
            email=email.strip(),
            academia=academia,
            especialidad=especialidad,
            metodo_pago='domiciliacion',
            curso='Oposiciones',
            notas=f"NIF: {nif.strip()} | IBAN: {iban} | Dir: {direccion} {cp_ciudad}".strip(),
        )
        db.session.add(alumno)
        db.session.commit()

        return jsonify({
            'message': f'Alumno {full_name} matriculado correctamente',
            'alumno': alumno.to_dict(),
            'extracted': {
                'nombre': nombre, 'apellidos': apellidos, 'nif': nif,
                'telefono': telefono, 'email': email, 'iban': iban,
            },
        }), 201

    except Exception as e:
        return jsonify({'error': f'Error procesando el PDF: {str(e)}'}), 400


@app.route('/api/reset-prepatop-2526', methods=['POST'])
@login_required
def reset_prepatop_2526():
    """Delete all PREPATOP students with grupo set, then reimport from JSON body."""
    data = request.get_json()
    students = data.get('students', [])

    # Delete all current PREPATOP students with grupo
    Alumno.query.filter(
        Alumno.academia == 'PREPATOP',
        Alumno.grupo != '',
        Alumno.grupo.isnot(None)
    ).delete(synchronize_session='fetch')

    # Also delete those without grupo (old imports)
    Alumno.query.filter(
        Alumno.academia == 'PREPATOP',
        db.or_(Alumno.grupo == '', Alumno.grupo.is_(None))
    ).delete(synchronize_session='fetch')

    # Import new students
    count = 0
    for s in students:
        alumno = Alumno(
            nombre=s['nombre'].strip(),
            academia='PREPATOP',
            especialidad=s.get('especialidad', ''),
            grupo=s.get('grupo', ''),
            metodo_pago=s.get('metodo_pago', 'efectivo'),
            curso='Oposiciones',
        )
        db.session.add(alumno)
        count += 1

    # Ensure months exist
    for mes in ['2026-04', '2026-05', '2026-06']:
        if not MesActivo.query.filter_by(mes=mes, academia='PREPATOP').first():
            db.session.add(MesActivo(mes=mes, academia='PREPATOP'))

    db.session.commit()
    return jsonify({'deleted': 'all', 'imported': count})


@app.route('/api/fix-grupos', methods=['POST'])
@login_required
def fix_grupos():
    """Fix grupo field for students that were imported before grupo was added."""
    import unicodedata

    def normalize(s):
        nfkd = unicodedata.normalize('NFKD', s)
        return ''.join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

    # Build name->grupo+metodo mapping from seed data
    name_to_info = {}
    for nombre, esp, grupo, metodo in PREPATOP_SEED_DATA:
        name_to_info[normalize(nombre)] = (grupo, metodo)

    alumnos = Alumno.query.filter_by(academia='PREPATOP').all()
    updated = 0
    for a in alumnos:
        norm = normalize(a.nombre)
        if norm in name_to_info:
            grupo, metodo = name_to_info[norm]
            if not a.grupo or a.grupo == '':
                a.grupo = grupo
            if not a.metodo_pago or a.metodo_pago == 'efectivo':
                a.metodo_pago = metodo
            updated += 1
    db.session.commit()
    return jsonify({'updated': updated, 'total': len(alumnos)})


PREPATOP_SEED_DATA = [
        # EF LUNES
        ('ANTONIO CARRASCO GUERRERO', 'EF', 'EF LUNES', 'efectivo'),
        ('ADRIÁN VINAGRE CAÑADAS', 'EF', 'EF LUNES', 'efectivo'),
        ('MANUEL LORENTE PESO', 'EF', 'EF LUNES', 'efectivo'),
        ('DANIEL CEREZO DELGADO', 'EF', 'EF LUNES', 'efectivo'),
        ('MIRIAM GUZMAN FERNÁNDEZ', 'EF', 'EF LUNES', 'efectivo'),
        ('LAURA RODERO FERNÁNDEZ', 'EF', 'EF LUNES', 'efectivo'),
        ('SERGIO LUQUE MARTÍN', 'EF', 'EF LUNES', 'efectivo'),
        ('LUCÍA BARTOLOMÉ CABERO', 'EF', 'EF LUNES', 'domiciliacion'),
        ('CARLOS ROMÁN HERNÁNDEZ', 'EF', 'EF LUNES', 'efectivo'),
        ('MARÍA BEATRIZ REAL MOURELLE', 'EF', 'EF LUNES', 'efectivo'),
        ('EMMA MARBÁN DE SALVADOR', 'EF', 'EF LUNES', 'efectivo'),
        ('JORGE GARCÍA ALCONCHEL', 'EF', 'EF LUNES', 'efectivo'),
        # EF MARTES
        ('ESTHER PACHÓN VILLADA', 'EF', 'EF MARTES', 'efectivo'),
        ('MIGUEL RUIZ FERNÁNDEZ', 'EF', 'EF MARTES', 'efectivo'),
        ('MARÍA PALACIOS SÁNCHEZ', 'EF', 'EF MARTES', 'efectivo'),
        ('ADRIÁN NIETO BAUTISTA', 'EF', 'EF MARTES', 'efectivo'),
        ('GLORIA NAVARRO GONZÁLEZ', 'EF', 'EF MARTES', 'efectivo'),
        ('NURIA CALERO CRUZ', 'EF', 'EF MARTES', 'efectivo'),
        ('SERGIO ESTÉVEZ ACEDO', 'EF', 'EF MARTES', 'efectivo'),
        ('ROSA MARÍA TORRES GÓMEZ', 'EF', 'EF MARTES', 'efectivo'),
        ('GONZALO MOYA GÁLVEZ', 'EF', 'EF MARTES', 'efectivo'),
        ('CAROLINA TROJACKI NOWAK', 'EF', 'EF MARTES', 'efectivo'),
        # EF MIÉRCOLES
        ('LAURA PINTADO PÉREZ', 'EF', 'EF MIÉRCOLES', 'efectivo'),
        ('MARINA PUIG DEL CASTILLO', 'EF', 'EF MIÉRCOLES', 'efectivo'),
        ('DAVID PELZER PEINADO', 'EF', 'EF MIÉRCOLES', 'efectivo'),
        ('ÁNGEL GÓMEZ GARCÍA', 'EF', 'EF MIÉRCOLES', 'efectivo'),
        ('ALEJANDRO RODRÍGUEZ CÓRDOBA', 'EF', 'EF MIÉRCOLES', 'efectivo'),
        ('DANIEL MUÑOZ BAUTISTA', 'EF', 'EF MIÉRCOLES', 'efectivo'),
        ('ALICIA DE LA ENCARNACIÓN CUENA', 'EF', 'EF MIÉRCOLES', 'efectivo'),
        ('MIGUEL HERMIDA MUÑOZ', 'EF', 'EF MIÉRCOLES', 'efectivo'),
        ('SAMUEL GARCÍLOPEZ SERRANO', 'EF', 'EF MIÉRCOLES', 'efectivo'),
        ('MARIA TORRE GONZÁLEZ', 'EF', 'EF MIÉRCOLES', 'efectivo'),
        ('ERIK MORALES COELLO', 'EF', 'EF MIÉRCOLES', 'efectivo'),
        # EF JUEVES
        ('CHEMA DÍAZ CAPILLA', 'EF', 'EF JUEVES', 'efectivo'),
        ('ÁLVARO MESONERO ORTIZ', 'EF', 'EF JUEVES', 'efectivo'),
        ('JAVIER GONZÁLEZ MATEO', 'EF', 'EF JUEVES', 'efectivo'),
        ('DANIEL CHILLARÓN SERRANO', 'EF', 'EF JUEVES', 'efectivo'),
        ('LAURA CRESPO VICENTE', 'EF', 'EF JUEVES', 'efectivo'),
        ('PABLO MARÍN SÁNCHEZ', 'EF', 'EF JUEVES', 'efectivo'),
        ('KAREN BUENO CASTRO', 'EF', 'EF JUEVES', 'efectivo'),
        ('PABLO GARCÍA MÍNGUEZ', 'EF', 'EF JUEVES', 'domiciliacion'),
        # AL
        ('Ana Jiménez Montes', 'AL', 'AL', 'domiciliacion'),
        ('Marta Almendros Candeleda', 'AL', 'AL', 'domiciliacion'),
        ('Elena Ferrero Álvarez', 'AL', 'AL', 'domiciliacion'),
        ('Irene Plaza López', 'AL', 'AL', 'efectivo'),
        ('Beatriz Pérez López', 'AL', 'AL', 'domiciliacion'),
        ('Marcos González Gómez', 'AL', 'AL', 'domiciliacion'),
        ('Lola Sánchez Flórez', 'AL', 'AL', 'domiciliacion'),
        ('MARTA CASABELLA SÁNCHEZ', 'AL', 'AL', 'domiciliacion'),
        # INGLÉS
        ('Paula Domingo Benito', 'Ingles', 'INGLÉS', 'efectivo'),
        ('Sofía Faerna Campíñez', 'Ingles', 'INGLÉS', 'efectivo'),
        ('María García Garcia', 'Ingles', 'INGLÉS', 'efectivo'),
        ('Irene Martín Muñoz', 'Ingles', 'INGLÉS', 'domiciliacion'),
        ('Andrea Cañizares Pereña', 'Ingles', 'INGLÉS', 'domiciliacion'),
        ('Irene Checa Muñoz', 'Ingles', 'INGLÉS', 'efectivo'),
        ('Estela Payo Molina', 'Ingles', 'INGLÉS', 'domiciliacion'),
        ('Ruth Huertas Santos', 'Ingles', 'INGLÉS', 'efectivo'),
        # INFANTIL
        ('Natalia Isabel Gómez', 'Infantil', 'INFANTIL', 'efectivo'),
        ('Noelia Bote Ramiro', 'Infantil', 'INFANTIL', 'domiciliacion'),
        ('Paula Martínez Villa', 'Infantil', 'INFANTIL', 'efectivo'),
        ('Sara Lopez Serrano', 'Infantil', 'INFANTIL', 'efectivo'),
        ('Carlota Arteaga Garcia Cesto', 'Infantil', 'INFANTIL', 'domiciliacion'),
        ('Vanesa (amiga de loly)', 'Infantil', 'INFANTIL', 'domiciliacion'),
        ('ANA PASTOR LÓPEZ-PUIGCERDER', 'Infantil', 'INFANTIL', 'efectivo'),
        ('Lorena Sol Hernández', 'Infantil', 'INFANTIL', 'efectivo'),
        ('SOFÍA SÁNCHEZ VILLAHOZ', 'Infantil', 'INFANTIL', 'domiciliacion'),
        ('LUCÍA PEDROCHE', 'Infantil', 'INFANTIL', 'domiciliacion'),
        # PT PRESENCIAL
        ('Andrea Gómez Medina', 'PT', 'PT PRESENCIAL', 'domiciliacion'),
        ('Lara Timón Soto', 'PT', 'PT PRESENCIAL', 'efectivo'),
        ('Laura López Fernández de la Puebla', 'PT', 'PT PRESENCIAL', 'domiciliacion'),
        ('Noelia Murillo Pablo', 'PT', 'PT PRESENCIAL', 'efectivo'),
        ('Lidia Martin Mata', 'PT', 'PT PRESENCIAL', 'domiciliacion'),
        ('Adriana (Pablo)', 'PT', 'PT PRESENCIAL', 'domiciliacion'),
        ('Julia García Rodríguez', 'PT', 'PT PRESENCIAL', 'domiciliacion'),
        ('Shanon', 'PT', 'PT PRESENCIAL', 'domiciliacion'),
        ('SAMUEL ADAN DIEZ', 'PT', 'PT PRESENCIAL', 'efectivo'),
        ('Lorena Pérez Maldonado', 'PT', 'PT PRESENCIAL', 'domiciliacion'),
        # PRIMARIA
        ('Miguel Armero Sanchiz', 'Primaria', 'PRIMARIA', 'efectivo'),
        ('Raquel Partido Lorenzo', 'Primaria', 'PRIMARIA', 'efectivo'),
        ('María Bengoechea Gonzalo', 'Primaria', 'PRIMARIA', 'domiciliacion'),
        ('Laura Rebollo Añover', 'Primaria', 'PRIMARIA', 'efectivo'),
        ('Laura Conde Soriano', 'Primaria', 'PRIMARIA', 'efectivo'),
        ('María del Sol Pedreira Pozo', 'Primaria', 'PRIMARIA', 'domiciliacion'),
        ('María Lucía Pedreira Pozo', 'Primaria', 'PRIMARIA', 'domiciliacion'),
        ('Lucía Haba Niso', 'Primaria', 'PRIMARIA', 'efectivo'),
        ('Nuria Muinelo Morcillo', 'Primaria', 'PRIMARIA', 'domiciliacion'),
        ('María Jesus Cecilia de la Iglesia', 'Primaria', 'PRIMARIA', 'efectivo'),
        ('Noemi López García', 'Primaria', 'PRIMARIA', 'domiciliacion'),
        ('Natalia Soto Tébar', 'Primaria', 'PRIMARIA', 'domiciliacion'),
        ('YAIZA', 'Primaria', 'PRIMARIA', 'efectivo'),
        # PT ONLINE
        ('Gabriela Lastra Lapeña', 'PT Online', 'PT ONLINE', 'domiciliacion'),
        ('Marta González López', 'PT Online', 'PT ONLINE', 'domiciliacion'),
        ('Isabel Menéndez Méndez', 'PT Online', 'PT ONLINE', 'domiciliacion'),
        ('Irati Balza', 'PT Online', 'PT ONLINE', 'domiciliacion'),
        ('María Briones Lázaro', 'PT Online', 'PT ONLINE', 'domiciliacion'),
        ('Rocío Méndez Elvira', 'PT Online', 'PT ONLINE', 'domiciliacion'),
        ('Alejandra Ramón Bermejo', 'PT Online', 'PT ONLINE', 'domiciliacion'),
        ('María Calle González', 'PT Online', 'PT ONLINE', 'domiciliacion'),
        ('Marta Roldan Perez', 'PT Online', 'PT ONLINE', 'domiciliacion'),
        ('Mari Carmen Lopez Garcia Heras', 'PT Online', 'PT ONLINE', 'domiciliacion'),
        ('NICOLE', 'PT Online', 'PT ONLINE', 'domiciliacion'),
        ('Hugo Bermejo Martínez', 'PT Online', 'PT ONLINE', 'domiciliacion'),
        # PT JÉSSICA 2 AÑOS
        ('Nerea Gallardo Segado', 'PT', 'PT JÉSSICA 2 AÑOS', 'domiciliacion'),
        ('María del Carmen Gómez Carmona', 'PT', 'PT JÉSSICA 2 AÑOS', 'domiciliacion'),
        ('Lucia Olmos Higueras', 'PT', 'PT JÉSSICA 2 AÑOS', 'domiciliacion'),
        ('Elena Bárcena Castresana', 'PT', 'PT JÉSSICA 2 AÑOS', 'domiciliacion'),
        ('Cristina Jiménez Velasco', 'PT', 'PT JÉSSICA 2 AÑOS', 'domiciliacion'),
        ('Ana Fernández Bosquet', 'PT', 'PT JÉSSICA 2 AÑOS', 'domiciliacion'),
        ('CRISTINA PARRAL CAÑADA', 'PT', 'PT JÉSSICA 2 AÑOS', 'domiciliacion'),
    ]


@app.route('/api/seed-prepatop', methods=['POST'])
@login_required
def seed_prepatop():
    """Seed PREPATOP students from the master Excel data."""
    existing = Alumno.query.filter_by(academia='PREPATOP').count()
    if existing > 0:
        return jsonify({'message': f'Ya hay {existing} alumnos de PREPATOP. No se importaron nuevos.', 'count': existing})

    count = 0
    for nombre, especialidad, grupo, metodo in PREPATOP_SEED_DATA:
        alumno = Alumno(
            nombre=nombre.strip(),
            academia='PREPATOP',
            especialidad=especialidad,
            grupo=grupo,
            metodo_pago=metodo,
            curso='Oposiciones',
        )
        db.session.add(alumno)
        count += 1

    # Also create the 3 months (April, May, June 2026)
    for mes in ['2026-04', '2026-05', '2026-06']:
        if not MesActivo.query.filter_by(mes=mes, academia='PREPATOP').first():
            db.session.add(MesActivo(mes=mes, academia='PREPATOP'))

    db.session.commit()
    return jsonify({'message': f'{count} alumnos importados', 'count': count}), 201


@app.route('/api/db-check')
@login_required
def db_check():
    """Temporary diagnostic endpoint to verify DB connection."""
    db_url = app.config['SQLALCHEMY_DATABASE_URI']
    is_postgres = 'postgresql' in db_url
    leads_count = Lead.query.count()
    alumnos_count = Alumno.query.count()
    # Check if fecha_contacto column exists
    has_fecha_contacto = hasattr(Lead, 'fecha_contacto')
    return jsonify({
        'database_type': 'PostgreSQL' if is_postgres else 'SQLite',
        'leads_count': leads_count,
        'alumnos_count': alumnos_count,
        'has_fecha_contacto': has_fecha_contacto,
        'db_url_prefix': db_url[:20] + '...',
    })


# ═════════════════════════════════════════════════════════════════════════
# CALL LOG (Tasker → /api/calls/log)
# ═════════════════════════════════════════════════════════════════════════
#
# Endpoint que reciben los webhooks del móvil (Tasker en Android) cuando
# termina una llamada con un lead. Si encuentra al lead por teléfono,
# crea una NotaActividad tipo "llamada" con dirección y duración.
#
# Autenticación: header X-CRM-Token = CALL_LOG_TOKEN.
# POST body JSON:
#   {
#     "phone": "+34612345678" o "612345678",
#     "direction": "outgoing" | "incoming",
#     "duration_seconds": 142,
#     "timestamp": "2026-06-02T15:30:00Z"  (opcional)
#   }


def _norm_phone_for_match(p):
    """Normaliza teléfonos para comparar (mismo criterio que el worker)."""
    if not p:
        return ""
    d = str(p).replace(" ", "").replace("-", "").lstrip("+")
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("34") and len(d) == 11:
        d = d[2:]
    return d[-9:] if len(d) >= 9 else ""


@app.route("/api/calls/log", methods=["POST"])
def log_call():
    # Auth por token
    expected = os.environ.get("CALL_LOG_TOKEN", "")
    if not expected:
        return jsonify({"error": "CALL_LOG_TOKEN no configurado en el servidor"}), 500
    provided = request.headers.get("X-CRM-Token") or (request.get_json(silent=True) or {}).get("token", "")
    if provided != expected:
        return jsonify({"error": "Token inválido"}), 401

    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip()
    direction = (data.get("direction") or "outgoing").strip().lower()
    try:
        duration_sec = int(data.get("duration_seconds") or 0)
    except (ValueError, TypeError):
        duration_sec = 0

    if not phone:
        return jsonify({"error": "Falta 'phone' en el body"}), 400

    target = _norm_phone_for_match(phone)
    if not target:
        return jsonify({"error": "Teléfono no válido", "phone": phone}), 400

    # Buscar lead por teléfono normalizado
    lead = None
    for l in Lead.query.all():
        if _norm_phone_for_match(l.telefono) == target:
            lead = l
            break

    if not lead:
        return jsonify({
            "lead_found": False,
            "phone_normalized": target,
            "message": f"Sin lead asociado al número (terminado en {target[-9:]})",
        }), 200

    # Formato de duración legible
    if duration_sec >= 60:
        duration_str = f"{duration_sec // 60} min {duration_sec % 60:02d} s"
    elif duration_sec > 0:
        duration_str = f"{duration_sec} s"
    else:
        duration_str = "sin contestar"

    dir_label = "Llamada saliente" if direction == "outgoing" else "Llamada entrante"
    contenido = f"{dir_label} ({duration_str})"

    nota = NotaActividad(
        lead_id=lead.id,
        contenido=contenido,
        tipo="llamada",
    )
    db.session.add(nota)
    db.session.commit()

    return jsonify({
        "lead_found": True,
        "lead_id": lead.id,
        "lead_nombre": lead.nombre,
        "lead_academia": lead.academia,
        "nota_id": nota.id,
        "contenido": contenido,
    })


# ═════════════════════════════════════════════════════════════════════════
# META ADS DASHBOARD
# ═════════════════════════════════════════════════════════════════════════

META_GRAPH_VERSION = "v25.0"
META_CACHE_TTL = 300  # 5 minutos
_meta_cache = {}  # {(endpoint, *args): (timestamp, data)}

# action_types que Meta usa para "lead" (depende del tipo de campaña)
LEAD_ACTION_TYPES = {
    "lead",
    "onsite_conversion.lead_grouped",
    "leadgen.other",
    "offsite_conversion.fb_pixel_lead",
}


def meta_cache_get(key):
    entry = _meta_cache.get(key)
    if entry and (time.time() - entry[0]) < META_CACHE_TTL:
        return entry[1]
    return None


def meta_cache_set(key, data):
    _meta_cache[key] = (time.time(), data)


def meta_graph_get(path, params, token):
    """GET a Meta Graph API. Devuelve dict (con 'error' si falla)."""
    params = {**params, "access_token": token}
    url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
            return {"error": body.get("error", {"message": str(body)})}
        except Exception:
            return {"error": {"message": f"HTTP {e.code}"}}
    except Exception as e:
        return {"error": {"message": str(e)}}


def get_meta_academy_config(academia_code):
    """academia_code: 'and' o 'sec'. Devuelve dict de config o None."""
    if academia_code == "and":
        return {
            "code": "and",
            "name": "PREPARAANDALUCIA",
            "label": "Andalucía",
            "token": os.environ.get("META_PAGE_TOKEN", ""),
            "ad_account": os.environ.get("META_AD_ACCOUNT_AND", ""),
            "campaign_id": os.environ.get("META_CAMPAIGN_AND", ""),
        }
    if academia_code == "sec":
        return {
            "code": "sec",
            "name": "PREPARASECUNDARIA",
            "label": "Secundaria",
            "token": os.environ.get("META_PAGE_TOKEN_SEC", ""),
            "ad_account": os.environ.get("META_AD_ACCOUNT_SEC", ""),
            "campaign_id": os.environ.get("META_CAMPAIGN_SEC", ""),
        }
    return None


def _meta_config_or_error(academia_code):
    """Devuelve (cfg, error_response). Si error_response no es None, hay que devolverla."""
    cfg = get_meta_academy_config(academia_code)
    if not cfg:
        return None, (jsonify({"error": "Academia inválida (use 'and' o 'sec')"}), 400)
    missing = [k for k in ("token", "campaign_id") if not cfg[k]]
    if missing:
        return None, (jsonify({
            "error": f"Faltan variables de entorno: {', '.join(missing)} para {cfg['name']}",
            "missing": missing,
        }), 200)
    return cfg, None


def _extract_leads(row):
    """Suma los 'actions' que correspondan a leads."""
    total = 0
    for a in (row.get("actions") or []):
        if a.get("action_type") in LEAD_ACTION_TYPES:
            try:
                total += int(float(a.get("value", 0)))
            except (ValueError, TypeError):
                pass
    return total


@app.route("/api/meta/summary/<academia>")
@login_required
def meta_summary(academia):
    cfg, err = _meta_config_or_error(academia)
    if err:
        return err

    cache_key = ("summary", academia)
    if not request.args.get("fresh"):
        cached = meta_cache_get(cache_key)
        if cached:
            return jsonify({**cached, "from_cache": True})

    # Insights HOY
    today = meta_graph_get(f"{cfg['campaign_id']}/insights", {
        "date_preset": "today",
        "fields": "impressions,reach,frequency,clicks,ctr,cpc,cpm,spend,actions",
    }, cfg["token"])
    if "error" in today:
        return jsonify({"error": today["error"].get("message", "Error Meta API")})

    # Insights AYER (solo para variación)
    yesterday = meta_graph_get(f"{cfg['campaign_id']}/insights", {
        "date_preset": "yesterday",
        "fields": "spend,actions",
    }, cfg["token"])

    # Info de la campaña (nombre, presupuesto, estado)
    camp = meta_graph_get(cfg["campaign_id"], {
        "fields": "name,status,daily_budget,lifetime_budget",
    }, cfg["token"])

    today_row = (today.get("data") or [{}])[0]
    yesterday_row = (yesterday.get("data") or [{}])[0] if "error" not in yesterday else {}

    leads_today = _extract_leads(today_row)
    leads_yesterday = _extract_leads(yesterday_row)
    spend_today = float(today_row.get("spend") or 0)
    spend_yesterday = float(yesterday_row.get("spend") or 0)
    ctr_today = float(today_row.get("ctr") or 0)
    impressions_today = int(today_row.get("impressions") or 0)
    clicks_today = int(today_row.get("clicks") or 0)

    daily_budget_raw = camp.get("daily_budget")
    daily_budget = (float(daily_budget_raw) / 100) if daily_budget_raw else None

    cpl_today = round(spend_today / leads_today, 2) if leads_today > 0 else None

    result = {
        "academia": academia,
        "campaign_name": camp.get("name", ""),
        "campaign_status": camp.get("status", ""),
        "leads_today": leads_today,
        "leads_yesterday": leads_yesterday,
        "leads_delta": leads_today - leads_yesterday,
        "spend_today": round(spend_today, 2),
        "spend_yesterday": round(spend_yesterday, 2),
        "daily_budget": daily_budget,
        "cpl_today": cpl_today,
        "ctr_today": round(ctr_today, 2),
        "impressions_today": impressions_today,
        "clicks_today": clicks_today,
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "from_cache": False,
    }
    meta_cache_set(cache_key, result)
    return jsonify(result)


@app.route("/api/meta/timeseries/<academia>")
@login_required
def meta_timeseries(academia):
    cfg, err = _meta_config_or_error(academia)
    if err:
        return err

    cache_key = ("timeseries", academia)
    if not request.args.get("fresh"):
        cached = meta_cache_get(cache_key)
        if cached:
            return jsonify({**cached, "from_cache": True})

    data = meta_graph_get(f"{cfg['campaign_id']}/insights", {
        "date_preset": "last_14d",
        "time_increment": "1",
        "fields": "impressions,clicks,spend,actions,ctr,cpc,date_start",
        "limit": "50",
    }, cfg["token"])

    if "error" in data:
        return jsonify({"error": data["error"].get("message", "Error Meta API")})

    days = []
    for row in data.get("data", []):
        leads = _extract_leads(row)
        spend = float(row.get("spend") or 0)
        days.append({
            "date": row.get("date_start"),
            "impressions": int(row.get("impressions") or 0),
            "clicks": int(row.get("clicks") or 0),
            "spend": round(spend, 2),
            "leads": leads,
            "ctr": float(row.get("ctr") or 0),
            "cpc": float(row.get("cpc") or 0),
            "cpl": round(spend / leads, 2) if leads > 0 else None,
        })
    # Ordenar por fecha asc por si Meta los devuelve al revés
    days.sort(key=lambda d: d["date"] or "")

    result = {
        "academia": academia,
        "days": days,
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "from_cache": False,
    }
    meta_cache_set(cache_key, result)
    return jsonify(result)


@app.route("/api/meta/ads/<academia>")
@login_required
def meta_ads(academia):
    cfg, err = _meta_config_or_error(academia)
    if err:
        return err

    cache_key = ("ads", academia)
    if not request.args.get("fresh"):
        cached = meta_cache_get(cache_key)
        if cached:
            return jsonify({**cached, "from_cache": True})

    # Insights por anuncio (suma 14 días por defecto)
    insights = meta_graph_get(f"{cfg['campaign_id']}/insights", {
        "level": "ad",
        "date_preset": "last_14d",
        "fields": "ad_id,ad_name,impressions,clicks,ctr,spend,actions",
        "limit": "100",
    }, cfg["token"])

    if "error" in insights:
        return jsonify({"error": insights["error"].get("message", "Error Meta API")})

    # Status de cada anuncio (otra llamada porque no viene en insights)
    ads_meta = meta_graph_get(f"{cfg['campaign_id']}/ads", {
        "fields": "id,name,status,effective_status",
        "limit": "100",
    }, cfg["token"])
    status_map = {a["id"]: a for a in (ads_meta.get("data") or [])} if "error" not in ads_meta else {}

    ads_list = []
    for row in insights.get("data", []):
        ad_id = row.get("ad_id", "")
        leads = _extract_leads(row)
        spend = float(row.get("spend") or 0)
        meta_info = status_map.get(ad_id, {})
        ads_list.append({
            "ad_id": ad_id,
            "ad_name": row.get("ad_name") or meta_info.get("name") or "(sin nombre)",
            "status": meta_info.get("effective_status") or meta_info.get("status") or "",
            "impressions": int(row.get("impressions") or 0),
            "clicks": int(row.get("clicks") or 0),
            "ctr": round(float(row.get("ctr") or 0), 2),
            "spend": round(spend, 2),
            "leads": leads,
            "cpl": round(spend / leads, 2) if leads > 0 else None,
        })

    # Si hay ads en status_map que no tienen insights (sin gasto), añadirlos vacíos
    seen_ids = {a["ad_id"] for a in ads_list}
    for ad_id, info in status_map.items():
        if ad_id not in seen_ids:
            ads_list.append({
                "ad_id": ad_id,
                "ad_name": info.get("name") or "(sin nombre)",
                "status": info.get("effective_status") or info.get("status") or "",
                "impressions": 0,
                "clicks": 0,
                "ctr": 0,
                "spend": 0,
                "leads": 0,
                "cpl": None,
            })

    ads_list.sort(key=lambda a: a["spend"], reverse=True)

    result = {
        "academia": academia,
        "ads": ads_list,
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "from_cache": False,
    }
    meta_cache_set(cache_key, result)
    return jsonify(result)


@app.route("/api/meta/historical/<academia>")
@login_required
def meta_historical(academia):
    cfg, err = _meta_config_or_error(academia)
    if err:
        return err
    if not cfg["ad_account"]:
        return jsonify({"error": f"Falta META_AD_ACCOUNT_{academia.upper()} para comparar con histórico"})

    cache_key = ("historical", academia)
    if not request.args.get("fresh"):
        cached = meta_cache_get(cache_key)
        if cached:
            return jsonify({**cached, "from_cache": True})

    # 1) Insights de TODAS las campañas de la cuenta — lifetime
    data = meta_graph_get(f"{cfg['ad_account']}/insights", {
        "level": "campaign",
        "date_preset": "maximum",
        "fields": "campaign_id,campaign_name,spend,actions,impressions,clicks,ctr",
        "limit": "200",
    }, cfg["token"])

    if "error" in data:
        return jsonify({"error": data["error"].get("message", "Error Meta API")})

    historical_rows = []
    current_row = None
    for row in data.get("data", []):
        if row.get("campaign_id") == cfg["campaign_id"]:
            current_row = row
        else:
            historical_rows.append(row)

    # Agregar histórico (todas las campañas excepto la actual)
    h_spend = sum(float(r.get("spend") or 0) for r in historical_rows)
    h_leads = sum(_extract_leads(r) for r in historical_rows)
    h_impressions = sum(int(r.get("impressions") or 0) for r in historical_rows)
    h_clicks = sum(int(r.get("clicks") or 0) for r in historical_rows)
    h_cpl = (h_spend / h_leads) if h_leads > 0 else None
    h_ctr = (h_clicks / h_impressions * 100) if h_impressions > 0 else None

    # Si la actual no aparece (raro pero posible si está sin gasto), pedirla directa
    if current_row is None:
        cur = meta_graph_get(f"{cfg['campaign_id']}/insights", {
            "date_preset": "maximum",
            "fields": "spend,actions,impressions,clicks,ctr,campaign_name",
        }, cfg["token"])
        if "error" not in cur:
            current_row = (cur.get("data") or [{}])[0]
        else:
            current_row = {}

    c_spend = float(current_row.get("spend") or 0)
    c_leads = _extract_leads(current_row)
    c_impressions = int(current_row.get("impressions") or 0)
    c_clicks = int(current_row.get("clicks") or 0)
    c_cpl = (c_spend / c_leads) if c_leads > 0 else None
    c_ctr = (c_clicks / c_impressions * 100) if c_impressions > 0 else None

    # Mejora (% relativo)
    #   CPL: menos es mejor → mejora = (h - c) / h * 100, positivo = mejor
    #   CTR: más es mejor → mejora = (c - h) / h * 100, positivo = mejor
    cpl_improvement = None
    if h_cpl is not None and c_cpl is not None and h_cpl > 0:
        cpl_improvement = (h_cpl - c_cpl) / h_cpl * 100
    ctr_improvement = None
    if h_ctr is not None and c_ctr is not None and h_ctr > 0:
        ctr_improvement = (c_ctr - h_ctr) / h_ctr * 100

    # Texto explicativo (lenguaje plano). Si hay mejora CPL,
    # calcula cuántos leads/100€ obtienes ahora vs antes.
    leads_per_100_old = (100 / h_cpl) if h_cpl else None
    leads_per_100_new = (100 / c_cpl) if c_cpl else None

    result = {
        "has_historical": (h_leads > 0 and h_cpl is not None),
        "historical": {
            "spend": round(h_spend, 2),
            "leads": h_leads,
            "cpl": round(h_cpl, 2) if h_cpl else None,
            "ctr": round(h_ctr, 2) if h_ctr else None,
            "campaigns_count": len(historical_rows),
        },
        "current": {
            "spend": round(c_spend, 2),
            "leads": c_leads,
            "cpl": round(c_cpl, 2) if c_cpl else None,
            "ctr": round(c_ctr, 2) if c_ctr else None,
            "campaign_name": current_row.get("campaign_name", ""),
        },
        "improvement": {
            "cpl_pct": round(cpl_improvement, 1) if cpl_improvement is not None else None,
            "ctr_pct": round(ctr_improvement, 1) if ctr_improvement is not None else None,
        },
        "leads_per_100_eur": {
            "old": round(leads_per_100_old, 1) if leads_per_100_old else None,
            "new": round(leads_per_100_new, 1) if leads_per_100_new else None,
        },
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "from_cache": False,
    }
    meta_cache_set(cache_key, result)
    return jsonify(result)


@app.route("/api/meta/ad/<ad_id>/creative")
@login_required
def meta_ad_creative(ad_id):
    aca = request.args.get("academia", "and")
    cfg, err = _meta_config_or_error(aca)
    if err:
        return err

    cache_key = ("creative", ad_id)
    cached = meta_cache_get(cache_key)
    if cached:
        return jsonify({**cached, "from_cache": True})

    # Obtener creative del ad
    creative_resp = meta_graph_get(ad_id, {
        "fields": "creative{id,object_story_spec,image_url,thumbnail_url}",
    }, cfg["token"])

    if "error" in creative_resp:
        return jsonify({"error": creative_resp["error"].get("message", "Error Meta API")})

    cre = creative_resp.get("creative") or {}
    image_url = cre.get("image_url") or cre.get("thumbnail_url")

    if not image_url:
        spec = cre.get("object_story_spec") or {}
        link_data = spec.get("link_data") or {}
        image_hash = link_data.get("image_hash")
        video_data = spec.get("video_data") or {}
        image_url = video_data.get("image_url") or video_data.get("thumbnail_url")

        if not image_url and image_hash and cfg["ad_account"]:
            images = meta_graph_get(f"{cfg['ad_account']}/adimages", {
                "hashes": json.dumps([image_hash]),
                "fields": "url,permalink_url,hash",
            }, cfg["token"])
            for img in (images.get("data") or []):
                image_url = img.get("permalink_url") or img.get("url")
                if image_url:
                    break

    result = {"image_url": image_url, "creative_id": cre.get("id")}
    meta_cache_set(cache_key, result)
    return jsonify(result)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, port=port)
