/**
 * HackCure — Dashboard UI
 * ========================
 * Renders patient cards, alerts, and event history.
 * Syncs with PatientStateManager.
 */

const DashboardUI = (() => {
    let selectedPatientId = null;

    function init() {
        renderPatientCards();
        setupEventHandlers();

        // Subscribe to state changes
        PatientStateManager.subscribe((type, data) => {
            if (type === 'update') {
                updatePatientCard(data.patient);
                addEventToLog(data.event);
                checkAlerts();
            } else if (type === 'reset' || type === 'init') {
                renderPatientCards();
                if (type === 'reset') clearEventLog();
                checkAlerts();
            }
        });

        // Clock
        updateClock();
        setInterval(updateClock, 1000);
    }

    function renderPatientCards() {
        const container = document.getElementById('patient-cards-container');
        if (!container) return;

        const patients = PatientStateManager.getPatientList();
        container.innerHTML = '';

        patients.forEach(p => {
            const card = createPatientCard(p);
            container.appendChild(card);
        });

        document.getElementById('patient-count').textContent = patients.length;
    }

    function createPatientCard(patient) {
        const card = document.createElement('div');
        card.className = 'patient-card';
        card.id = `card-${patient.patient_id}`;
        card.dataset.patientId = patient.patient_id;

        applyCardStatus(card, patient);

        const statusText = getStatusText(patient);
        const statusClass = getStatusClass(patient);
        const timeStr = patient.last_event_time
            ? new Date(patient.last_event_time).toLocaleTimeString()
            : '--:--:--';

        card.innerHTML = `
            <div class="card-header">
                <div>
                    <div class="card-name">${patient.name || patient.patient_id}</div>
                    <div class="card-id">Room ${patient.room || '?'} · Age ${patient.age || '?'}</div>
                </div>
                <div class="card-status">
                    <span class="status-badge ${statusClass}">${statusText}</span>
                </div>
            </div>
            <div class="card-meta">
                <span>Last: ${timeStr}</span>
                <span class="card-confidence">${patient.confidence ? (patient.confidence * 100).toFixed(0) + '%' : '—'}</span>
            </div>
        `;

        card.addEventListener('click', () => selectPatient(patient.patient_id));
        return card;
    }

    function updatePatientCard(patient) {
        const card = document.getElementById(`card-${patient.patient_id}`);
        if (!card) return;

        applyCardStatus(card, patient);

        const statusText = getStatusText(patient);
        const statusClass = getStatusClass(patient);
        const timeStr = patient.last_event_time
            ? new Date(patient.last_event_time).toLocaleTimeString()
            : '--:--:--';

        const statusBadge = card.querySelector('.status-badge');
        if (statusBadge) {
            statusBadge.className = `status-badge ${statusClass}`;
            statusBadge.textContent = statusText;
        }

        const meta = card.querySelector('.card-meta');
        if (meta) {
            meta.innerHTML = `
                <span>Last: ${timeStr}</span>
                <span class="card-confidence">${patient.confidence ? (patient.confidence * 100).toFixed(0) + '%' : '—'}</span>
            `;
        }
    }

    function applyCardStatus(card, patient) {
        card.classList.remove('status-fall', 'status-pain', 'status-fall-pain', 'status-machine-error');
        if (patient.fall_detected && patient.pain_detected) {
            card.classList.add('status-fall-pain');
        } else if (patient.fall_detected) {
            card.classList.add('status-fall');
        } else if (patient.pain_detected) {
            card.classList.add('status-pain');
        } else if (patient.machine_error) {
            card.classList.add('status-machine-error');
        }
    }

    function getStatusText(patient) {
        if (patient.fall_detected && patient.pain_detected) return '⚠ FALL + PAIN';
        if (patient.fall_detected) return '⚠ FALL';
        if (patient.pain_detected) return '😣 PAIN';
        if (patient.machine_error) return '⚙️ ' + (patient.machine_type || 'MACHINE ERR');
        return '✓ Normal';
    }

    function getStatusClass(patient) {
        if (patient.fall_detected && patient.pain_detected) return 'fall-pain';
        if (patient.fall_detected) return 'fall';
        if (patient.pain_detected) return 'pain';
        if (patient.machine_error) return 'machine-error';
        return 'normal';
    }

    function selectPatient(patientId) {
        // Deselect previous
        document.querySelectorAll('.patient-card').forEach(c => c.classList.remove('selected'));

        selectedPatientId = patientId;

        // Highlight card
        const card = document.getElementById(`card-${patientId}`);
        if (card) card.classList.add('selected');

        // Focus camera (CCTV view)
        HospitalScene.focusOnPatient(patientId);
        
        // Show CCTV Overlay
        const overlay = document.getElementById('cctv-overlay');
        const camId = document.getElementById('cctv-cam-id');
        if (overlay && camId) {
            overlay.classList.remove('cctv-hidden');
            const patient = PatientStateManager.getPatient(patientId);
            camId.textContent = patient?.room || '01';
        }

        // Show detail
        showPatientDetail(patientId);
    }

    function showPatientDetail(patientId) {
        const detail = document.getElementById('patient-detail');
        const content = document.getElementById('detail-content');
        const patient = PatientStateManager.getPatient(patientId);
        if (!detail || !content || !patient) return;

        detail.classList.remove('detail-hidden');

        const machineRow = patient.machine_error ? `
            <div class="detail-row detail-row-alert">
                <span class="detail-label">⚙️ Machine</span>
                <span class="detail-value detail-value-alert">${patient.machine_type || 'Unknown'} — ERROR</span>
            </div>
        ` : '';

        const recsHtml = (patient.recommendations && patient.recommendations.length > 0) ? `
            <div class="detail-row detail-row-recs">
                <span class="detail-label">🤖 AI Agent</span>
                <span class="detail-value">${patient.recommendations[0]}</span>
            </div>
        ` : '';

        content.innerHTML = `
            <div class="detail-row">
                <span class="detail-label">ID</span>
                <span class="detail-value">${patient.patient_id}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Name</span>
                <span class="detail-value">${patient.name}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Room</span>
                <span class="detail-value">${patient.room || '?'}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">State</span>
                <span class="detail-value">${getStatusText(patient)}</span>
            </div>
            ${machineRow}
            <div class="detail-row">
                <span class="detail-label">Confidence</span>
                <span class="detail-value">${patient.confidence ? (patient.confidence * 100).toFixed(1) + '%' : '—'}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Priority</span>
                <span class="detail-value">${patient.alert_priority?.toUpperCase() || 'NONE'}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Source</span>
                <span class="detail-value">${patient.source?.toUpperCase() || '—'}</span>
            </div>
            ${recsHtml}
        `;
    }

    // ── Event Log ──────────────────────────────────────────
    function addEventToLog(event) {
        if (!event) return;

        const list = document.getElementById('event-list');
        if (!list) return;

        // Remove empty placeholder
        const empty = list.querySelector('.event-empty');
        if (empty) empty.remove();

        const item = document.createElement('div');
        const eventClass = getEventClass(event.event_type);
        item.className = `event-item ${eventClass}`;

        const time = event.timestamp
            ? new Date(event.timestamp).toLocaleTimeString()
            : new Date().toLocaleTimeString();

        const patient = PatientStateManager.getPatient(event.patient_id);
        const name = patient?.name || event.patient_id;

        const machineLabel = event.machine_type ? ` — ${event.machine_type}` : '';
        const typeLabels = {
            fall: '⚠️ Fall Detected',
            pain: '😣 Pain Detected',
            fall_and_pain: '🚨 Fall + Pain',
            recover: '✅ Recovery',
            machine_error: `⚙️ Machine Failure${machineLabel}`,
            behavioral_risk: '🧠 Behavioral Risk',
        };

        item.innerHTML = `
            <div class="event-header">
                <span class="event-type">${typeLabels[event.event_type] || event.event_type}</span>
                <span class="event-time">${time}</span>
            </div>
            <div class="event-patient">${name} · Room ${patient?.room || '?'}</div>
            <span class="event-source source-${event.source}">${event.source}</span>
        `;

        list.insertBefore(item, list.firstChild);

        // Cap at 50 events
        while (list.children.length > 50) {
            list.removeChild(list.lastChild);
        }

        // Update count
        const count = document.getElementById('event-count');
        if (count) count.textContent = list.children.length;
    }

    function clearEventLog() {
        const list = document.getElementById('event-list');
        if (list) {
            list.innerHTML = '<div class="event-empty">No events yet</div>';
        }
        const count = document.getElementById('event-count');
        if (count) count.textContent = '0';
    }

    function getEventClass(eventType) {
        const map = {
            fall: 'event-fall',
            pain: 'event-pain',
            fall_and_pain: 'event-fall-pain',
            recover: 'event-recover',
            machine_error: 'event-machine-error',
            behavioral_risk: 'event-behavioral-risk',
        };
        return map[eventType] || '';
    }

    // ── Alerts ─────────────────────────────────────────────
    function checkAlerts() {
        const critical = PatientStateManager.getCriticalPatients();
        const machineErrors = PatientStateManager.getMachineErrorPatients();
        const banner = document.getElementById('alert-banner');
        const text = document.getElementById('alert-text');

        if (critical.length > 0) {
            const names = critical.map(p => p.name || p.patient_id).join(', ');
            text.textContent = `CRITICAL ALERT — ${names}`;
            banner.className = 'alert-visible alert-critical';
        } else if (machineErrors.length > 0) {
            const msgs = machineErrors.map(p => `${p.machine_type || 'Machine'} (Room ${p.room})`).join(', ');
            text.textContent = `⚙️ MACHINE FAILURE — ${msgs}`;
            banner.className = 'alert-visible alert-machine-error';
        } else if (!PatientStateManager.hasActiveAlerts()) {
            banner.className = 'alert-hidden';
        }
    }

    // ── Event Handlers ─────────────────────────────────────
    function setupEventHandlers() {
        // Camera controls
        document.getElementById('btn-overview')?.addEventListener('click', () => {
            HospitalScene.resetCamera();
            document.getElementById('cctv-overlay')?.classList.add('cctv-hidden');
        });
        document.getElementById('btn-topdown')?.addEventListener('click', () => {
            HospitalScene.topDownView();
            document.getElementById('cctv-overlay')?.classList.add('cctv-hidden');
        });

        // Alert dismiss
        document.getElementById('alert-dismiss')?.addEventListener('click', () => {
            document.getElementById('alert-banner').className = 'alert-hidden';
        });
    }

    function updateClock() {
        const now = new Date();
        const timeStr = now.toLocaleTimeString();
        const dateStr = now.toISOString().split('T')[0].replace(/-/g, '/');
        
        const el = document.getElementById('clock');
        if (el) el.textContent = timeStr;
        
        const cctvTime = document.getElementById('cctv-time');
        if (cctvTime) cctvTime.textContent = timeStr;
        
        const cctvDate = document.getElementById('cctv-date');
        if (cctvDate) cctvDate.textContent = dateStr;
    }

    function getSelectedPatientId() {
        return selectedPatientId;
    }

    return {
        init,
        selectPatient,
        addEventToLog,
        getSelectedPatientId,
    };
})();
