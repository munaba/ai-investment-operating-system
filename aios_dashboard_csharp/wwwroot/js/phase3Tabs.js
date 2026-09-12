// Phase3 tab switching — replaces Bootstrap JS bundle dependency (not loaded, LAN-only)
// + ARIA sync + arrow-key roving
window.phase3Tabs = {
    init: function () {
        const tablist = document.getElementById('phase3Tabs');
        if (!tablist || tablist.dataset.bound === '1') return;
        tablist.dataset.bound = '1';

        var tabs = Array.from(tablist.querySelectorAll('button[role="tab"]'));
        var panes = document.querySelectorAll('#phase3TabContent .tab-pane');
        var prevIndex = tabs.findIndex(function (b) { return b.classList.contains('active'); });
        if (prevIndex < 0) prevIndex = 0;

        function activate(idx) {
            var direction = idx > prevIndex ? 'right' : 'left';
            prevIndex = idx;
            tabs.forEach(function (b, i) {
                var isActive = i === idx;
                b.classList.toggle('active', isActive);
                b.setAttribute('aria-selected', isActive ? 'true' : 'false');
                b.setAttribute('tabindex', isActive ? '0' : '-1');
            });
            panes.forEach(function (pane) {
                pane.classList.remove('show', 'active');
            });
            var target = document.querySelector(tabs[idx].getAttribute('data-bs-target'));
            if (target && window.aiosAnim && window.aiosAnim.tabTransition) {
                window.aiosAnim.tabTransition(target.id, direction);
            } else if (target) {
                target.classList.add('show', 'active');
            }
        }

        tabs.forEach(function (btn, idx) {
            btn.addEventListener('click', function () { activate(idx); });
            btn.addEventListener('keydown', function (e) {
                if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                    e.preventDefault();
                    var dir = e.key === 'ArrowRight' ? 1 : -1;
                    var next = (idx + dir + tabs.length) % tabs.length;
                    tabs[next].focus();
                    activate(next);
                } else if (e.key === 'Home') {
                    e.preventDefault();
                    tabs[0].focus();
                    activate(0);
                } else if (e.key === 'End') {
                    e.preventDefault();
                    tabs[tabs.length - 1].focus();
                    activate(tabs.length - 1);
                }
            });
        });
    }
};
