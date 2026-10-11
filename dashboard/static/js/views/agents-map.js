/**
 * Vue « Carte des agents » (V2, étape 9) : quel agent Python, quel workflow n8n, quels déclencheurs.
 * La détection et la sévérité restent dans le backend ; n8n orchestre le raisonnement LLM et les notifications.
 */
(() => {
    'use strict';
    async function render(el) {
        let d;
        try { d = await Api.get('/api/agents/map'); } catch (e) { el.innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
        const online = d.n8n.status === 'online';
        const byAgent = {};
        d.rows.forEach(r => (byAgent[r.agent] = byAgent[r.agent] || []).push(r));
        const calls = (c) => c && (c.n8n || c.local || c.fallback) ? `${c.n8n || 0} via n8n · ${c.local || 0} en local${c.fallback ? ' · ' + c.fallback + ' de secours' : ''}` : '—';
        el.innerHTML = `<div class="ai-hint">${Api.esc(d.principle)}</div>
            <div class="card"><h3>n8n <span class="tag ${online ? 'tag-ok' : 'tag-warn'}">${{ online: 'en ligne : orchestration par n8n', offline: 'hors ligne : repli local', disabled: 'désactivé : agents locaux' }[d.n8n.status]}</span>
                <span class="muted small">${d.rows.length} workflows · ${Object.keys(byAgent).length} agents</span></h3>
            <table class="data"><thead><tr><th>Agent (Python)</th><th>Workflow n8n</th><th>Rôle du workflow</th><th>Déclencheur</th><th>Appels depuis le démarrage</th></tr></thead><tbody>
            ${Object.keys(byAgent).sort().map(a => byAgent[a].map((r, i) => `<tr>${i === 0 ? `<td rowspan="${byAgent[a].length}"><b>${Api.esc(a)}</b></td>` : ''}<td><span class="tag tag-n8n">${Api.esc(r.workflow)}</span></td>
                <td class="small">${Api.esc(r.title)}</td><td class="small">${Api.esc(r.trigger)}</td><td class="muted small">${calls(r.calls)}</td></tr>`).join('')).join('')}</tbody></table></div>`;
    }
    Views.register('agentsmap', { title: 'Carte des agents', perm: 'view_twin', mount(el) { render(el); }, unmount() { } });
})();
