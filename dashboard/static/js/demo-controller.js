/**
 * HackCure — Demo Controller (Scenario B)
 * =========================================
 * Controls for triggering simulated events
 * during hackathon jury presentation.
 */

const DemoController = (() => {
    let autoSequenceRunning = false;
    let autoSequenceTimer = null;

    function init(mode) {
        setupDemoButtons();
        populatePatientSelect();
        updateVisibility(mode);
    }

    function populatePatientSelect() {
        const select = document.getElementById('demo-target-patient');
        if (!select) return;

        const patients = PatientStateManager.getPatientList();
        select.innerHTML = '';
        patients.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.patient_id;
            opt.textContent = `${p.name} (Room ${p.room || '?'})`;
            select.appendChild(opt);
        });
    }

    function setupDemoButtons() {
        // Event trigger buttons
        document.querySelectorAll('.demo-btn[data-event]').forEach(btn => {
            btn.addEventListener('click', () => {
                const eventType = btn.dataset.event;
                const patientId = document.getElementById('demo-target-patient')?.value;
                if (patientId && eventType) {
                    triggerDemoEvent(patientId, eventType);
                }
            });
        });

        // Auto sequence
        document.getElementById('btn-auto-demo')?.addEventListener('click', () => {
            if (autoSequenceRunning) {
                stopAutoSequence();
            } else {
                runAutoSequence();
            }
        });

        // Reset all
        document.getElementById('btn-reset-all')?.addEventListener('click', resetAll);
    }

    async function triggerDemoEvent(patientId, eventType, confidence = 0.92) {
        try {
            const resp = await fetch('/api/demo/trigger', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    patient_id: patientId,
                    event_type: eventType,
                    confidence: confidence,
                }),
            });
            if (!resp.ok) {
                console.error('Demo trigger failed:', await resp.text());
            }
        } catch (e) {
            console.error('Demo trigger error:', e);
        }
    }

    async function resetAll() {
        stopAutoSequence();
        try {
            await fetch('/api/demo/reset', { method: 'POST' });
        } catch (e) {
            console.error('Reset error:', e);
        }
    }

    async function runAutoSequence() {
        autoSequenceRunning = true;
        const btn = document.getElementById('btn-auto-demo');
        if (btn) btn.textContent = '⏹️ Stop Sequence';

        const patients = PatientStateManager.getPatientList();
        const sequence = [
            { delay: 2000, pid: patients[1]?.patient_id, event: 'fall', msg: 'Patient B falls...' },
            { delay: 3000, pid: patients[1]?.patient_id, event: 'fall_and_pain', msg: 'Pain detected on Patient B!' },
            { delay: 4000, pid: patients[0]?.patient_id, event: 'pain', msg: 'Pain detected on Patient A' },
            { delay: 4000, pid: patients[2]?.patient_id, event: 'fall', msg: 'Patient C falls!' },
            { delay: 5000, pid: patients[1]?.patient_id, event: 'recover', msg: 'Patient B recovering...' },
            { delay: 3000, pid: patients[0]?.patient_id, event: 'recover', msg: 'Patient A recovering...' },
            { delay: 3000, pid: patients[2]?.patient_id, event: 'recover', msg: 'Patient C recovering...' },
        ];

        for (const step of sequence) {
            if (!autoSequenceRunning) break;

            await new Promise(resolve => {
                autoSequenceTimer = setTimeout(resolve, step.delay);
            });

            if (!autoSequenceRunning) break;

            if (step.pid) {
                console.log(`[AUTO] ${step.msg}`);
                await triggerDemoEvent(step.pid, step.event, 0.88 + Math.random() * 0.1);
            }
        }

        stopAutoSequence();
    }

    function stopAutoSequence() {
        autoSequenceRunning = false;
        if (autoSequenceTimer) {
            clearTimeout(autoSequenceTimer);
            autoSequenceTimer = null;
        }
        const btn = document.getElementById('btn-auto-demo');
        if (btn) btn.textContent = '▶️ Auto Sequence';
    }

    function updateVisibility(mode) {
        const panel = document.getElementById('demo-controls');
        if (panel) {
            if (mode === 'demo') {
                panel.classList.remove('demo-hidden');
            } else {
                panel.classList.add('demo-hidden');
            }
        }

        const modeIndicator = document.getElementById('mode-indicator');
        const modeLabel = document.getElementById('mode-label');
        if (modeIndicator && modeLabel) {
            if (mode === 'real') {
                modeIndicator.classList.add('real-mode');
                modeLabel.textContent = 'LIVE MONITORING';
            } else {
                modeIndicator.classList.remove('real-mode');
                modeLabel.textContent = 'DEMO MODE';
            }
        }
    }

    return {
        init,
        triggerDemoEvent,
        resetAll,
        updateVisibility,
    };
})();
