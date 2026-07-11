import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { signOut } from "@/app/admin/actions";
import { site } from "@/lib/site";

export const dynamic = "force-dynamic";

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  let user = null;
  try {
    const supabase = await createClient();
    const result = await supabase.auth.getUser();
    user = result.data.user;
  } catch {
    user = null;
  }

  // Login page (and an unconfigured setup) render without the admin chrome.
  if (!user) {
    return <div className="min-h-screen bg-steel-950">{children}</div>;
  }

  return (
    <div className="min-h-screen bg-steel-950">
      <header className="border-b border-steel-700 bg-steel-900">
        <div className="hazard-bar" />
        <div className="container-wide flex h-16 items-center justify-between">
          <div className="flex items-center gap-6">
            <Link href="/admin" className="font-display text-lg font-semibold uppercase tracking-wide text-white">
              {site.name} <span className="text-hazard-500">Admin</span>
            </Link>
          </div>
          <div className="flex items-center gap-5">
            <Link
              href="/"
              target="_blank"
              className="font-mono text-xs uppercase tracking-[0.2em] text-steel-400 hover:text-hazard-400"
            >
              View site ↗
            </Link>
            <form action={signOut}>
              <button
                type="submit"
                className="font-mono text-xs uppercase tracking-[0.2em] text-steel-400 hover:text-red-400"
              >
                Sign out
              </button>
            </form>
          </div>
        </div>
      </header>
      <main className="container-wide py-10">{children}</main>
    </div>
  );
}
