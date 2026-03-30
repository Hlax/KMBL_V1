import type { Metadata } from "next";
import type { ReactNode } from "react";
import { ControlPlaneNav } from "./components/ControlPlaneNav";
import { OperatorFlowStrip } from "./components/OperatorFlowStrip";
import "./globals.css";

export const metadata: Metadata = {
  title: "KMBL Control Plane",
  description: "Operator shell — orchestration runs through the Python service.",
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
          <OperatorFlowStrip />
          {children}
        </main>
      </body>
    </html>
  );
}
