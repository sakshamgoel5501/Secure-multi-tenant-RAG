import { Suspense } from "react";
import { DocumentDetail } from "@/components/document-detail";

type Props = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tenant?: string }>;
};

async function Detail({ params, searchParams }: Props) {
  const { id } = await params;
  const { tenant } = await searchParams;
  return <DocumentDetail id={id} tenant={tenant ?? "tenant-1"} />;
}

export default function Page(props: Props) {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading document…</p>}>
      <Detail {...props} />
    </Suspense>
  );
}

