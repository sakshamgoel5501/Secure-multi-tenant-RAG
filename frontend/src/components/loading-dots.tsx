export function LoadingDots({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-label={label} className="flex items-center gap-1.5 py-6">
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </div>
  );
}


