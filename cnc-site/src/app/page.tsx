import Link from "next/link";
import { SiteShell } from "@/components/SiteShell";
import { ProductCard } from "@/components/ProductCard";
import { getProducts } from "@/lib/products";
import { site } from "@/lib/site";

export const dynamic = "force-dynamic";

const capabilities = [
  { code: "01", title: "CNC Milling", desc: "3- & 4-axis milling for precision parts and prototypes." },
  { code: "02", title: "CNC Turning", desc: "Lathe work for shafts, bushings and round stock." },
  { code: "03", title: "Fabrication", desc: "Welding, cutting and assembly of finished weldments." },
  { code: "04", title: "Custom One-Offs", desc: "Repairs, brackets and made-to-order metal work." },
];

const stats = [
  { value: "±0.001\"", label: "Tolerances" },
  { value: "15+ yrs", label: "On the floor" },
  { value: "Steel · Alu", label: "Materials" },
];

export default async function HomePage() {
  const featured = await getProducts({ featuredOnly: true, limit: 6 });
  const recent = await getProducts({ limit: 6 });
  const showcase = featured.length > 0 ? featured : recent;

  return (
    <SiteShell>
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-steel-700">
        <div className="absolute inset-0 bg-grid-steel bg-[size:32px_32px] opacity-60" />
        <div className="absolute inset-0 bg-gradient-to-b from-steel-950/40 via-steel-950/70 to-steel-950" />
        <div className="container-wide relative py-24 sm:py-32">
          <p className="label mb-5 flex items-center gap-3">
            <span className="inline-block h-px w-10 bg-hazard-500" />
            {site.location} · Precision Metalwork
          </p>
          <h1 className="heading max-w-3xl text-5xl leading-[0.95] sm:text-7xl">
            Metal, machined to{" "}
            <span className="text-hazard-500">exact spec.</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg text-steel-300">
            {site.name} builds custom CNC-machined and fabricated parts — from
            one-off prototypes to production runs. If it&apos;s metal, we can make it.
          </p>
          <div className="mt-9 flex flex-wrap gap-4">
            <Link href="/work" className="btn-primary">
              View the work
            </Link>
            <Link href="/contact" className="btn-ghost">
              Request a quote
            </Link>
          </div>

          <div className="mt-16 grid max-w-2xl grid-cols-3 gap-px border border-steel-700 bg-steel-700">
            {stats.map((s) => (
              <div key={s.label} className="bg-steel-900 px-4 py-5">
                <p className="font-display text-2xl font-semibold text-hazard-500">
                  {s.value}
                </p>
                <p className="label mt-1">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Capabilities */}
      <section className="container-wide py-20">
        <div className="mb-10 flex items-end justify-between">
          <div>
            <p className="label">What we do</p>
            <h2 className="heading mt-2 text-3xl">Capabilities</h2>
          </div>
        </div>
        <div className="grid gap-px border border-steel-700 bg-steel-700 sm:grid-cols-2 lg:grid-cols-4">
          {capabilities.map((c) => (
            <div key={c.code} className="group bg-steel-900 p-6 transition-colors hover:bg-steel-850">
              <span className="font-mono text-xs text-hazard-500">/{c.code}</span>
              <h3 className="heading mt-4 text-lg">{c.title}</h3>
              <p className="mt-2 text-sm text-steel-400">{c.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Featured work */}
      <section className="container-wide py-8 pb-20">
        <div className="mb-10 flex items-end justify-between">
          <div>
            <p className="label">Selected builds</p>
            <h2 className="heading mt-2 text-3xl">Featured work</h2>
          </div>
          <Link href="/work" className="hidden font-mono text-xs uppercase tracking-[0.2em] text-hazard-400 hover:text-hazard-500 sm:inline">
            All work →
          </Link>
        </div>

        {showcase.length > 0 ? (
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {showcase.map((p) => (
              <ProductCard key={p.id} product={p} />
            ))}
          </div>
        ) : (
          <div className="frame flex flex-col items-center justify-center gap-3 py-20 text-center">
            <p className="heading text-xl text-steel-400">Nothing here yet</p>
            <p className="max-w-sm text-sm text-steel-500">
              Products added from the admin panel will appear here.
            </p>
          </div>
        )}
      </section>

      {/* CTA */}
      <section className="border-y border-steel-700 bg-steel-900">
        <div className="container-wide flex flex-col items-start gap-6 py-16 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="heading text-3xl">Have a part in mind?</h2>
            <p className="mt-2 text-steel-400">
              Send over a drawing or a description — we&apos;ll get back with a quote.
            </p>
          </div>
          <Link href="/contact" className="btn-primary shrink-0">
            Get in touch
          </Link>
        </div>
      </section>
    </SiteShell>
  );
}
