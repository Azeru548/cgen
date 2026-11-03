import type { Metadata, Viewport } from "next";
import { AuthProvider } from "@/components/AuthProvider";
import { TelemetryBridge } from "@/components/TelemetryBridge";
import "./globals.css";
import "./landing.css";

/** Canonical origin for absolute URLs in metadata. Baked in at build time. */
const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://cgen.pxxl.click"
).replace(/\/+$/, "");

const TITLE = "cgen — language to solid";
const DESCRIPTION =
  "Describe a part in plain language and get validated STEP and STL CAD files from a deterministic CadQuery engine. No code execution, append-only revisions.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: TITLE,
    template: "%s · cgen",
  },
  description: DESCRIPTION,
  applicationName: "cgen",
  alternates: { canonical: "/" },
  /* Both icons are plain static files in public/ — no app/ metadata routes, so
     nothing runs image processing at request time in production. */
  icons: { icon: "/favicon.ico", apple: "/apple-touch-icon.png" },
  /* Launch posts unfurl from these. The image is a static 1200×630 card built
     by scripts/make-og.js, so no OG image route runs at request time. */
  openGraph: {
    type: "website",
    url: "/",
    siteName: "cgen",
    title: TITLE,
    description: DESCRIPTION,
    images: [
      {
        url: "/og.png",
        width: 1200,
        height: 630,
        alt: "cgen — describe a part, download STEP + STL",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
    images: ["/og.png"],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0e1014",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <TelemetryBridge />
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
