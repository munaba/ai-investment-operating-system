/* AIOS Animations — GSAP helpers for Blazor Server interop */
/* ponytail: scoped to window.aiosAnim to avoid global pollution. */
/* Upgrade path: replace with Blazor lifecycle-based animation when Blazor supports it natively. */

window.aiosAnim = {
    _activeCounts: {},

    /**
     * Count-up animation for financial numbers.
     * @param {string} elementId - DOM id of the element
     * @param {number} from - previous value
     * @param {number} to - new value  
     * @param {number} duration - ms (default 500)
     * @param {string} prefix - e.g. "" or "$"
     * @param {string} suffix - e.g. " IDR"
     */
    countUp: function (elementId, from, to, duration, prefix, suffix) {
        duration = duration || 500;
        prefix = prefix || '';
        suffix = suffix || '';

        // Cancel any running animation on this element
        if (this._activeCounts[elementId]) {
            this._activeCounts[elementId].kill();
        }

        var el = document.getElementById(elementId);
        if (!el) return;

        var obj = { val: from };
        // ponytail: expo.out for snappy feel, no overshoot on linear numeric values
        var tween = gsap.to(obj, {
            val: to,
            duration: duration / 1000,
            ease: 'expo.out',
            onUpdate: function () {
                el.textContent = prefix + Math.round(obj.val).toLocaleString('id-ID') + suffix;
            },
            onComplete: function () {
                el.textContent = prefix + Math.round(to).toLocaleString('id-ID') + suffix;
                el.setAttribute('aria-label', prefix + Math.round(to).toLocaleString('id-ID') + suffix);
                delete window.aiosAnim._activeCounts[elementId];
            }
        });
        this._activeCounts[elementId] = tween;
    },

    /**
     * Smooth tab pane transition (fade + slight slide).
     * @param {string} paneId - id of the tab-pane to show
     * @param {string} direction - 'left' or 'right'
     */
    tabTransition: function (paneId, direction) {
        var pane = document.getElementById(paneId);
        if (!pane) return;

        var offsetX = direction === 'right' ? 20 : -20;

        // Set initial state
        pane.classList.add('show', 'active');

        gsap.fromTo(pane,
            { opacity: 0, x: offsetX },
            { opacity: 1, x: 0, duration: 0.25, ease: 'power2.out' }
        );
    },

    /**
     * Table row hover micro-interaction (called on mouseenter/mouseleave).
     * @param {HTMLElement} row
     * @param {string} event - 'enter' or 'leave'
     */
    rowHover: function (row, event) {
        if (event === 'enter') {
            gsap.to(row, { x: 4, duration: 0.2, ease: 'power2.out' });
            row.style.borderLeft = '2px solid var(--lime)';
        } else {
            gsap.to(row, { x: 0, duration: 0.2, ease: 'power2.out' });
            row.style.borderLeft = '2px solid transparent';
        }
    },

    /**
     * Init table row hover for all tables. Call from OnAfterRenderAsync.
     * Uses event delegation — safe for dynamically rendered Blazor content.
     */
    initRowHover: function () {
        if (this._rowHoverBound) return;
        this._rowHoverBound = true;
        document.addEventListener('mouseenter', function (e) {
            var row = e.target.closest('.table tbody tr');
            if (row) window.aiosAnim.rowHover(row, 'enter');
        }, true);
        document.addEventListener('mouseleave', function (e) {
            var row = e.target.closest('.table tbody tr');
            if (row) window.aiosAnim.rowHover(row, 'leave');
        }, true);
    }
};
