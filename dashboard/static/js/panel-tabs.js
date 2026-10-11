/**
 * HackCure — onglets du panneau droit (Agents / Journal).
 * Le Journal contient l'Event Log existant (#event-list) sans modification.
 */
(function () {
    'use strict';
    function activate(tab) {
        document.querySelectorAll('.panel-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
        document.querySelectorAll('.panel-section').forEach(s => s.classList.toggle('hidden', s.dataset.tab !== tab));
    }
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.panel-tab').forEach(b => b.addEventListener('click', () => activate(b.dataset.tab)));
    });
    window.PanelTabs = { activate };
})();
