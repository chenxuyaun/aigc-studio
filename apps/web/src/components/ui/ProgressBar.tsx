export function ProgressBar({ progress, status }: { progress: number; status: string }) {
  return (
    <div className="space-y-1">
      <div className="h-2 overflow-hidden rounded-full bg-secondary">
        <div
          className="h-full bg-primary transition-all"
          style={{ width: `${progress}%` }}
          role="progressbar"
          aria-valuenow={progress}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
      <p className="font-mono-ui text-xs text-muted-foreground">
        {status} · {progress}%
      </p>
    </div>
  );
}
