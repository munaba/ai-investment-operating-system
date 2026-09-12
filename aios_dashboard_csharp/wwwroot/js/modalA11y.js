// Phase2 modal accessibility: inert background, focus-trap, Escape, focus-return
window.modalA11y = {
    _originalFocus: null,
    _modalRoot: null,
    _focusableEls: [],
    _firstFocusable: null,
    _lastFocusable: null,

    open: function(modalSelector) {
        const modal = document.querySelector(modalSelector);
        if (!modal) return;
        
        this._modalRoot = modal;
        
        // Save original focus
        this._originalFocus = document.activeElement;
        
        // Set inert on siblings (main content outside modal)
        const siblings = Array.from(document.body.children).filter(el => 
            el !== modal && 
            el.tagName !== 'SCRIPT' && 
            el.tagName !== 'NEXT-ROUTE-ANNOUNCER' &&
            !el.hasAttribute('inert')
        );
        siblings.forEach(el => el.setAttribute('inert', ''));
        modal.dataset.inertSiblings = siblings.map(el => el.tagName + (el.id ? '#' + el.id : '')).join(',');
        
        // Setup focus trap
        this._updateFocusableElements();
        if (this._firstFocusable) {
            this._firstFocusable.focus();
        }
        
        // Bind handlers
        modal.addEventListener('keydown', this._handleKeydown.bind(this));
    },

    close: function(modalSelector) {
        const modal = document.querySelector(modalSelector);
        if (!modal) return;
        
        // Remove inert from siblings
        const inertSiblings = modal.dataset.inertSiblings;
        if (inertSiblings) {
            const siblings = Array.from(document.body.children).filter(el => el.hasAttribute('inert'));
            siblings.forEach(el => el.removeAttribute('inert'));
            delete modal.dataset.inertSiblings;
        }
        
        // Return focus
        if (this._originalFocus && this._originalFocus.focus) {
            this._originalFocus.focus();
        }
        
        // Cleanup
        modal.removeEventListener('keydown', this._handleKeydown.bind(this));
        this._originalFocus = null;
        this._modalRoot = null;
        this._focusableEls = [];
    },

    _updateFocusableElements: function() {
        if (!this._modalRoot) return;
        
        const focusableSelectors = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
        this._focusableEls = Array.from(this._modalRoot.querySelectorAll(focusableSelectors));
        this._firstFocusable = this._focusableEls[0] || null;
        this._lastFocusable = this._focusableEls[this._focusableEls.length - 1] || null;
    },

    _handleKeydown: function(e) {
        // Escape to close
        if (e.key === 'Escape') {
            e.preventDefault();
            const closeBtn = this._modalRoot.querySelector('.btn-close, [data-dismiss="modal"]');
            if (closeBtn) closeBtn.click();
            return;
        }
        
        // Tab trap
        if (e.key === 'Tab') {
            if (this._focusableEls.length === 0) {
                e.preventDefault();
                return;
            }
            
            if (e.shiftKey) {
                // Shift+Tab: wrap from first to last
                if (document.activeElement === this._firstFocusable) {
                    e.preventDefault();
                    this._lastFocusable.focus();
                }
            } else {
                // Tab: wrap from last to first
                if (document.activeElement === this._lastFocusable) {
                    e.preventDefault();
                    this._firstFocusable.focus();
                }
            }
        }
    }
};
