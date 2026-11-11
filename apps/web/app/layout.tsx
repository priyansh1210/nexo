import type { Metadata } from "next";
import { IBM_Plex_Sans } from "next/font/google";
import "./globals.css";

const plex = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Nexo", template: "%s · Nexo" },
  description: "Self-hostable customer-success assistant",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={plex.variable}>
      <body className="min-h-dvh font-sans">{children}</body>
    </html>
  );
}
