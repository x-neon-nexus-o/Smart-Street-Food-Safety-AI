import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Smart Street Food Safety AI",
  description: "Food safety assistant for Indian street vendors, reviewers, and consumers",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <body className="min-h-full flex flex-col font-sans" suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
