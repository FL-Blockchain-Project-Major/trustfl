import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TrustFL",
  description: "Federated Learning Platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50">
        <main className="container mx-auto p-4">{children}</main>
      </body>
    </html>
  );
}
