import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "cgen — AI CAD generator",
  description:
    "Describe a part in natural language, preview the generated 3D model, and download STEP/STL CAD files.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
