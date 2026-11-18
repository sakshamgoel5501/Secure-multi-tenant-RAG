export default function CustomPage() {
  return (
    <div className="max-w-3xl space-y-3">
      <h1 className="text-xl font-semibold tracking-tight">Your tab</h1>
      <p className="text-sm text-muted-foreground">
        A blank page for whatever you want to add. To enable it, set <code className="font-mono">ready: true</code> on
        the &quot;Your tab&quot; entry in <code className="font-mono">src/components/sidebar.tsx</code>, rename the label,
        and build the page here. Call the backend through a route handler in <code className="font-mono">src/app/api/</code>,
        like the others.
      </p>
    </div>
  );
}

