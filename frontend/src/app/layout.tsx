import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";
import { SessionProvider } from "@/components/session-provider";
import { SessionRedirect } from "@/components/session-redirect";
import { Sidebar } from "@/components/sidebar";
import { ThemeProvider } from "@/components/theme-provider";

export const metadata: Metadata = {
  title: "Vault",
  description: "Multi-tenant retrieval with authorization enforced at query time",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="antialiased">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <SessionProvider>
            <div className="flex min-h-screen">
              <Suspense fallback={<aside className="sticky top-0 h-screen w-60 shrink-0 border-r bg-card/40" />}>
                <Sidebar />
              </Suspense>
              <main className="min-w-0 flex-1 px-10 py-8">
                <div className="mx-auto max-w-5xl">{children}</div>
              </main>
            </div>
            <Suspense fallback={null}>
              <SessionRedirect />
            </Suspense>
          </SessionProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}

