import { useState, useCallback } from 'react';

// Simple toast hook for export feedback
export function useExportToast() {
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  const showToast = useCallback((message: string, type: 'success' | 'error' = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  }, []);

  const hideToast = useCallback(() => setToast(null), []);

  return { toast, showToast, hideToast };
}