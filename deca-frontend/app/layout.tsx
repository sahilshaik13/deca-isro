import type { Metadata, Viewport } from 'next'
import { Space_Grotesk, IBM_Plex_Mono } from 'next/font/google'
import './globals.css'

const display = Space_Grotesk({
  subsets: ['latin'],
  variable: '--font-display',
  weight: ['400', '500', '600', '700'],
  display: 'swap',
  preload: false,
})

const mono = IBM_Plex_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  weight: ['400', '500'],
  display: 'swap',
  preload: false,
})

export const metadata: Metadata = {
  title: 'DECA — Orchestrator Dashboard',
  description:
    'DECA SD-WAN orchestrator: analyzer predictions, TT&C/Payload mission classes, human-gated steers.',
  icons: {
    icon: '/icon.svg',
    shortcut: '/icon.svg',
  },
}

export const viewport: Viewport = {
  colorScheme: 'light',
  themeColor: '#ffffff',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className={`${display.variable} ${mono.variable} light`}>
      <body className="antialiased font-[family-name:var(--font-mono)] bg-[var(--deca-bg)] text-[var(--deca-ink)]">
        {children}
      </body>
    </html>
  )
}
