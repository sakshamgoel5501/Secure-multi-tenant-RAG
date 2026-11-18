import { adminProxy } from "@/lib/server/admin";

export const GET = () => adminProxy("/admin/eval");

