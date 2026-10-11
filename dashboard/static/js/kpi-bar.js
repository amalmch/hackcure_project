/**
 * HackCure — bandeau KPI en bas du mode 3D : patients hospitalisés, risques ouverts par sévérité,
 * personnel en service, température moyenne, alertes pharmacie. Source : /api/kpi + messages WS.
 */
const KpiBar = (() => {
    'use strict';
    let timer = null;
    let data = null;

    function render() {
        const el = document.getElementById('kpi-bar'); if (!el || !data) return;
        const r = data.risks || {};
        const dot = (c) => `<span class="kpi-dot" style="background:${c}"></span>`;
        el.innerHTML = `
            <div class="kpi"><span class="kpi-label">Patients hospitalisés</span><span class="kpi-value">${data.patients}</span><span class="kpi-sub">${data.rooms} chambres</span></div>
            <div class="kpi"><span class="kpi-label">Risques ouverts</span>
                <span class="kpi-value">${data.open_risks}</span>
                <span class="kpi-sub">${dot('#a855f7')}${r.critical || 0} ${dot('#ef4444')}${r.high || 0} ${dot('#f59e0b')}${r.medium || 0} ${dot('#22c55e')}${r.low || 0}</span></div>
            <div class="kpi"><span class="kpi-label">Personnel en service</span><span class="kpi-value">${data.staff_on_duty}</span><span class="kpi-sub">${data.staff_in_rooms} en chambre</span></div>
            <div class="kpi"><span class="kpi-label">Température moyenne</span><span class="kpi-value">${data.avg_temp != null ? data.avg_temp.toFixed(1) + '<span class="metric-unit">°C</span>' : '—'}</span><span class="kpi-sub">${data.avg_humidity != null ? 'humidité ' + Math.round(data.avg_humidity) + ' %' : ''}</span></div>
            <div class="kpi ${data.spo2_min != null && data.spo2_min < 90 ? 'kpi-alert' : ''}"><span class="kpi-label">SpO2 la plus basse</span><span class="kpi-value">${data.spo2_min != null ? Math.round(data.spo2_min) + '<span class="metric-unit">%</span>' : '—'}</span><span class="kpi-sub">${data.spo2_min_room ? 'chambre ' + data.spo2_min_room : 'oxymètres de pouls'}</span></div>
            <div class="kpi"><span class="kpi-label">Alertes pharmacie</span><span class="kpi-value">${data.pharmacy_alerts}</span><span class="kpi-sub">${data.low_stock} stock bas · ${data.expiring} péremption</span></div>`;
    }

    async function refresh() {
        try { data = await Api.get('/api/kpi', { noRedirect: true }); render(); } catch (_) { }
    }

    window.addEventListener('hackcure:ws', (e) => {
        const m = e.detail;
        if (m.type === 'kpi') { data = Object.assign(data || {}, m.data); render(); }
        else if (m.type === 'risk' || m.type === 'staff_visit') refresh();
    });
    document.addEventListener('DOMContentLoaded', () => {
        Auth.onReady(() => { refresh(); timer = setInterval(refresh, 15000); });
    });
    return { refresh };
})();
