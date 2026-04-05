import "./globals.css";

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full">
      <head>
        <title>ERP AI Assistant — Multi-Agent System</title>
        <meta name="description" content="AI-powered ERP chat interface — FAST-NUCES FYP" />
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </head>
      <body className="h-full flex flex-col">{children}</body>
    </html>
  );
}
