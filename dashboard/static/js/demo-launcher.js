/**
 * HackCure — bouton « Lancer la démo » : choix du scénario (simulateur embarqué ou MQTT).
 */
const DemoLauncher = (() => {
    'use strict';
    const ICON = { full_demo_v2: '🌟', full_demo: '🎬', fall_demo: '🚨', nurse_resolves: '🧑‍⚕️', sepsis_trend: '🦠', iv_empty: '💧', fever_101: '🔥', room_overheat_102: '☀️', desaturation_103: '🫁', cardiac_event_102: '❤️',
        hypoglycemia_104: '🩸', seizure_103: '⚡', deterioration_101: '📉', machine_error_103: '⚙️', normal_night: '🌙', stop: '⏹️' };
    const ORDER = ['full_demo_v2', 'full_demo', 'fall_demo', 'fever_101', 'room_overheat_102', 'desaturation_103', 'sepsis_trend', 'cardiac_event_102', 'hypoglycemia_104', 'seizure_103', 'deterioration_101', 'machine_error_103', 'iv_empty', 'normal_night', 'stop'];
    let scenarios = [];
    let current = null;

    async function load() {
        try { const d = await Api.get('/api/demo/scenarios', { noRedirect: true }); scenarios = d.scenarios; current = d.current; } catch (_) { scenarios = []; }
    }

    function render() {
        const menu = document.getElementById('demo-menu'); if (!menu) return;
        const rank = (n) => { const i = ORDER.indexOf(n); return i < 0 ? 99 : i; };
        const isRes = (s) => (s.resolves && s.resolves.length) || s.name === 'nurse_resolves';
        const list = scenarios.filter(s => !isRes(s)).sort((a, b) => rank(a.name) - rank(b.name));
        const res = scenarios.filter(isRes).sort((a, b) => a.name.localeCompare(b.name));
        const item = (s) => `<button data-name="${s.name}">${ICON[s.name] || (isRes(s) ? '🧑‍⚕️' : '▶')} <b>${s.name}</b> <span class="muted small">(chambre ${s.room}${s.duration ? ', ' + s.duration + ' s' : ''})</span><span class="demo-desc">${Api.esc(s.description)}</span></button>`;
        menu.innerHTML = `<div class="notif-head"><span>Scénarios de démonstration</span>${current && current.name ? `<span class="tag tag-in_progress">en cours : ${current.name}</span>` : ''}</div>`
            + list.map(item).join('') + `<div class="notif-head"><span>Résolutions par un soignant</span><span class="muted small">lancées aussi par « Je prends en charge »</span></div>` + res.map(item).join('');
        menu.querySelectorAll('button[data-name]').forEach(b => b.addEventListener('click', () => start(b.dataset.name)));
    }

    async function start(name) {
        document.getElementById('demo-menu')?.classList.add('hidden');
        try {
            const r = await Api.post('/api/demo/scenario', { name });
            current = r.scenario;
            Api.toast(`▶ Scénario « ${name} » lancé (${r.via})`, 'success');
            if (Views.current !== 'twin') Views.show('twin');
            const sc = scenarios.find(s => s.name === name);
            if (sc && sc.room && typeof HospitalScene !== 'undefined') HospitalScene.zoomToRoom(sc.room);
        } catch (e) { Api.toast('Scénario impossible : ' + e.message, 'critical'); }
    }

    function toggle() {
        const menu = document.getElementById('demo-menu'); if (!menu) return;
        const show = menu.classList.contains('hidden');
        document.getElementById('notif-dropdown')?.classList.add('hidden');
        if (show) { load().then(render); }
        menu.classList.toggle('hidden', !show);
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('btn-launch-demo')?.addEventListener('click', (e) => { e.stopPropagation(); toggle(); });
        document.addEventListener('click', (e) => { if (!e.target.closest('#demo-menu') && !e.target.closest('#btn-launch-demo')) document.getElementById('demo-menu')?.classList.add('hidden'); });
    });
    window.addEventListener('hackcure:ws', (e) => {
        const m = e.detail;
        if (m.type !== 'scenario') return;
        if (m.event === 'scenario_step') Api.toast(`🎬 ${m.name} · chambre ${m.room} · ${m.action}${m.params && m.params.posture ? ' → ' + m.params.posture : ''}`, 'info');
        else if (m.event === 'scenario_finished') { current = null; Api.toast(`🎬 Scénario « ${m.name} » terminé`, 'success'); }
        else if (m.event === 'scenario_started') current = { name: m.name, room: m.room };
    });
    return { start, load };
})();
