import Link from "next/link";
import { site } from "@/lib/site";

const nav = [
  { href: "/", label: "Home" },
  { href: "/work", label: "Work" },
  { href: "/contact", label: "Contact" },
];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-steel-700 bg-steel-950/90 backdrop-blur">
      <div className="hazard-bar" />
      <div className="container-wide flex h-16 items-center justify-between">
        <Link href="/" className="group flex items-center gap-3">
          <span className="flex h-8 w-8 items-center justify-center border border-hazard-500 font-display text-lg font-bold text-hazard-500">
            {site.name.charAt(0)}
          </span>
          <span className="font-display text-lg font-semibold uppercase tracking-wide text-white">
            {site.name}
          </span>
        </Link>
        <nav className="flex items-center gap-6">
          {nav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="font-mono text-xs uppercase tracking-[0.2em] text-steel-300 transition-colors hover:text-hazard-400"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
