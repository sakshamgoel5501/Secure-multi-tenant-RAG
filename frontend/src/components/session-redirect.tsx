"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useSession } from "@/components/session-provider";

export function SessionRedirect() {
  const { account, loading } = useSession();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!account && pathname !== "/login") router.replace("/login");
    else if (account?.must_change_password && pathname !== "/account") router.replace("/account");
    else if (account && pathname === "/login") router.replace("/");
  }, [loading, account, pathname, router]);

  return null;
}

