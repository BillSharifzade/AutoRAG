import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { ChatProvider } from "@/lib/chat-store";
import { LocaleProvider } from "@/i18n";
import { Shell } from "@/components/shell";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const grotesk = Space_Grotesk({
  variable: "--font-grotesk",
  subsets: ["latin"],
});
const jbmono = JetBrains_Mono({
  variable: "--font-jbmono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "KARAG · Koinot Auto RAG",
  description:
    "Enterprise AI platform: cited knowledge, verified live figures, and generated Office documents — with retrieval-time RBAC.",
};

// Sets the theme before first paint to avoid a light/dark flash.
const themeInit = `
try {
  var t = localStorage.getItem("karag_theme");
  if (t !== "dark" && t !== "light")
    t = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = t;
} catch (e) {}
`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="ru"
      suppressHydrationWarning
      className={`${inter.variable} ${grotesk.variable} ${jbmono.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body className="app-wash min-h-full">
        <LocaleProvider>
          <AuthProvider>
            {/* Above the router on purpose: the open conversation has to outlive
                a trip to Documents and back. */}
            <ChatProvider>
              <Shell>{children}</Shell>
            </ChatProvider>
          </AuthProvider>
        </LocaleProvider>
      </body>
    </html>
  );
}
