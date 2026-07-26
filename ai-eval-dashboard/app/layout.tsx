import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Providers } from "@/components/providers";
import { ToastContainer } from "@/components/shared/toast";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Eval Monitor — Continuous Monitoring Dashboard",
  description:
    "Real-time monitoring of AI evaluation metrics: safety, performance, and system reliability scores across your LLM applications.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col bg-background text-foreground" suppressHydrationWarning>
        <TooltipProvider delay={0}>
          <Providers>{children}</Providers>
          <ToastContainer />
        </TooltipProvider>
      </body>
    </html>
  );
}
