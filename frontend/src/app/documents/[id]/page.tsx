import { DocumentDetail } from "@/components/document-detail";

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tenant?: string }>;
}) {
  const { id } = await params;
  const { tenant } = await searchParams;
  return <DocumentDetail id={id} tenant={tenant ?? "tenant-1"} />;
}


