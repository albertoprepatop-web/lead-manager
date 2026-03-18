// ── State ──────────────────────────────────────────────────────────────────
let currentView = 'dashboard';
let currentAcademia = ''; // '' = General
let currentLeadId = null;
let chartEstados = null;
let chartMeses = null;
let chartAlumnosMes = null;
let pendingContactoLeadId = null;
let pendingContactoSource = null; // 'detail' or 'quick'

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

const ESPECIALIDADES = {
    PREPATOP: ['Infantil', 'Primaria', 'Ingles', 'PT', 'PT Online', 'EF', 'AL'],
    PREPARAANDALUCIA: ['EF', 'AL', 'PT', 'Primaria'],
    PREPARASECUNDARIA: ['Tecnologia', 'Historia', 'Lengua', 'Economia', 'Latin', 'FyQ', 'Filosofia', 'Ingles', 'Musica', 'EF'],
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
    if (academia === 'GESTION_PREPATOP') {
        document.getElementById('subtabs-general').style.display = 'none';
        document.getElementById('subtabs-academia').style.display = 'none';
        showView('economica');
    } else if (academia === '') {
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
    else if (view === 'economica') loadEconomica();
    else if (view === 'socios') loadSocios();
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
    if (data.alumnos_por_mes) renderChartAlumnosMes(data.alumnos_por_mes);
    if (data.por_especialidad) renderChartsEspecialidad(data.por_especialidad);

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

function renderChartAlumnosMes(alumnosPorMes) {
    const ctx = document.getElementById('chart-alumnos-mes').getContext('2d');
    if (chartAlumnosMes) chartAlumnosMes.destroy();
    chartAlumnosMes = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: alumnosPorMes.map(m => m.mes),
            datasets: [{
                label: 'Nuevos Alumnos',
                data: alumnosPorMes.map(m => m.count),
                backgroundColor: '#16A34A',
                borderColor: '#15803D',
                borderWidth: 1,
                borderRadius: 4,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
        },
    });
}

const MAX_ALUMNOS_GRUPO = 14;

const ESP_BAR_COLORS = {
    PREPATOP: '#2563EB',
    PREPARASECUNDARIA: '#16A34A',
    PREPARAANDALUCIA: '#EA580C',
};

function renderChartsEspecialidad(porEspecialidad) {
    const configs = [
        { key: 'PREPATOP', containerId: 'esp-bars-prepatop' },
        { key: 'PREPARASECUNDARIA', containerId: 'esp-bars-preparasecundaria' },
        { key: 'PREPARAANDALUCIA', containerId: 'esp-bars-preparaandalucia' },
    ];

    for (const cfg of configs) {
        const data = porEspecialidad[cfg.key];
        const container = document.getElementById(cfg.containerId);
        if (!data || !container) continue;

        const color = ESP_BAR_COLORS[cfg.key];
        const total = Object.values(data).reduce((a, b) => a + b, 0);

        let html = '';
        for (const [esp, count] of Object.entries(data)) {
            const pct = Math.min((count / MAX_ALUMNOS_GRUPO) * 100, 100);
            const isFull = count >= MAX_ALUMNOS_GRUPO;
            const barColor = isFull ? '#EF4444' : color;
            html += `
                <div class="mb-2">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <span class="fw-bold" style="font-size:0.85rem">${esp}</span>
                        <span class="badge ${isFull ? 'bg-danger' : 'bg-secondary'}">${count}/${MAX_ALUMNOS_GRUPO}</span>
                    </div>
                    <div class="progress" style="height: 20px;">
                        <div class="progress-bar ${isFull ? 'bg-danger' : ''}" role="progressbar"
                             style="width: ${pct}%; background-color: ${isFull ? '' : barColor}"
                             aria-valuenow="${count}" aria-valuemin="0" aria-valuemax="${MAX_ALUMNOS_GRUPO}">
                        </div>
                    </div>
                </div>`;
        }
        html += `<div class="text-center text-muted mt-2" style="font-size:0.8rem">Total: ${total} alumnos</div>`;
        container.innerHTML = html;
    }
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
    if (estado === 'contactado') {
        pendingContactoLeadId = id;
        pendingContactoSource = 'quick';
        const now = new Date();
        document.getElementById('fecha-contacto-input').value = now.toISOString().slice(0, 16);
        new bootstrap.Modal(document.getElementById('fechaContactoModal')).show();
        return;
    }
    await api(`/api/leads/${id}`, { method: 'PUT', body: { estado } });
}

function exportCSV() {
    const params = new URLSearchParams();
    if (currentAcademia) params.set('academia', currentAcademia);
    const estado = document.getElementById('filter-estado').value;
    if (estado) params.set('estado', estado);
    window.open(`/api/export/csv?${params}`, '_blank');
}

// ── Especialidad Helper ───────────────────────────────────────────────────
function updateEspecialidadOptions(prefix) {
    const academiaEl = document.getElementById(`${prefix}-academia`);
    const espSelect = document.getElementById(`${prefix}-especialidad`);
    const espGroup = document.getElementById(`${prefix}-especialidad-group`);
    if (!academiaEl || !espSelect) return;

    const academia = academiaEl.value;
    const opciones = ESPECIALIDADES[academia] || [];

    if (opciones.length === 0) {
        espGroup.style.display = 'none';
        espSelect.innerHTML = '<option value="">Sin especialidad</option>';
    } else {
        espGroup.style.display = 'block';
        espSelect.innerHTML = '<option value="">Sin especialidad</option>' +
            opciones.map(e => `<option value="${e}">${e}</option>`).join('');
    }
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
        updateEspecialidadOptions('lead');
        document.getElementById('lead-especialidad').value = lead.especialidad || '';
    } else {
        document.getElementById('lead-nombre').value = '';
        document.getElementById('lead-telefono').value = '';
        document.getElementById('lead-email').value = '';
        document.getElementById('lead-estado').value = 'nuevo';
        document.getElementById('lead-notas').value = '';
        updateEspecialidadOptions('lead');
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
        especialidad: document.getElementById('lead-especialidad').value,
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
        ${lead.especialidad ? `<div class="mb-1"><i class="bi bi-mortarboard me-2"></i>Especialidad: ${lead.especialidad}</div>` : ''}
        ${lead.fecha_contacto ? `<div class="mb-1"><i class="bi bi-telephone-forward me-2"></i>Contactado: ${formatDate(lead.fecha_contacto)}</div>` : ''}
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
    if (estado === 'contactado') {
        pendingContactoLeadId = currentLeadId;
        pendingContactoSource = 'detail';
        const now = new Date();
        document.getElementById('fecha-contacto-input').value = now.toISOString().slice(0, 16);
        new bootstrap.Modal(document.getElementById('fechaContactoModal')).show();
        return;
    }
    await api(`/api/leads/${currentLeadId}`, { method: 'PUT', body: { estado } });
    openLeadDetail(currentLeadId);
}

async function confirmContacto() {
    const fechaContacto = document.getElementById('fecha-contacto-input').value;
    const body = { estado: 'contactado' };
    if (fechaContacto) body.fecha_contacto = fechaContacto;

    await api(`/api/leads/${pendingContactoLeadId}`, { method: 'PUT', body });
    bootstrap.Modal.getInstance(document.getElementById('fechaContactoModal')).hide();

    if (pendingContactoSource === 'detail') {
        openLeadDetail(pendingContactoLeadId);
    }
    refreshCurrentView();
    pendingContactoLeadId = null;
    pendingContactoSource = null;
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
        tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted py-4">No se encontraron alumnos</td></tr>';
        return;
    }

    const showAcademia = !currentAcademia;
    tbody.innerHTML = alumnos.map(a => `
        <tr>
            <td class="fw-bold">${a.nombre}</td>
            <td>${a.telefono || '-'}</td>
            <td>${a.email || '-'}</td>
            <td>${showAcademia ? `<span class="badge badge-${a.academia.toLowerCase()}">${a.academia}</span>` : ''}</td>
            <td>${a.especialidad || '-'}</td>
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
    document.getElementById('alumno-cuota').value = alumno.cuota || '';
    document.getElementById('alumno-notas').value = alumno.notas;

    // Especialidad
    const espSelect = document.getElementById('alumno-especialidad');
    const espGroup = document.getElementById('alumno-especialidad-group');
    const opciones = ESPECIALIDADES[alumno.academia] || [];
    if (opciones.length === 0) {
        espGroup.style.display = 'none';
        espSelect.innerHTML = '<option value="">Sin especialidad</option>';
    } else {
        espGroup.style.display = 'block';
        espSelect.innerHTML = '<option value="">Sin especialidad</option>' +
            opciones.map(e => `<option value="${e}">${e}</option>`).join('');
        espSelect.value = alumno.especialidad || '';
    }

    new bootstrap.Modal(document.getElementById('alumnoModal')).show();
}

async function saveAlumno() {
    const id = document.getElementById('alumno-id').value;
    const data = {
        nombre: document.getElementById('alumno-nombre').value.trim(),
        telefono: document.getElementById('alumno-telefono').value.trim(),
        email: document.getElementById('alumno-email').value.trim(),
        especialidad: document.getElementById('alumno-especialidad').value,
        curso: document.getElementById('alumno-curso').value.trim(),
        modalidad: document.getElementById('alumno-modalidad').value,
        estado_pago: document.getElementById('alumno-pago').value,
        cuota: document.getElementById('alumno-cuota').value || 0,
        notas: document.getElementById('alumno-notas').value.trim(),
    };

    await api(`/api/alumnos/${id}`, { method: 'PUT', body: data });
    bootstrap.Modal.getInstance(document.getElementById('alumnoModal')).hide();
    loadAlumnos();
}

// ── Nuevo Alumno (manual, sin pasar por Lead) ────────────────────────────
function openNuevoAlumnoModal() {
    document.getElementById('nuevo-alumno-nombre').value = '';
    document.getElementById('nuevo-alumno-telefono').value = '';
    document.getElementById('nuevo-alumno-email').value = '';
    document.getElementById('nuevo-alumno-curso').value = '';
    document.getElementById('nuevo-alumno-modalidad').value = 'presencial';
    document.getElementById('nuevo-alumno-pago').value = 'pendiente';
    document.getElementById('nuevo-alumno-notas').value = '';

    if (currentAcademia) {
        document.getElementById('nuevo-alumno-academia').value = currentAcademia;
        document.getElementById('nuevo-alumno-academia-group').style.display = 'none';
    } else {
        document.getElementById('nuevo-alumno-academia-group').style.display = 'block';
    }
    updateEspecialidadOptions('nuevo-alumno');

    new bootstrap.Modal(document.getElementById('nuevoAlumnoModal')).show();
}

async function saveNuevoAlumno() {
    const data = {
        nombre: document.getElementById('nuevo-alumno-nombre').value.trim(),
        telefono: document.getElementById('nuevo-alumno-telefono').value.trim(),
        email: document.getElementById('nuevo-alumno-email').value.trim(),
        academia: currentAcademia || document.getElementById('nuevo-alumno-academia').value,
        especialidad: document.getElementById('nuevo-alumno-especialidad').value,
        curso: document.getElementById('nuevo-alumno-curso').value.trim(),
        modalidad: document.getElementById('nuevo-alumno-modalidad').value,
        estado_pago: document.getElementById('nuevo-alumno-pago').value,
        cuota: document.getElementById('nuevo-alumno-cuota').value || 0,
        notas: document.getElementById('nuevo-alumno-notas').value.trim(),
    };

    if (!data.nombre) { alert('El nombre es obligatorio'); return; }
    if (!data.curso) { alert('El curso es obligatorio'); return; }

    await api('/api/alumnos', { method: 'POST', body: data });
    bootstrap.Modal.getInstance(document.getElementById('nuevoAlumnoModal')).hide();
    alert('Alumno creado correctamente!');
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
    else if (currentView === 'economica') loadEconomica();
    else if (currentView === 'socios') loadSocios();
}

// ── Gestion Economica ────────────────────────────────────────────────────
const MES_LABELS = {
    '01': 'Enero', '02': 'Febrero', '03': 'Marzo', '04': 'Abril',
    '05': 'Mayo', '06': 'Junio', '07': 'Julio', '08': 'Agosto',
    '09': 'Septiembre', '10': 'Octubre', '11': 'Noviembre', '12': 'Diciembre',
};

function formatMes(mesStr) {
    // "2026-04" -> "Abril 2026"
    const [year, month] = mesStr.split('-');
    return `${MES_LABELS[month] || month} ${year}`;
}

async function loadEconomica() {
    const apiAcademia = currentAcademia === 'GESTION_PREPATOP' ? 'PREPATOP' : currentAcademia;
    if (!apiAcademia) return;

    const titleLabel = currentAcademia === 'GESTION_PREPATOP' ? 'PREPATOP 2025-2026' : apiAcademia;
    document.getElementById('economica-title').innerHTML = `<i class="bi bi-cash-stack"></i> Gestion Economica - ${titleLabel}`;

    const data = await api(`/api/gestion-economica?academia=${apiAcademia}`);
    const meses = data.meses;
    const allAlumnos = data.alumnos;
    const totales = data.totales;

    // Group students: regular vs Jessica 2 years
    const regularAlumnos = allAlumnos.filter(a => a.curso !== 'PT Jessica 2 Años');
    const jessicaAlumnos = allAlumnos.filter(a => a.curso === 'PT Jessica 2 Años');

    // Group regular students by especialidad
    const groups = {};
    for (const a of regularAlumnos) {
        const esp = a.especialidad || 'Sin especialidad';
        if (!groups[esp]) groups[esp] = [];
        groups[esp].push(a);
    }

    function buildAlumnoRows(alumnos) {
        return alumnos.map(a => `<tr>
            <td class="fw-bold">${a.nombre}</td>
            <td>${a.cuota ? a.cuota.toFixed(2) + ' EUR' : '-'}</td>
            ${meses.map(m => {
                const pago = a.pagos[m];
                if (pago) {
                    const metodoIcon = pago.metodo === 'efectivo' ? 'bi-cash' : 'bi-receipt';
                    const metodoLabel = pago.metodo === 'efectivo' ? 'Efect.' : 'Recibo';
                    const socioLabel = pago.recogido_por ? ` (${pago.recogido_por.charAt(0)})` : '';
                    return `<td class="text-center">
                        <button class="btn btn-sm btn-success w-100" onclick="openPagoModal(${a.id}, '${m}', ${a.cuota || 0}, ${pago.id})" title="Click para editar">
                            <i class="bi ${metodoIcon}"></i> ${metodoLabel}${socioLabel}
                        </button>
                    </td>`;
                } else {
                    return `<td class="text-center">
                        <button class="btn btn-sm btn-outline-danger w-100" onclick="openPagoModal(${a.id}, '${m}', ${a.cuota || 0})">
                            <i class="bi bi-x-circle"></i> Pendiente
                        </button>
                    </td>`;
                }
            }).join('')}
        </tr>`).join('');
    }

    // Build header
    const thead = document.getElementById('economica-thead');
    thead.innerHTML = `<tr>
        <th style="min-width:200px">Alumno</th>
        <th style="min-width:80px">Cuota</th>
        ${meses.map(m => `<th class="text-center" style="min-width:120px">${formatMes(m)}</th>`).join('')}
    </tr>`;

    // Build body with groups
    const tbody = document.getElementById('economica-tbody');
    const colSpan = 2 + meses.length;

    if (allAlumnos.length === 0) {
        tbody.innerHTML = `<tr><td colspan="${colSpan}" class="text-center text-muted py-4">No hay alumnos en esta academia</td></tr>`;
    } else {
        let html = '';
        // Specialty order
        const espOrder = ['EF', 'AL', 'Ingles', 'Infantil', 'PT', 'Primaria', 'PT Online'];
        const sortedKeys = espOrder.filter(k => groups[k]);
        // Add any remaining keys
        for (const k of Object.keys(groups)) {
            if (!sortedKeys.includes(k)) sortedKeys.push(k);
        }

        for (const esp of sortedKeys) {
            html += `<tr class="table-secondary"><td colspan="${colSpan}" class="fw-bold"><i class="bi bi-mortarboard"></i> ${esp} (${groups[esp].length})</td></tr>`;
            html += buildAlumnoRows(groups[esp]);
        }

        // Jessica section
        if (jessicaAlumnos.length > 0) {
            html += `<tr class="table-warning"><td colspan="${colSpan}" class="fw-bold"><i class="bi bi-star"></i> PT Jessica - 2 Años (${jessicaAlumnos.length})</td></tr>`;
            html += buildAlumnoRows(jessicaAlumnos);
        }

        tbody.innerHTML = html;
    }

    // Build footer with totals
    const tfoot = document.getElementById('economica-tfoot');
    if (meses.length > 0) {
        tfoot.innerHTML = `
            <tr class="table-warning fw-bold">
                <td>Total Efectivo</td>
                <td></td>
                ${meses.map(m => `<td class="text-center">${(totales[m]?.efectivo || 0).toFixed(2)} EUR</td>`).join('')}
            </tr>
            <tr class="table-info fw-bold">
                <td>Total Recibo</td>
                <td></td>
                ${meses.map(m => `<td class="text-center">${(totales[m]?.recibo || 0).toFixed(2)} EUR</td>`).join('')}
            </tr>
            <tr class="table-dark fw-bold">
                <td>TOTAL</td>
                <td></td>
                ${meses.map(m => `<td class="text-center">${(totales[m]?.total || 0).toFixed(2)} EUR</td>`).join('')}
            </tr>`;
    } else {
        tfoot.innerHTML = '';
    }

    // Summary cards
    const totalEfectivo = Object.values(totales).reduce((sum, t) => sum + (t.efectivo || 0), 0);
    const totalRecibo = Object.values(totales).reduce((sum, t) => sum + (t.recibo || 0), 0);
    document.getElementById('economica-totales').innerHTML = `
        <div class="col-md-4">
            <div class="card border-success">
                <div class="card-body text-center">
                    <h6 class="text-success"><i class="bi bi-cash"></i> Total Efectivo</h6>
                    <h3 class="fw-bold">${totalEfectivo.toFixed(2)} EUR</h3>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card border-primary">
                <div class="card-body text-center">
                    <h6 class="text-primary"><i class="bi bi-receipt"></i> Total Recibo</h6>
                    <h3 class="fw-bold">${totalRecibo.toFixed(2)} EUR</h3>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card border-dark">
                <div class="card-body text-center">
                    <h6><i class="bi bi-wallet2"></i> Total General</h6>
                    <h3 class="fw-bold">${(totalEfectivo + totalRecibo).toFixed(2)} EUR</h3>
                </div>
            </div>
        </div>`;
}

function openPagoModal(alumnoId, mes, cuota, pagoId = null) {
    document.getElementById('pago-alumno-id').value = alumnoId;
    document.getElementById('pago-mes').value = mes;
    document.getElementById('pago-id').value = pagoId || '';
    document.getElementById('pago-mes-label').textContent = formatMes(mes);
    document.getElementById('pago-metodo').value = 'efectivo';
    document.getElementById('pago-cantidad').value = cuota || '';
    document.getElementById('pago-recogido').value = 'Alberto';
    document.getElementById('btn-delete-pago').style.display = pagoId ? 'inline-block' : 'none';

    // Find alumno name from the table
    const rows = document.querySelectorAll('#economica-tbody tr');
    let nombre = '';
    rows.forEach(r => {
        const btn = r.querySelector(`button[onclick*="openPagoModal(${alumnoId},"]`) || r.querySelector(`button[onclick*="openPagoModal(${alumnoId}, "]`);
        if (btn) nombre = r.cells[0].textContent;
    });
    document.getElementById('pago-alumno-nombre').textContent = nombre;

    toggleRecogidoPor();

    // If editing existing pago, load its data
    if (pagoId) {
        // We need to find the pago data - it's embedded in the button title
        const btn = document.querySelector(`button[onclick*="openPagoModal(${alumnoId}, '${mes}', ${cuota}, ${pagoId})"]`);
        if (btn) {
            const title = btn.getAttribute('title');
            if (title) {
                const isEfectivo = title.startsWith('efectivo');
                document.getElementById('pago-metodo').value = isEfectivo ? 'efectivo' : 'recibo';
                toggleRecogidoPor();
                // Extract recogido_por from "(Alberto)" or "(Esteban)"
                const socioMatch = title.match(/\((\w+)\)/);
                if (socioMatch) document.getElementById('pago-recogido').value = socioMatch[1];
                // Extract cantidad
                const cantMatch = title.match(/([\d.]+) EUR/);
                if (cantMatch) document.getElementById('pago-cantidad').value = cantMatch[1];
            }
        }
    }

    new bootstrap.Modal(document.getElementById('pagoModal')).show();
}

function toggleRecogidoPor() {
    const metodo = document.getElementById('pago-metodo').value;
    document.getElementById('pago-recogido-group').style.display = metodo === 'efectivo' ? 'block' : 'none';
}

async function savePago() {
    const alumnoId = document.getElementById('pago-alumno-id').value;
    const mes = document.getElementById('pago-mes').value;
    const pagoId = document.getElementById('pago-id').value;
    const metodo = document.getElementById('pago-metodo').value;
    const cantidad = document.getElementById('pago-cantidad').value;
    const recogidoPor = document.getElementById('pago-recogido').value;

    if (!cantidad || parseFloat(cantidad) <= 0) { alert('La cantidad es obligatoria'); return; }

    const body = {
        alumno_id: parseInt(alumnoId),
        mes,
        metodo,
        cantidad: parseFloat(cantidad),
        recogido_por: metodo === 'efectivo' ? recogidoPor : null,
    };

    if (pagoId) {
        await api(`/api/pagos/${pagoId}`, { method: 'PUT', body });
    } else {
        await api('/api/pagos', { method: 'POST', body });
    }

    bootstrap.Modal.getInstance(document.getElementById('pagoModal')).hide();
    loadEconomica();
}

async function deletePago() {
    const pagoId = document.getElementById('pago-id').value;
    if (!pagoId) return;
    if (!confirm('Eliminar este pago?')) return;

    await api(`/api/pagos/${pagoId}`, { method: 'DELETE' });
    bootstrap.Modal.getInstance(document.getElementById('pagoModal')).hide();
    loadEconomica();
}

function openAddMesModal() {
    // Default to next month
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 2).padStart(2, '0'); // next month (0-indexed + 1 + 1)
    document.getElementById('add-mes-input').value = `${year}-${month}`;
    new bootstrap.Modal(document.getElementById('addMesModal')).show();
}

async function saveNewMes() {
    const mes = document.getElementById('add-mes-input').value;
    if (!mes) { alert('Selecciona un mes'); return; }

    const apiAcademia = currentAcademia === 'GESTION_PREPATOP' ? 'PREPATOP' : currentAcademia;
    await api('/api/meses', { method: 'POST', body: { mes, academia: apiAcademia } });
    bootstrap.Modal.getInstance(document.getElementById('addMesModal')).hide();
    loadEconomica();
}

// ── Socios ───────────────────────────────────────────────────────────────
async function loadSocios() {
    const data = await api('/api/socios');
    const { socios, meses } = data;

    const container = document.getElementById('socios-cards');
    const totalGeneral = Object.values(socios).reduce((sum, s) => sum + s.total, 0);

    container.innerHTML = Object.entries(socios).map(([nombre, info]) => {
        const pct = totalGeneral > 0 ? ((info.total / totalGeneral) * 100).toFixed(1) : 0;
        return `
        <div class="col-md-6">
            <div class="card">
                <div class="card-header fw-bold bg-dark text-white">
                    <i class="bi bi-person-circle"></i> ${nombre}
                </div>
                <div class="card-body">
                    <div class="text-center mb-3">
                        <h2 class="fw-bold text-success">${info.total.toFixed(2)} EUR</h2>
                        <span class="text-muted">Total efectivo recogido (${pct}%)</span>
                    </div>
                    ${meses.length > 0 ? `
                    <table class="table table-sm">
                        <thead><tr><th>Mes</th><th class="text-end">Efectivo</th></tr></thead>
                        <tbody>
                            ${meses.map(m => `<tr>
                                <td>${formatMes(m)}</td>
                                <td class="text-end fw-bold">${(info.por_mes[m] || 0).toFixed(2)} EUR</td>
                            </tr>`).join('')}
                        </tbody>
                        <tfoot>
                            <tr class="table-dark"><td class="fw-bold">Total</td><td class="text-end fw-bold">${info.total.toFixed(2)} EUR</td></tr>
                        </tfoot>
                    </table>` : '<p class="text-muted text-center">No hay pagos registrados</p>'}
                </div>
            </div>
        </div>`;
    }).join('');
}
