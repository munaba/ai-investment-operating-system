// Phase3 tab switching — replaces Bootstrap JS bundle dependency (not loaded, LAN-only)
// Updated: smooth transitions via anime.js
window.phase3Tabs = {
    init: function () {
        const tablist = document.getElementById('phase3Tabs');
        if (!tablist || tablist.dataset.bound === '1') return;
        tablist.dataset.bound = '1';

        var prevIndex = 0;

        tablist.querySelectorAll('button[data-bs-toggle="tab"]').forEach(function (btn, idx) {
            btn.addEventListener('click', function () {
                var direction = idx > prevIndex ? 'right' : 'left';
                prevIndex = idx;

                // deactivate all
                tablist.querySelectorAll('.nav-link').forEach(function (b) { b.classList.remove('active'); });
                document.querySelectorAll('#phase3TabContent .tab-pane').forEach(function (pane) {
                    pane.classList.remove('show', 'active');
                });
                // activate clicked with transition
                btn.classList.add('active');
                var target = document.querySelector(btn.getAttribute('data-bs-target'));
                if (target && window.aiosAnim && window.aiosAnim.tabTransition) {
                    window.aiosAnim.tabTransition(target.id, direction);
                } else if (target) {
                    target.classList.add('show', 'active');
                }
            });
        });
    }
};
