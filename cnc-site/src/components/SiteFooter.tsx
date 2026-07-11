import Link from "next/link";
import { site } from "@/lib/site";

export function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-steel-700 bg-steel-900">
      <div className="hazard-bar" />
      <div className="container-wide grid gap-10 py-12 sm:grid-cols-3">
        <div>
          <p className="heading text-lg">{site.name}</p>
          <p className="mt-2 max-w-xs text-sm text-steel-400">{site.tagline}</p>
        </div>
        <div>
          <p className="label mb-3">Shop</p>
          <ul className="space-y-2 text-sm">
            <li>
              <Link href="/work" className="hover:text-hazard-400">
                View work
              </Link>
            </li>
            <li>
              <Link href="/contact" className="hover:text-hazard-400">
                Request a quote
              </Link>
            </li>
            <li>
              <Link href="/admin" className="text-steel-500 hover:text-hazard-400">
                Admin
              </Link>
            </li>
          </ul>
        </div>
        <div>
          <p className="label mb-3">Contact</p>
          <ul className="space-y-2 text-sm text-steel-400">
            <li>
              <a href={`tel:${site.phone.replace(/[^\d+]/g, "")}`} className="hover:text-hazard-400">
                {site.phone}
              </a>
            </li>
            <li>
              <a href={`mailto:${site.email}`} className="hover:text-hazard-400">
                {site.email}
              </a>
            </li>
            <li>{site.location}</li>
          </ul>
        </div>
      </div>
      <div className="border-t border-steel-800">
        <div className="container-wide flex flex-col gap-2 py-5 text-xs text-steel-500 sm:flex-row sm:items-center sm:justify-between">
          <span className="font-mono uppercase tracking-[0.2em]">
            © {new Date().getFullYear()} {site.name}
          </span>
          <span className="font-mono uppercase tracking-[0.2em]">
            Built for the shop floor
          </span>
        </div>
      </div>
    </footer>
  );
}
