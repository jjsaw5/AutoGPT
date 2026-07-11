import Link from "next/link";
import { SiteShell } from "@/components/SiteShell";

export default function NotFound() {
  return (
    <SiteShell>
      <div className="container-wide flex min-h-[50vh] flex-col items-center justify-center py-24 text-center">
        <p className="font-display text-7xl font-bold text-hazard-500">404</p>
        <h1 className="heading mt-4 text-2xl">Page not found</h1>
        <p className="mt-2 text-steel-400">That part isn&apos;t on the shelf.</p>
        <Link href="/" className="btn-primary mt-8">
          Back home
        </Link>
      </div>
    </SiteShell>
  );
}
