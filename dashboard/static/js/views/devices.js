/**
 * Vue « Paramètres des machines » : valeurs en direct par chambre + courbes Chart.js.
 * Alimentée par /api/devices (+ historiques) puis par les messages WS `device_batch`.
 */
(function () {
    'use strict';
    const LABELS = { iv_pump: 'Perfusion', nutrition_pump: 'Nutrition', transfusion: 'Transfusion', bp: 'Tension', ecg: 'ECG', oxygen: 'Oxygène', spo2: 'SpO2', thermometer: 'Thermomètre', glucometer: 'Glucomètre' };
    const KEY = { iv_pump: ['volumeLeftMl', 'ml'], nutrition_pump: ['volumeLeftMl', 'ml'], transfusion: ['volumeLeftMl', 'ml'], bp: ['sys', 'mmHg'], ecg: ['hr', 'bpm'], oxygen: ['flowLMin', 'l/min'], spo2: ['spo2', '%'], thermometer: ['tempC', '°C'], glucometer: ['glucose', 'g/L'] };
    const SERIES = [
        { device: 'ecg', metric: 'hr', label: 'FC (bpm)', color: '#22ff7a', axis: 'y' },
        { device: 'spo2', metric: 'spo2', label: 'SpO2 (%)', color: '#38bdf8', axis: 'y' },
        { device: 'bp', metric: 'sys', label: 'PAS (mmHg)', color: '#f472b6', axis: 'y' },
        { device: 'thermometer', metric: 'tempC', label: 'T° (°C)', color: '#facc15', axis: 'y2' },
    ];
    const ROOMS = ['101', '102', '103', '104'];
    const charts = {};
    let mounted = false;
    let devicesCache = [];

    function statusTag(s, fault) {
        if (fault && fault.code && !(fault.code === 'occlusion' || fault.code === 'empty')) return `<span class="tag tag-danger">PANNE</span> <span class="small">${Api.esc(fault.label || fault.code)}</span>`;
        const map = { running: ['En marche', 'tag-low'], alarm: ['ALARME', 'tag-danger'], paused: ['Pause', 'tag-warn'], standby: ['Veille', ''], off: ['Arrêt', ''] };
        const [t, c] = map[s] || [s, ''];
        return `<span class="tag ${c}">${t}</span>`;
    }

    function fmtMetrics(type, m) {
        if (!m) return '—';
        switch (type) {
            case 'iv_pump': return `${m.rateMlH} ml/h · reste <b>${Math.round(m.volumeLeftMl)}</b> ml${m.occlusion ? ' · <span class="tag tag-danger">occlusion</span>' : ''}`;
            case 'nutrition_pump': return `${m.rateMlH} ml/h · reste <b>${Math.round(m.volumeLeftMl)}</b> ml`;
            case 'transfusion': return `${m.rateMlH} ml/h · reste <b>${Math.round(m.volumeLeftMl)}</b> ml${m.reaction ? ' · <span class="tag tag-danger">réaction</span>' : ''}`;
            case 'bp': return `<b>${m.sys}/${m.dia}</b> mmHg · PAM ${m.map}`;
            case 'ecg': return `<b>${m.hr}</b> bpm · ${m.rhythm}${m.rr ? ' · FR ' + m.rr : ''}`;
            case 'oxygen': return `<b>${m.flowLMin}</b> l/min`;
            case 'spo2': return `<b>${m.spo2}</b> %`;
            case 'glucometer': return `<b>${m.glucose}</b> g/L`;
            case 'thermometer': return `<b>${Number(m.tempC).toFixed(1)}</b> °C`;
            default: return JSON.stringify(m);
        }
    }

    function roomCard(room, devices) {
        const rows = devices.map(d => `
            <tr id="dev-${d.device_id}">
                <td>${LABELS[d.type] || d.type}</td>
                <td class="metrics">${fmtMetrics(d.type, d.metrics)}</td>
                <td class="status">${statusTag(d.status, d.fault)}</td>
            </tr>`).join('');
        return `<div class="card" data-room="${room}">
            <h3><span class="room-pill">Chambre ${room}</span> <span class="muted small" id="dev-room-ts-${room}"></span></h3>
            <div class="grid-2" style="grid-template-columns: 1.1fr 1fr; align-items:start">
                <table class="data"><thead><tr><th>Appareil</th><th>Valeurs</th><th>État</th></tr></thead><tbody>${rows}</tbody></table>
                <div class="chart-box"><canvas id="chart-${room}"></canvas></div>
            </div>
        </div>`;
    }

    async function buildChart(room) {
        if (typeof Chart === 'undefined') return;
        const canvas = document.getElementById(`chart-${room}`);
        if (!canvas) return;
        const datasets = [];
        for (const s of SERIES) {
            let pts = [];
            try {
                const h = await Api.get(`/api/devices/${room}-${s.device}/history?metric=${s.metric}&minutes=10`);
                pts = h.points.map(p => ({ x: p.t * 1000, y: p.v }));
            } catch (_) { }
            datasets.push({ label: s.label, data: pts, borderColor: s.color, backgroundColor: s.color, borderWidth: 1.5, pointRadius: 0, tension: 0.25, yAxisID: s.axis, _key: `${room}-${s.device}:${s.metric}` });
        }
        if (charts[room]) charts[room].destroy();
        charts[room] = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: { datasets },
            options: {
                animation: false, responsive: true, maintainAspectRatio: false, parsing: false, normalized: true,
                interaction: { mode: 'nearest', intersect: false },
                plugins: { legend: { labels: { color: '#94a3b8', boxWidth: 10, font: { size: 10 } } }, tooltip: { callbacks: { title: (items) => new Date(items[0].parsed.x).toLocaleTimeString('fr-FR') } } },
                scales: {
                    x: { type: 'linear', ticks: { color: '#64748b', font: { size: 9 }, maxTicksLimit: 6, callback: (v) => new Date(v).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }, grid: { color: 'rgba(148,163,184,.08)' } },
                    y: { position: 'left', min: 40, max: 180, ticks: { color: '#64748b', font: { size: 9 } }, grid: { color: 'rgba(148,163,184,.08)' } },
                    y2: { position: 'right', min: 34, max: 41, ticks: { color: '#facc15', font: { size: 9 } }, grid: { drawOnChartArea: false } },
                },
            },
        });
    }

    function onBatch(readings) {
        if (!mounted) return;
        const now = Date.now();
        readings.forEach(r => {
            const row = document.getElementById(`dev-${r.device_id}`);
            if (row) {
                row.querySelector('.metrics').innerHTML = fmtMetrics(r.type, r.metrics);
                row.querySelector('.status').innerHTML = statusTag(r.status, r.fault);
            }
            const ts = document.getElementById(`dev-room-ts-${r.room}`);
            if (ts) ts.textContent = 'mis à jour ' + new Date(r.ts).toLocaleTimeString('fr-FR');
            const chart = charts[r.room];
            if (chart) {
                chart.data.datasets.forEach(ds => {
                    const [dev, metric] = ds._key.split(':');
                    if (dev === r.device_id && r.metrics[metric] !== undefined) {
                        ds.data.push({ x: new Date(r.ts).getTime() || now, y: r.metrics[metric] });
                        const cutoff = now - 10 * 60 * 1000;
                        while (ds.data.length && ds.data[0].x < cutoff) ds.data.shift();
                    }
                });
            }
        });
        Object.values(charts).forEach(c => c.update('none'));
    }

    window.addEventListener('hackcure:ws', (e) => {
        const m = e.detail;
        if (m.type === 'device_batch') onBatch(m.readings);
    });

    Views.register('devices', {
        title: 'Paramètres des machines',
        perm: 'view_clinical',
        async mount(el) {
            mounted = true;
            el.innerHTML = '<div class="empty">Chargement des appareils…</div>';
            try { devicesCache = await Api.get('/api/devices'); } catch (e) { el.innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
            const byRoom = {};
            devicesCache.forEach(d => (byRoom[d.room] = byRoom[d.room] || []).push(d));
            el.innerHTML = `<div class="ai-hint">Constantes des appareils simulés (VitalDB si réseau, sinon synthétiques) et de la chambre 101. Courbes : 10 dernières minutes.</div>
                <div class="grid-2">${ROOMS.map(r => roomCard(r, byRoom[r] || [])).join('')}</div>`;
            for (const r of ROOMS) await buildChart(r);
        },
        unmount() {
            mounted = false;
            Object.keys(charts).forEach(k => { try { charts[k].destroy(); } catch (_) { } delete charts[k]; });
        },
    });
})();
