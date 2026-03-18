import csv
import io
import os
import functools
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request, Response, session, redirect, url_for
from flask_cors import CORS
from models import db, Lead, Seguimiento, NotaActividad, Alumno, Pago, MesActivo, ACADEMIAS, ESTADOS, SOCIOS
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
    # Auto-migrate: add cuota column if missing
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)
        columns = [c['name'] for c in inspector.get_columns('alumnos')]
        if 'cuota' not in columns:
            db.session.execute(text('ALTER TABLE alumnos ADD COLUMN cuota FLOAT DEFAULT 0'))
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
    total_alumnos = Alumno.query.count()
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
        alumnos_ac = Alumno.query.filter_by(academia=academia).count()
        por_academia[academia] = {
            'total': total_ac,
            'por_estado': por_estado,
            'alumnos': alumnos_ac,
        }

    # Leads por mes (ultimos 6 meses)
    por_mes = []
    for i in range(5, -1, -1):
        mes_inicio = (now.replace(day=1) - timedelta(days=30 * i)).replace(day=1)
        if i > 0:
            mes_fin = (now.replace(day=1) - timedelta(days=30 * (i - 1))).replace(day=1)
        else:
            mes_fin = now + timedelta(days=1)
        count = Lead.query.filter(
            Lead.created_at >= mes_inicio,
            Lead.created_at < mes_fin
        ).count()
        por_mes.append({
            'mes': mes_inicio.strftime('%b %Y'),
            'count': count,
        })

    # Seguimientos proximos
    seguimientos_proximos = Seguimiento.query.filter(
        Seguimiento.completado == False
    ).order_by(Seguimiento.fecha.asc()).limit(10).all()

    # Alumnos por mes (ultimos 6 meses)
    alumnos_por_mes = []
    for i in range(5, -1, -1):
        mes_inicio = (now.replace(day=1) - timedelta(days=30 * i)).replace(day=1)
        if i > 0:
            mes_fin = (now.replace(day=1) - timedelta(days=30 * (i - 1))).replace(day=1)
        else:
            mes_fin = now + timedelta(days=1)
        count = Alumno.query.filter(
            Alumno.fecha_matricula >= mes_inicio,
            Alumno.fecha_matricula < mes_fin
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

    return jsonify({
        'total_leads': total,
        'nuevos_semana': nuevos_semana,
        'total_alumnos': total_alumnos,
        'seguimientos_pendientes': seguimientos_pendientes,
        'por_academia': por_academia,
        'por_mes': por_mes,
        'alumnos_por_mes': alumnos_por_mes,
        'por_especialidad': por_especialidad,
        'seguimientos_proximos': [s.to_dict() for s in seguimientos_proximos],
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
    return jsonify([l.to_dict() for l in leads])


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

    for field in ['nombre', 'telefono', 'email', 'especialidad', 'curso', 'modalidad', 'estado_pago', 'notas']:
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

    # Build response
    alumnos_data = []
    for a in alumnos:
        alumnos_data.append({
            'id': a.id,
            'nombre': a.nombre,
            'cuota': a.cuota or 0,
            'pagos': pagos_map.get(a.id, {}),
        })

    # Totals per month
    totales = {}
    for mes in meses_list:
        efectivo = sum(p.cantidad for p in pagos if p.mes == mes and p.metodo == 'efectivo')
        recibo = sum(p.cantidad for p in pagos if p.mes == mes and p.metodo == 'recibo')
        totales[mes] = {'efectivo': efectivo, 'recibo': recibo, 'total': efectivo + recibo}

    return jsonify({
        'meses': meses_list,
        'alumnos': alumnos_data,
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
    # Get all cash payments grouped by recogido_por
    pagos_efectivo = Pago.query.filter_by(metodo='efectivo').all()

    socios_data = {}
    for socio in SOCIOS:
        pagos_socio = [p for p in pagos_efectivo if p.recogido_por == socio]
        total = sum(p.cantidad for p in pagos_socio)

        # Group by month
        por_mes = {}
        for p in pagos_socio:
            if p.mes not in por_mes:
                por_mes[p.mes] = 0
            por_mes[p.mes] += p.cantidad

        socios_data[socio] = {
            'total': total,
            'por_mes': por_mes,
        }

    # Get all active months across all academies
    meses = MesActivo.query.order_by(MesActivo.mes.asc()).all()
    meses_unicos = sorted(set(m.mes for m in meses))

    return jsonify({
        'socios': socios_data,
        'meses': meses_unicos,
    })


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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, port=port)
