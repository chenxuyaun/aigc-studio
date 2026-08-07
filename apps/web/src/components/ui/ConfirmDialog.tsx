import { Dialog } from "@/components/ui/Dialog";

import { Button } from "./Button";

/** 危险操作确认框：说明清楚对象与后果，而不是只问“是否确认”。 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmText = "确认",
  loading = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmText?: string;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <Dialog open={open} onClose={onCancel} title={title} className="sm:max-w-sm">
      <div className="p-5">
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="flex justify-end gap-2 border-t border-border p-4">
        <Button variant="ghost" onClick={onCancel}>
          取消
        </Button>
        <Button variant="danger" onClick={onConfirm} loading={loading}>
          {confirmText}
        </Button>
      </div>
    </Dialog>
  );
}
