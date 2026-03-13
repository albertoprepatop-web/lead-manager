import csv
import io
import os
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request, Response
from flask_cors import CORS
from models import db, Lead, Seguimiento, NotaActividad, Alumno, ACADEMIAS, ESTADOS
from database import seed_database

app = Flask(__name__)

# Database: PostgreSQL in production (Railway), SQLite locally
db_url = os.environ.get('DATABASE_URL', 'sqlite:///leads.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

CORS(app)
db.init_app(app)

with app.app_context():
    db.create_all()
    seed_database()


# ── Pages ──────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ── Dashboard ──────────────────────────────────────────────────────────────

@app.route('/api/dashboard')
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

    return jsonify({
        'total_leads': total,
        'nuevos_semana': nuevos_semana,
        'total_alumnos': total_alumnos,
        'seguimientos_pendientes': seguimientos_pendientes,
        'por_academia': por_academia,
        'por_mes': por_mes,
        'seguimientos_proximos': [s.to_dict() for s in seguimientos_proximos],
    })


# ── Leads CRUD ─────────────────────────────────────────────────────────────

@app.route('/api/leads')
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
        notas=data.get('notas', ''),
    )
    db.session.add(lead)
    db.session.commit()
    return jsonify(lead.to_dict()), 201


@app.route('/api/leads/<int:lead_id>')
def get_lead(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    data = lead.to_dict()
    data['seguimientos'] = [s.to_dict() for s in lead.seguimientos]
    data['notas_actividad'] = [n.to_dict() for n in sorted(lead.notas_actividad, key=lambda x: x.created_at, reverse=True)]
    return jsonify(data)


@app.route('/api/leads/<int:lead_id>', methods=['PUT'])
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
    if 'estado' in data:
        if data['estado'] not in ESTADOS:
            return jsonify({'error': f'Estado no valido'}), 400
        lead.estado = data['estado']
    if 'notas' in data:
        lead.notas = data['notas']

    lead.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(lead.to_dict())


@app.route('/api/leads/<int:lead_id>', methods=['DELETE'])
def delete_lead(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    db.session.delete(lead)
    db.session.commit()
    return jsonify({'message': 'Lead eliminado'})


# ── Matriculacion: Lead -> Alumno ──────────────────────────────────────────

@app.route('/api/leads/<int:lead_id>/matricular', methods=['POST'])
def matricular_lead(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    data = request.get_json() or {}

    alumno = Alumno(
        nombre=lead.nombre,
        telefono=lead.telefono,
        email=lead.email,
        academia=lead.academia,
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
def get_alumno(alumno_id):
    alumno = Alumno.query.get_or_404(alumno_id)
    return jsonify(alumno.to_dict())


@app.route('/api/alumnos/<int:alumno_id>', methods=['PUT'])
def update_alumno(alumno_id):
    alumno = Alumno.query.get_or_404(alumno_id)
    data = request.get_json()

    for field in ['nombre', 'telefono', 'email', 'curso', 'modalidad', 'estado_pago', 'notas']:
        if field in data:
            setattr(alumno, field, data[field])

    alumno.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(alumno.to_dict())


@app.route('/api/alumnos/<int:alumno_id>', methods=['DELETE'])
def delete_alumno(alumno_id):
    alumno = Alumno.query.get_or_404(alumno_id)
    db.session.delete(alumno)
    db.session.commit()
    return jsonify({'message': 'Alumno eliminado'})


# ── Seguimientos ───────────────────────────────────────────────────────────

@app.route('/api/seguimientos')
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
def delete_seguimiento(seg_id):
    seg = Seguimiento.query.get_or_404(seg_id)
    db.session.delete(seg)
    db.session.commit()
    return jsonify({'message': 'Seguimiento eliminado'})


# ── Notas de Actividad ────────────────────────────────────────────────────

@app.route('/api/notas', methods=['POST'])
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
def get_notas_lead(lead_id):
    Lead.query.get_or_404(lead_id)
    notas = NotaActividad.query.filter_by(lead_id=lead_id).order_by(
        NotaActividad.created_at.desc()
    ).all()
    return jsonify([n.to_dict() for n in notas])


# ── Export CSV ─────────────────────────────────────────────────────────────

@app.route('/api/export/csv')
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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, port=port)
