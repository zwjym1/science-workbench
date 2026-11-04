import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {title: '知序 · AI 科普编导工作台', description: '从真实证据出发，创作有价值的科普内容'};
export default function RootLayout({ children }: Readonly<{children: React.ReactNode}>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
