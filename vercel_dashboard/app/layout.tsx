import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GEP · Jumeau Numérique HVAC",
  description:
    "Green Energy Park — supervision temps réel des capteurs IoT et prévision LSTM par zone, depuis InfluxDB Cloud.",
  icons: {
    icon: "/gep-logo.jpeg",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fr">
      <body>{children}</body>
    </html>
  );
}
