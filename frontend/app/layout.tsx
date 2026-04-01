import type { Metadata } from "next";
import SettingsLauncher from "@/components/settings/SettingsLauncher";
import "./globals.css";

export const metadata: Metadata = {
  title: "ArchMind Dashboard",
  description: "Internal dashboard for ArchMind projects",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        {children}
        <SettingsLauncher />
      </body>
    </html>
  );
}
