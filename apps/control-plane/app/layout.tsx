import type { Metadata } from "next";
import type { ReactNode } from "react";
import { ControlPlaneNav } from "./components/ControlPlaneNav";
import "./globals.css";

export const metadata: Metadata = {
  title: "KMBL",
  description: "Autonomous creative operating system — orchestration via the Python service.",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <main>
          <ControlPlaneNav />
          {children}
        </main>
      </body>
    </html>
  );
}
