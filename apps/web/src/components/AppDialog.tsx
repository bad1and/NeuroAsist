import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

export function AppDialog({
  open,
  title,
  description,
  children,
  onClose,
}: {
  open: boolean;
  title: string;
  description?: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      className="app-dialog"
      ref={ref}
      aria-labelledby="app-dialog-title"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      {open && <>
        <div className="dialog-heading">
          <div>
            <h2 id="app-dialog-title">{title}</h2>
            {description && <p>{description}</p>}
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Закрыть диалог">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        {children}
      </>}
    </dialog>
  );
}
