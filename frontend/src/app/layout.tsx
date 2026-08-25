import type { Metadata } from "next";
import { Vazirmatn } from "next/font/google";
import "./globals.css";

const vazirmatn = Vazirmatn({
  subsets: ["arabic", "latin"],
  variable: "--font-vazirmatn",
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "مسکن‌یار | جستجوی هوشمند اجاره در تهران",
  description: "پلتفرم کشف اجاره مسکن با درک محاوره فارسی و امتیازدهی دسترسی به حمل‌ونقل عمومی تهران.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fa" dir="rtl">
      <body className={`${vazirmatn.variable} font-sans antialiased`}>{children}</body>
    </html>
  );
}
