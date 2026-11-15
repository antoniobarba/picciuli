import * as Dialog from '@radix-ui/react-dialog';
import type { ReactNode } from 'react';

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  wide?: boolean;
  children: ReactNode;
}

/** A centred dialog on wide screens and a bottom sheet on phones. */
export function Modal({ open, onClose, title, description, wide, children }: ModalProps) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="overlay" />
        <Dialog.Content
          className={`dialog${wide ? ' dialog-wide' : ''}`}
          onOpenAutoFocus={(event) => {
            // Focus the first field rather than the close button.
            const target = (event.currentTarget as HTMLElement).querySelector<HTMLElement>(
              '[data-autofocus], input:not([type=hidden]), select, textarea',
            );
            if (target) {
              event.preventDefault();
              target.focus();
            }
          }}
        >
          <div className="dialog-header">
            <Dialog.Title className="dialog-title">{title}</Dialog.Title>
            <Dialog.Close className="icon-button" aria-label="Close">
              ✕
            </Dialog.Close>
          </div>
          {description ? (
            <Dialog.Description className="dialog-description">{description}</Dialog.Description>
          ) : (
            <Dialog.Description className="sr-only">{typeof title === 'string' ? title : 'Dialog'}</Dialog.Description>
          )}
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
