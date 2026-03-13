// ── State ──────────────────────────────────────────────────────────────────
let currentView = 'dashboard';
let currentAcademia = ''; // '' = General
let currentLeadId = null;
let chartEstados = null;
let chartMeses = null;

const ACADEMIA_COLORS = {
    PREPATOP: '#2563EB',
    PREPARASECUNDARIA: '#16A34A',
    PREPARAANDALUCIA: '#EA580C',
};

const ESTADO_LABELS = {
    nuevo: 'Nuevo',
    contactado: 'Contactado',
    no_coge: 'No Coge',
    interesado: 'Interesado',
    a_espera_de_pago: 'Espera Pago',
    matriculado: 'Matriculado',
    perdido: 'Perdido',
};

const TIPO_ICONS = {
    llamada: 'bi-telephone',
    email: 'bi-envelope',
    reunion: 'bi-camera-video',
    otro: 'bi-chat-dots',
};

// ── Init ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    switchAcademia('');
    document.getElementById('filter-busqueda').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') loadLeads();
    });
    document.getElementById('filter-alumnos-busqueda').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') loadAlumnos();
    });
});

// ── Academy Navigation ────────────────────────────────────────────────────
function switchAcademia(academia) {
    currentAcademia = academia;

    // Update academy tab styling
    document.querySelectorAll('.academy-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.academia === academia);
    });

    // Show correct sub-tabs
    if (academia === '') {
        document.getElementById('subtabs-general').style.display = 'flex';
        document.getElementById('subtabs-academia').style.display = 'none';
        showView('dashboard');
    } else {
        document.getElementById('subtabs-general').style.display = 'none';
        document.getElementById('subtabs-academia').style.display = 'flex';
        showView('leads');
    }
}

// ── View Navigation ───────────────────────────────────────────────────────
function showView(view) {
    currentView = view;
    document.querySelectorAll('[id^="view-"]').forEach(el => el.style.display = 'none');
    document.getElementById(`view-${view}`).style.display = 'block';

    // Update sub-tab styling
    const group = currentAcademia === '' ? 'subtabs-general' : 'subtabs-academia';
    document.querySelectorAll(`#${group} .sub-tab`).forEach(tab => {
        tab.classList.remove('active');
    });
    // Find the matching sub-tab
    document.querySelectorAll(`#${group} .sub-tab`).forEach(tab => {
        if (tab.onclick && tab.onclick.toString().includes(`'${view}'`)) {
            tab.classList.add('active');
        }
    });

    // Load data
    if (view === 'dashboard') loadDashboard();
    else if (view === 'leads') loadLeads();
    else if (view === 'pipeline') loadPipeline();
    else if (view === 'alumnos') loadAlumnos();
    else if (view === 'seguimientos') loadSeguimientos();
}

// ── API Helper ────────────────────────────────────────────────────────────
async function api(url, options = {}) {
    if (options.body && typeof options.body === 'object') {
        options.body = JSON.stringify(options.body);
        options.headers = { 'Content-Type': 'application/json', ...options.headers };
    }
    const res = await fetch(url, options);
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `Error ${res.status}`);
    }
    if (res.headers.get('content-type')?.includes('json')) {
        return res.json();
    }
    return res;
}

// ── Dashboard ─────────────────────────────────────────────────────────────
async function loadDashboard() {
    const data = await api('/api/dashboard');

    document.getElementById('kpi-total').textContent = data.total_leads;
    document.getElementById('kpi-nuevos').textContent = data.nuevos_semana;
    document.getElementById('kpi-alumnos').textContent = data.total_alumnos;
    document.getElementById('kpi-seguimientos').textContent = data.seguimientos_pendientes;

    for (const [academia, info] of Object.entries(data.por_academia)) {
        const key = academia.toLowerCase();
        document.getElementById(`ac-${key}-total`).textContent = info.total;
        document.getElementById(`ac-${key}-alumnos`).textContent = info.alumnos;
        const estadosEl = document.getElementById(`ac-${key}-estados`);
        estadosEl.innerHTML = Object.entries(info.por_estado).map(([estado, count]) =>
            `<div class="estado-mini"><span>${ESTADO_LABELS[estado] || estado}</span><span class="count">${count}</span></div>`
        ).join('');
    }

    renderChartEstados(data.por_academia);
    renderChartMeses(data.por_mes);

    const tbody = document.getElementById('dashboard-seguimientos');
    if (data.seguimientos_proximos.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3">No hay seguimientos pendientes</td></tr>';
    } else {
        tbody.innerHTML = data.seguimientos_proximos.map(s => {
            const fecha = new Date(s.fecha);
            const now = new Date();
            const rowClass = fecha < now ? 'seg-vencido' : fecha.toDateString() === now.toDateString() ? 'seg-hoy' : '';
            return `<tr class="${rowClass}">
                <td>${formatDate(s.fecha)}</td>
                <td><a href="#" onclick="openLeadDetail(${s.lead_id}); return false;">${s.lead_nombre}</a></td>
                <td><span class="badge badge-${s.lead_academia?.toLowerCase()}">${s.lead_academia}</span></td>
                <td>${s.nota}</td>
                <td><button class="btn btn-sm btn-outline-success btn-action" onclick="completeSeguimiento(${s.id})"><i class="bi bi-check-lg"></i></button></td>
            </tr>`;
        }).join('');
    }
}

function renderChartEstados(porAcademia) {
    const ctx = document.getElementById('chart-estados').getContext('2d');
    if (chartEstados) chartEstados.destroy();
    const estados = Object.keys(ESTADO_LABELS);
    const datasets = Object.entries(porAcademia).map(([academia, info]) => ({
        label: academia,
        data: estados.map(e => info.por_estado[e] || 0),
        backgroundColor: ACADEMIA_COLORS[academia],
    }));
    chartEstados = new Chart(ctx, {
        type: 'bar',
        data: { labels: estados.map(e => ESTADO_LABELS[e]), datasets },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top' } }, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } } },
    });
}

function renderChartMeses(porMes) {
    const ctx = document.getElementById('chart-meses').getContext('2d');
    if (chartMeses) chartMeses.destroy();
    chartMeses = new Chart(ctx, {
        type: 'line',
        data: {
            labels: porMes.map(m => m.mes),
            datasets: [{ label: 'Nuevos Leads', data: porMes.map(m => m.count), borderColor: '#2563EB', backgroundColor: 'rgba(37,99,235,0.1)', fill: true, tension: 0.3 }],
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } } },
    });
}

// ── Leads ─────────────────────────────────────────────────────────────────
async function loadLeads() {
    const params = new URLSearchParams();

    // If we're in an academy tab, force the filter
    if (currentAcademia) {
        params.set('academia', currentAcademia);
        document.getElementById('leads-title').innerHTML = `<i class="bi bi-people"></i> Leads - ${currentAcademia}`;
    } else {
        document.getElementById('leads-title').innerHTML = `<i class="bi bi-people"></i> Todos los Leads`;
    }

    const busqueda = document.getElementById('filter-busqueda').value;
    const estado = document.getElementById('filter-estado').value;
    const desde = document.getElementById('filter-desde').value;
    const hasta = document.getElementById('filter-hasta').value;

    if (busqueda) params.set('busqueda', busqueda);
    if (estado) params.set('estado', estado);
    if (desde) params.set('fecha_desde', desde);
    if (hasta) params.set('fecha_hasta', hasta);

    const leads = await api(`/api/leads?${params}`);
    document.getElementById('leads-count').textContent = `${leads.length} leads`;

    const tbody = document.getElementById('leads-table');
    if (leads.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4">No se encontraron leads</td></tr>';
        return;
    }

    const showAcademia = !currentAcademia;
    tbody.innerHTML = leads.map(l => `
        <tr>
            <td><a href="#" onclick="openLeadDetail(${l.id}); return false;" class="fw-bold text-decoration-none">${l.nombre}</a></td>
            <td>${l.telefono || '-'}</td>
            <td>${l.email || '-'}</td>
            <td>${showAcademia ? `<span class="badge badge-${l.academia.toLowerCase()}">${l.academia}</span>` : ''}</td>
            <td>
                <select class="form-select form-select-sm d-inline-block w-auto" onchange="quickChangeEstado(${l.id}, this.value)" style="font-size:0.75rem; padding: 0.1rem 1.5rem 0.1rem 0.4rem;">
                    ${Object.entries(ESTADO_LABELS).map(([k, v]) => `<option value="${k}" ${k === l.estado ? 'selected' : ''}>${v}</option>`).join('')}
                </select>
            </td>
            <td class="text-muted" style="font-size:0.8rem">${formatDate(l.created_at)}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary btn-action" onclick="openLeadModal(${l.id})" title="Editar"><i class="bi bi-pencil"></i></button>
                <button class="btn btn-sm btn-outline-danger btn-action" onclick="confirmDeleteLead(${l.id})" title="Eliminar"><i class="bi bi-trash"></i></button>
            </td>
        </tr>
    `).join('');
}

function clearFilters() {
    document.getElementById('filter-busqueda').value = '';
    document.getElementById('filter-estado').value = '';
    document.getElementById('filter-desde').value = '';
    document.getElementById('filter-hasta').value = '';
    loadLeads();
}

async function quickChangeEstado(id, estado) {
    await api(`/api/leads/${id}`, { method: 'PUT', body: { estado } });
}

function exportCSV() {
    const params = new URLSearchParams();
    if (currentAcademia) params.set('academia', currentAcademia);
    const estado = document.getElementById('filter-estado').value;
    if (estado) params.set('estado', estado);
    window.open(`/api/export/csv?${params}`, '_blank');
}

// ── Lead Modal (Create/Edit) ──────────────────────────────────────────────
async function openLeadModal(id = null) {
    const modal = new bootstrap.Modal(document.getElementById('leadModal'));
    document.getElementById('leadModalTitle').textContent = id ? 'Editar Lead' : 'Nuevo Lead';
    document.getElementById('lead-id').value = id || '';

    // If in academy context, pre-select and hide the academia field
    if (currentAcademia && !id) {
        document.getElementById('lead-academia').value = currentAcademia;
        document.getElementById('lead-academia-group').style.display = 'none';
    } else {
        document.getElementById('lead-academia-group').style.display = 'block';
    }

    if (id) {
        const lead = await api(`/api/leads/${id}`);
        document.getElementById('lead-nombre').value = lead.nombre;
        document.getElementById('lead-telefono').value = lead.telefono;
        document.getElementById('lead-email').value = lead.email;
        document.getElementById('lead-academia').value = lead.academia;
        document.getElementById('lead-estado').value = lead.estado;
        document.getElementById('lead-notas').value = lead.notas;
    } else {
        document.getElementById('lead-nombre').value = '';
        document.getElementById('lead-telefono').value = '';
        document.getElementById('lead-email').value = '';
        document.getElementById('lead-estado').value = 'nuevo';
        document.getElementById('lead-notas').value = '';
    }

    modal.show();
}

async function saveLead() {
    const id = document.getElementById('lead-id').value;
    const data = {
        nombre: document.getElementById('lead-nombre').value.trim(),
        telefono: document.getElementById('lead-telefono').value.trim(),
        email: document.getElementById('lead-email').value.trim(),
        academia: document.getElementById('lead-academia').value,
        estado: document.getElementById('lead-estado').value,
        notas: document.getElementById('lead-notas').value.trim(),
    };

    if (!data.nombre) { alert('El nombre es obligatorio'); return; }

    if (id) {
        await api(`/api/leads/${id}`, { method: 'PUT', body: data });
    } else {
        await api('/api/leads', { method: 'POST', body: data });
    }

    bootstrap.Modal.getInstance(document.getElementById('leadModal')).hide();
    refreshCurrentView();
}

// ── Delete Lead ───────────────────────────────────────────────────────────
function confirmDeleteLead(id) {
    const modal = new bootstrap.Modal(document.getElementById('deleteModal'));
    document.getElementById('delete-message').textContent = 'Estas seguro de que quieres eliminar este lead? Esta accion no se puede deshacer.';
    document.getElementById('btn-confirm-delete').onclick = async () => {
        await api(`/api/leads/${id}`, { method: 'DELETE' });
        bootstrap.Modal.getInstance(document.getElementById('deleteModal')).hide();
        refreshCurrentView();
    };
    modal.show();
}

// ── Lead Detail (Offcanvas) ───────────────────────────────────────────────
async function openLeadDetail(id) {
    currentLeadId = id;
    const lead = await api(`/api/leads/${id}`);

    document.getElementById('detail-nombre').textContent = lead.nombre;
    document.getElementById('detail-tel').href = `tel:${lead.telefono}`;
    document.getElementById('detail-email').href = `mailto:${lead.email}`;
    document.getElementById('detail-estado-select').value = lead.estado;

    // Hide matricular/pagado buttons based on state
    document.getElementById('btn-matricular').style.display = lead.estado === 'matriculado' ? 'none' : 'inline-block';
    document.getElementById('btn-pagado').style.display = (lead.estado === 'a_espera_de_pago' || lead.estado === 'interesado') ? 'inline-block' : 'none';

    document.getElementById('detail-info').innerHTML = `
        <div class="mb-1"><i class="bi bi-telephone me-2"></i>${lead.telefono || '-'}</div>
        <div class="mb-1"><i class="bi bi-envelope me-2"></i>${lead.email || '-'}</div>
        <div class="mb-1"><i class="bi bi-building me-2"></i><span class="badge badge-${lead.academia.toLowerCase()}">${lead.academia}</span></div>
        <div class="mb-1"><i class="bi bi-clock me-2"></i>Creado: ${formatDate(lead.created_at)}</div>
        ${lead.notas ? `<div class="mt-2 p-2 bg-light rounded"><small>${lead.notas}</small></div>` : ''}
    `;

    // Seguimientos
    const segEl = document.getElementById('detail-seguimientos');
    if (lead.seguimientos.length === 0) {
        segEl.innerHTML = '<div class="p-3 text-center text-muted">Sin seguimientos</div>';
    } else {
        segEl.innerHTML = lead.seguimientos.sort((a, b) => new Date(a.fecha) - new Date(b.fecha)).map(s => {
            const vencido = !s.completado && new Date(s.fecha) < new Date();
            return `<div class="list-group-item ${s.completado ? 'text-decoration-line-through text-muted' : vencido ? 'list-group-item-danger' : ''}">
                <div class="d-flex justify-content-between align-items-center">
                    <div><small class="fw-bold">${formatDate(s.fecha)}</small><div>${s.nota}</div></div>
                    <div>${!s.completado ? `<button class="btn btn-sm btn-outline-success btn-action" onclick="completeSeguimiento(${s.id})"><i class="bi bi-check-lg"></i></button>` : '<i class="bi bi-check-circle text-success"></i>'}</div>
                </div>
            </div>`;
        }).join('');
    }

    // Notas actividad
    const notasEl = document.getElementById('detail-notas');
    if (lead.notas_actividad.length === 0) {
        notasEl.innerHTML = '<div class="p-3 text-center text-muted">Sin actividad registrada</div>';
    } else {
        notasEl.innerHTML = lead.notas_actividad.map(n => `
            <div class="activity-item tipo-${n.tipo}">
                <div class="d-flex justify-content-between">
                    <span class="activity-tipo">${n.tipo} <i class="bi ${TIPO_ICONS[n.tipo]}"></i></span>
                    <span class="activity-date">${formatDate(n.created_at)}</span>
                </div>
                <div>${n.contenido}</div>
            </div>
        `).join('');
    }

    new bootstrap.Offcanvas(document.getElementById('leadDetail')).show();
}

async function changeLeadEstado() {
    const estado = document.getElementById('detail-estado-select').value;
    await api(`/api/leads/${currentLeadId}`, { method: 'PUT', body: { estado } });
    openLeadDetail(currentLeadId);
}

async function addNota() {
    const tipo = document.getElementById('nueva-nota-tipo').value;
    const contenido = document.getElementById('nueva-nota-contenido').value.trim();
    if (!contenido) { alert('Escribe el contenido de la actividad'); return; }

    await api('/api/notas', { method: 'POST', body: { lead_id: currentLeadId, tipo, contenido } });
    document.getElementById('nueva-nota-contenido').value = '';
    openLeadDetail(currentLeadId);
}

// ── Matriculacion ─────────────────────────────────────────────────────────
function openMatriculaModal() {
    document.getElementById('matricula-curso').value = '';
    document.getElementById('matricula-modalidad').value = 'presencial';
    document.getElementById('matricula-pago').value = 'pendiente';
    document.getElementById('matricula-notas').value = '';
    new bootstrap.Modal(document.getElementById('matriculaModal')).show();
}

async function matricularLead() {
    const curso = document.getElementById('matricula-curso').value.trim();
    if (!curso) { alert('El curso es obligatorio'); return; }

    const data = {
        curso,
        modalidad: document.getElementById('matricula-modalidad').value,
        estado_pago: document.getElementById('matricula-pago').value,
        notas: document.getElementById('matricula-notas').value.trim(),
    };

    await api(`/api/leads/${currentLeadId}/matricular`, { method: 'POST', body: data });

    bootstrap.Modal.getInstance(document.getElementById('matriculaModal')).hide();
    bootstrap.Offcanvas.getInstance(document.getElementById('leadDetail'))?.hide();

    alert('Lead matriculado correctamente! Ahora aparece en la seccion Alumnos.');
    refreshCurrentView();
}

// ── Pagado (auto-matriculacion) ──────────────────────────────────────────
function openPagadoModal() {
    document.getElementById('pagado-curso').value = '';
    document.getElementById('pagado-modalidad').value = 'presencial';
    document.getElementById('pagado-notas').value = '';
    new bootstrap.Modal(document.getElementById('pagadoModal')).show();
}

async function marcarPagado() {
    const curso = document.getElementById('pagado-curso').value.trim();
    if (!curso) { alert('El curso es obligatorio'); return; }

    const data = {
        curso,
        modalidad: document.getElementById('pagado-modalidad').value,
        notas: document.getElementById('pagado-notas').value.trim(),
    };

    await api(`/api/leads/${currentLeadId}/pagado`, { method: 'POST', body: data });

    bootstrap.Modal.getInstance(document.getElementById('pagadoModal')).hide();
    bootstrap.Offcanvas.getInstance(document.getElementById('leadDetail'))?.hide();

    alert('Pago registrado! El lead ha sido matriculado automaticamente.');
    refreshCurrentView();
}

// ── Alumnos ───────────────────────────────────────────────────────────────
async function loadAlumnos() {
    const params = new URLSearchParams();

    if (currentAcademia) {
        params.set('academia', currentAcademia);
        document.getElementById('alumnos-title').innerHTML = `<i class="bi bi-person-check"></i> Alumnos - ${currentAcademia}`;
    } else {
        document.getElementById('alumnos-title').innerHTML = `<i class="bi bi-person-check"></i> Todos los Alumnos`;
    }

    const busqueda = document.getElementById('filter-alumnos-busqueda').value;
    const pago = document.getElementById('filter-alumnos-pago').value;

    if (busqueda) params.set('busqueda', busqueda);
    if (pago) params.set('estado_pago', pago);

    const alumnos = await api(`/api/alumnos?${params}`);
    document.getElementById('alumnos-count').textContent = `${alumnos.length} alumnos`;

    const tbody = document.getElementById('alumnos-table');
    if (alumnos.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">No se encontraron alumnos</td></tr>';
        return;
    }

    const showAcademia = !currentAcademia;
    tbody.innerHTML = alumnos.map(a => `
        <tr>
            <td class="fw-bold">${a.nombre}</td>
            <td>${a.telefono || '-'}</td>
            <td>${a.email || '-'}</td>
            <td>${showAcademia ? `<span class="badge badge-${a.academia.toLowerCase()}">${a.academia}</span>` : ''}</td>
            <td>${a.curso}</td>
            <td><span class="badge bg-secondary">${a.modalidad}</span></td>
            <td><span class="badge badge-pago-${a.estado_pago}">${a.estado_pago}</span></td>
            <td class="text-muted" style="font-size:0.8rem">${formatDate(a.fecha_matricula)}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary btn-action" onclick="openAlumnoModal(${a.id})" title="Editar"><i class="bi bi-pencil"></i></button>
                <button class="btn btn-sm btn-outline-danger btn-action" onclick="confirmDeleteAlumno(${a.id})" title="Eliminar"><i class="bi bi-trash"></i></button>
            </td>
        </tr>
    `).join('');
}

function clearAlumnosFilters() {
    document.getElementById('filter-alumnos-busqueda').value = '';
    document.getElementById('filter-alumnos-pago').value = '';
    loadAlumnos();
}

function exportAlumnosCSV() {
    const params = new URLSearchParams();
    if (currentAcademia) params.set('academia', currentAcademia);
    window.open(`/api/export/alumnos/csv?${params}`, '_blank');
}

async function openAlumnoModal(id) {
    const alumno = await api(`/api/alumnos/${id}`);
    document.getElementById('alumno-id').value = alumno.id;
    document.getElementById('alumno-nombre').value = alumno.nombre;
    document.getElementById('alumno-telefono').value = alumno.telefono;
    document.getElementById('alumno-email').value = alumno.email;
    document.getElementById('alumno-curso').value = alumno.curso;
    document.getElementById('alumno-modalidad').value = alumno.modalidad;
    document.getElementById('alumno-pago').value = alumno.estado_pago;
    document.getElementById('alumno-notas').value = alumno.notas;
    new bootstrap.Modal(document.getElementById('alumnoModal')).show();
}

async function saveAlumno() {
    const id = document.getElementById('alumno-id').value;
    const data = {
        nombre: document.getElementById('alumno-nombre').value.trim(),
        telefono: document.getElementById('alumno-telefono').value.trim(),
        email: document.getElementById('alumno-email').value.trim(),
        curso: document.getElementById('alumno-curso').value.trim(),
        modalidad: document.getElementById('alumno-modalidad').value,
        estado_pago: document.getElementById('alumno-pago').value,
        notas: document.getElementById('alumno-notas').value.trim(),
    };

    await api(`/api/alumnos/${id}`, { method: 'PUT', body: data });
    bootstrap.Modal.getInstance(document.getElementById('alumnoModal')).hide();
    loadAlumnos();
}

function confirmDeleteAlumno(id) {
    const modal = new bootstrap.Modal(document.getElementById('deleteModal'));
    document.getElementById('delete-message').textContent = 'Estas seguro de que quieres eliminar este alumno?';
    document.getElementById('btn-confirm-delete').onclick = async () => {
        await api(`/api/alumnos/${id}`, { method: 'DELETE' });
        bootstrap.Modal.getInstance(document.getElementById('deleteModal')).hide();
        loadAlumnos();
    };
    modal.show();
}

// ── Seguimientos ──────────────────────────────────────────────────────────
async function loadSeguimientos() {
    const pendientes = document.getElementById('filter-pendientes').checked;
    const params = new URLSearchParams();
    if (pendientes) params.set('pendientes', 'true');
    if (currentAcademia) {
        params.set('academia', currentAcademia);
        document.getElementById('seguimientos-title').innerHTML = `<i class="bi bi-calendar-check"></i> Seguimientos - ${currentAcademia}`;
    } else {
        document.getElementById('seguimientos-title').innerHTML = `<i class="bi bi-calendar-check"></i> Todos los Seguimientos`;
    }

    const seguimientos = await api(`/api/seguimientos?${params}`);
    const tbody = document.getElementById('seguimientos-table');
    if (seguimientos.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">No hay seguimientos</td></tr>';
        return;
    }

    const now = new Date();
    tbody.innerHTML = seguimientos.map(s => {
        const fecha = new Date(s.fecha);
        const isVencido = !s.completado && fecha < now;
        const isHoy = fecha.toDateString() === now.toDateString();
        const rowClass = isVencido ? 'seg-vencido' : isHoy ? 'seg-hoy' : '';
        return `<tr class="${rowClass}">
            <td>${s.completado ? '<span class="badge bg-success">Completado</span>'
                : isVencido ? '<span class="badge bg-danger">Vencido</span>'
                : isHoy ? '<span class="badge bg-warning text-dark">Hoy</span>'
                : '<span class="badge bg-secondary">Pendiente</span>'}</td>
            <td>${formatDate(s.fecha)}</td>
            <td><a href="#" onclick="openLeadDetail(${s.lead_id}); return false;">${s.lead_nombre}</a></td>
            <td><span class="badge badge-${s.lead_academia?.toLowerCase()}">${s.lead_academia}</span></td>
            <td>${s.nota}</td>
            <td>
                ${!s.completado ? `<button class="btn btn-sm btn-outline-success btn-action" onclick="completeSeguimiento(${s.id})"><i class="bi bi-check-lg"></i></button>` : ''}
                <button class="btn btn-sm btn-outline-danger btn-action" onclick="deleteSeguimiento(${s.id})"><i class="bi bi-trash"></i></button>
            </td>
        </tr>`;
    }).join('');
}

function openSeguimientoModal() {
    const now = new Date();
    now.setDate(now.getDate() + 1);
    now.setHours(10, 0, 0, 0);
    document.getElementById('seg-fecha').value = now.toISOString().slice(0, 16);
    document.getElementById('seg-nota').value = '';
    new bootstrap.Modal(document.getElementById('seguimientoModal')).show();
}

async function saveSeguimiento() {
    const fecha = document.getElementById('seg-fecha').value;
    const nota = document.getElementById('seg-nota').value.trim();
    if (!fecha) { alert('Selecciona una fecha'); return; }

    await api('/api/seguimientos', { method: 'POST', body: { lead_id: currentLeadId, fecha, nota } });
    bootstrap.Modal.getInstance(document.getElementById('seguimientoModal')).hide();
    openLeadDetail(currentLeadId);
}

async function completeSeguimiento(id) {
    await api(`/api/seguimientos/${id}`, { method: 'PUT', body: { completado: true } });
    refreshCurrentView();
    if (currentLeadId) openLeadDetail(currentLeadId);
}

async function deleteSeguimiento(id) {
    if (!confirm('Eliminar este seguimiento?')) return;
    await api(`/api/seguimientos/${id}`, { method: 'DELETE' });
    loadSeguimientos();
}

// ── Pipeline ──────────────────────────────────────────────────────────────
async function loadPipeline() {
    const params = currentAcademia ? `?academia=${currentAcademia}` : '';
    document.getElementById('pipeline-title').innerHTML = currentAcademia
        ? `<i class="bi bi-kanban"></i> Pipeline - ${currentAcademia}`
        : `<i class="bi bi-kanban"></i> Pipeline de Ventas`;

    const leads = await api(`/api/leads${params}`);
    const estados = ['nuevo', 'contactado', 'no_coge', 'interesado', 'a_espera_de_pago', 'matriculado', 'perdido'];

    for (const estado of estados) {
        const container = document.getElementById(`pipeline-${estado}`);
        const estadoLeads = leads.filter(l => l.estado === estado);
        container.innerHTML = estadoLeads.map(l => `
            <div class="pipeline-card" draggable="true" data-id="${l.id}"
                 ondragstart="dragStart(event, ${l.id})" ondragend="dragEnd(event)"
                 onclick="openLeadDetail(${l.id})">
                <div class="lead-name">${l.nombre}</div>
                <div class="lead-meta">
                    <span class="badge badge-${l.academia.toLowerCase()}" style="font-size:0.65rem">${l.academia}</span>
                </div>
                ${l.telefono ? `<div class="lead-meta mt-1"><i class="bi bi-telephone"></i> ${l.telefono}</div>` : ''}
            </div>
        `).join('');

        const header = container.previousElementSibling;
        const originalText = header.textContent.replace(/\s*\(\d+\)/, '');
        header.textContent = `${originalText} (${estadoLeads.length})`;
    }

    document.querySelectorAll('.pipeline-body').forEach(body => {
        body.addEventListener('dragover', (e) => { e.preventDefault(); body.classList.add('drag-over'); });
        body.addEventListener('dragleave', () => { body.classList.remove('drag-over'); });
        body.addEventListener('drop', () => { body.classList.remove('drag-over'); });
    });
}

let draggedLeadId = null;

function dragStart(event, id) {
    draggedLeadId = id;
    event.target.classList.add('dragging');
    event.dataTransfer.effectAllowed = 'move';
}

function dragEnd(event) { event.target.classList.remove('dragging'); }

async function dropLead(event, estado) {
    event.preventDefault();
    if (draggedLeadId) {
        await api(`/api/leads/${draggedLeadId}`, { method: 'PUT', body: { estado } });
        draggedLeadId = null;
        loadPipeline();
    }
}

// ── Utilities ─────────────────────────────────────────────────────────────
function formatDate(isoStr) {
    if (!isoStr) return '-';
    const d = new Date(isoStr);
    return d.toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function refreshCurrentView() {
    if (currentView === 'leads') loadLeads();
    else if (currentView === 'pipeline') loadPipeline();
    else if (currentView === 'dashboard') loadDashboard();
    else if (currentView === 'alumnos') loadAlumnos();
    else if (currentView === 'seguimientos') loadSeguimientos();
}
