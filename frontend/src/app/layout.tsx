import type { Metadata } from "next";
import "./globals.css";
import { PersonaProvider } from "@/components/persona-provider";
import { Sidebar } from "@/components/sidebar";
import { ThemeProvider } from "@/components/theme-provider";

export const metadata: Metadata = {
  title: "Secure RAG",
  description: "Multi-tenant retrieval with authorization enforced at query time",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="antialiased">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <PersonaProvider>
            <div className="flex min-h-screen">
              <Sidebar />
              <main className="min-w-0 flex-1 px-10 py-8">
                <div className="mx-auto max-w-5xl">{children}</div>
              </main>
            </div>
          </PersonaProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}


