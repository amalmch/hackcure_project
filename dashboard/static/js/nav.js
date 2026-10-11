/**
 * HackCure — navigation du panneau gauche + vues HTML affichées PAR-DESSUS le viewport 3D.
 * Le canvas Three.js reste vivant en arrière-plan (jamais réinitialisé).
 *
 *   Views.register('pharmacy', { title: 'Pharmacie', perm: 'view_pharmacy', mount(el) {...}, unmount() {...} })
 *   Views.show('pharmacy')  /  Views.show('twin')  (retour à la 3D)
 */
const Views = (() => {
    'use strict';
    const registry = {};
    let current = 'twin';

    function register(id, def) { registry[id] = def; }
    function get(id) { return registry[id]; }

    function show(id) {
        const overlay = document.getElementById('view-overlay');
        const body = document.getElementById('view-body');
        const title = document.getElementById('view-title');
        if (!overlay || !body) return;
        if (current !== 'twin' && registry[current] && registry[current].unmount) {
            try { registry[current].unmount(); } catch (e) { console.error(e); }
        }
        body.innerHTML = '';
        current = id;
        document.querySelectorAll('#main-nav .nav-btn').forEach(b => b.classList.toggle('active', b.dataset.view === id));
        if (id === 'twin' || !registry[id]) {
            overlay.classList.add('view-hidden');
            document.body.classList.remove('view-open');
            return;
        }
        const def = registry[id];
        if (title) title.textContent = def.title || id;
        overlay.classList.remove('view-hidden');
        document.body.classList.add('view-open');
        try { def.mount(body); } catch (e) { console.error('View mount error', id, e); body.innerHTML = `<div class="view-error">Erreur d'affichage : ${Api.esc(e.message)}</div>`; }
    }

    function refresh() { if (current !== 'twin' && registry[current]) show(current); }

    return { register, get, show, refresh, get current() { return current; } };
})();

const Nav = (() => {
    'use strict';
    // id, libellé, icône, permission de visualisation
    const ITEMS = [
        { id: 'twin', label: 'Jumeau numérique 3D', icon: '🏥', perm: 'view_twin' },
        { id: 'staff', label: 'Personnel présent', icon: '🧑‍⚕️', perm: 'view_clinical' },
        { id: 'pharmacy', label: 'Pharmacie', icon: '💊', perm: 'view_pharmacy' },
        { id: 'cameras', label: 'Caméras', icon: '📷', perm: 'view_clinical' },
        { id: 'devices', label: 'Paramètres des machines', icon: '📈', perm: 'view_clinical' },
        { id: 'detection', label: 'Centre de détection', icon: '🛰️', perm: 'view_clinical' },
        { id: 'command', label: 'Centre de commande', icon: '🎛️', perm: 'view_command' },
        { id: 'patients', label: 'Patients', icon: '🧾', perm: 'view_patients' },
        { id: 'shift', label: 'Rapport de garde', icon: '🌙', perm: 'view_shift_report' },
        { id: 'report', label: 'Rapport médecin', icon: '📝', perm: 'view_medical_docs' },
        { id: 'prescription', label: 'Ordonnance', icon: '℞', perm: 'view_medical_docs' },
        { id: 'history', label: 'Historique patients', icon: '🗂️', perm: 'view_history' },
        { id: 'dossier', label: 'Dossier médical', icon: '📚', perm: 'open_medical_record' },
        { id: 'diagnostics', label: 'Diagnostics live', icon: '🧬', perm: 'view_diagnostics' },
        { id: 'treatment', label: 'Ordonnance de traitement', icon: '💉', perm: 'view_treatment_orders' },
        { id: 'careplan', label: 'Plan de soins', icon: '🗓️', perm: 'view_care_plan' },
        { id: 'psych', label: 'Psychologie', icon: '🧠', perm: 'view_psychology' },
        { id: 'predictions', label: 'Prédictions', icon: '🔮', perm: 'view_predictions' },
        { id: 'ambulances', label: 'Ambulances', icon: '🚑', perm: 'view_ambulances' },
        { id: 'agentsmap', label: 'Carte des agents', icon: '🕸️', perm: 'view_twin' },
        { id: 'users', label: 'Utilisateurs', icon: '👥', perm: 'manage_users' },
    ];

    function render() {
        const nav = document.getElementById('main-nav');
        if (!nav) return;
        nav.innerHTML = '';
        ITEMS.forEach(it => {
            const allowed = Auth.can(it.perm);
            if (!allowed && it.perm === 'manage_users') return; // masqué (owner seulement)
            const b = document.createElement('button');
            b.className = 'nav-btn' + (it.id === Views.current ? ' active' : '') + (allowed ? '' : ' disabled');
            b.dataset.view = it.id;
            b.disabled = !allowed;
            b.title = allowed ? it.label : `${it.label} — non autorisé pour votre rôle`;
            b.innerHTML = `<span class="nav-icon">${it.icon}</span><span class="nav-label">${it.label}</span>`;
            b.addEventListener('click', () => Views.show(it.id));
            nav.appendChild(b);
        });
        const close = document.getElementById('view-close');
        if (close && !close.dataset.bound) { close.dataset.bound = '1'; close.addEventListener('click', () => Views.show('twin')); }
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && Views.current !== 'twin') Views.show('twin'); });
    }

    Auth.onReady(render);
    return { render, ITEMS };
})();
