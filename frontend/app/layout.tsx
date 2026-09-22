import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "cgen - AI CAD generator",
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
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,500;12..96,600;12..96,700;12..96,800&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        {/*
THESIS: cgen is an open making-kit — color-coded compartments and a landing shelf of project trays; refuses monochrome brutalist CAD chrome.
OWN-WORLD: warm ivory canvas, white surfaces, coral/cobalt/mint/amber roles, 12–20px radii, Bricolage Grotesque + Plex Mono for measurements only.
STORY: creator lands on the tray shelf, opens a workspace, describes a part, previews it, inspects and downloads — color marks the compartment.
FIRST VIEWPORT: tray cards + create action; workspace view: topbar, session pills, rounded viewport + inspector, generate full-height on prompt.
FORM: assigned direction "Open Kit", seed b5593edb.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and DESIGN.md.
*/}
        {children}
      </body>
    </html>
  );
}
