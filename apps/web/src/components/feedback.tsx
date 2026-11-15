import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import { Modal } from './Modal';

// Toasts

type ToastKind = 'info' | 'success' | 'warning' | 'error';

interface Toast {
  id: number;
  kind: ToastKind;
  title?: string;
  message: string;
}

type Notify = (message: string, options?: { title?: string; kind?: ToastKind }) => void;

const ToastContext = createContext<Notify>(() => {});

export function useNotify(): Notify {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback<Notify>(
    (message, { title, kind = 'info' } = {}) => {
      const id = next.current++;
      setToasts((current) => [...current.slice(-3), { id, kind, title, message }]);
      window.setTimeout(() => dismiss(id), kind === 'error' || kind === 'warning' ? 8000 : 4000);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast-${toast.kind}`} onClick={() => dismiss(toast.id)}>
            {toast.title ? <strong>{toast.title}</strong> : null}
            <span>{toast.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

// Confirmation

export interface ConfirmOptions {
  title: string;
  message?: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm>(() => Promise.resolve(false));

export function useConfirm(): Confirm {
  return useContext(ConfirmContext);
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<(ConfirmOptions & { resolve: (answer: boolean) => void }) | null>(null);

  const confirm = useCallback<Confirm>(
    (options) => new Promise<boolean>((resolve) => setRequest({ ...options, resolve })),
    [],
  );

  const answer = (value: boolean) => {
    request?.resolve(value);
    setRequest(null);
  };

  const value = useMemo(() => confirm, [confirm]);
  return (
    <ConfirmContext.Provider value={value}>
      {children}
      <Modal open={request !== null} onClose={() => answer(false)} title={request?.title ?? ''}>
        {request?.message ? <div className="form-body">{request.message}</div> : null}
        <div className="form-actions">
          <button type="button" className="button" onClick={() => answer(false)}>
            Cancel
          </button>
          <button
            type="button"
            className={`button ${request?.danger === false ? 'primary' : 'danger'}`}
            onClick={() => answer(true)}
            data-autofocus
          >
            {request?.confirmLabel ?? 'Delete'}
          </button>
        </div>
      </Modal>
    </ConfirmContext.Provider>
  );
}
