/**
 * HackCure — Patient State Manager
 * =================================
 * Shared state machine for patient data.
 * Used by both the 3D scene and the dashboard UI.
 */

const PatientStateManager = (() => {
    // Patient data store
    const patients = {};
    const listeners = [];

    // Valid states
    const STATES = {
        NORMAL: 'normal',
        FALL: 'fall_detected',
        PAIN: 'pain_detected',
        FALL_PAIN: 'fall_and_pain',
    };

    const PRIORITIES = {
        none: 0,
        low: 1,
        high: 2,
        critical: 3,
    };

    function init(patientData) {
        Object.keys(patientData).forEach(id => {
            patients[id] = { ...patientData[id] };
        });
        notifyAll('init', null);
    }

    function getPatient(id) {
        return patients[id] || null;
    }

    function getAllPatients() {
        return { ...patients };
    }

    function getPatientList() {
        return Object.values(patients);
    }

    function updatePatient(event) {
        const id = event.patient_id;
        if (!patients[id]) return;

        const p = patients[id];
        p.state = event.state || p.state;
        p.fall_detected = event.fall_detected ?? p.fall_detected;
        p.pain_detected = event.pain_detected ?? p.pain_detected;
        p.confidence = event.confidence ?? p.confidence;
        p.alert_priority = event.alert_priority || p.alert_priority;
        p.last_event_time = event.timestamp || new Date().toISOString();
        p.source = event.source || p.source;

        notifyAll('update', { patient: p, event });
    }

    function resetAll(patientData) {
        if (patientData) {
            Object.keys(patientData).forEach(id => {
                patients[id] = { ...patientData[id] };
            });
        } else {
            Object.values(patients).forEach(p => {
                p.state = STATES.NORMAL;
                p.fall_detected = false;
                p.pain_detected = false;
                p.confidence = 0;
                p.alert_priority = 'none';
                p.source = 'system';
            });
        }
        notifyAll('reset', null);
    }

    function hasActiveAlerts() {
        return Object.values(patients).some(
            p => p.fall_detected || p.pain_detected
        );
    }

    function getCriticalPatients() {
        return Object.values(patients).filter(
            p => p.alert_priority === 'critical'
        );
    }

    // Observer pattern
    function subscribe(callback) {
        listeners.push(callback);
    }

    function notifyAll(type, data) {
        listeners.forEach(cb => {
            try { cb(type, data); }
            catch (e) { console.error('State listener error:', e); }
        });
    }

    return {
        STATES,
        PRIORITIES,
        init,
        getPatient,
        getAllPatients,
        getPatientList,
        updatePatient,
        resetAll,
        hasActiveAlerts,
        getCriticalPatients,
        subscribe,
    };
})();
