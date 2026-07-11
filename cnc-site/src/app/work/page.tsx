import type { Metadata } from "next";
import { SiteShell } from "@/components/SiteShell";
import { ProductCard } from "@/components/ProductCard";
import { getProducts } from "@/lib/products";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Work",
  description: "A gallery of custom CNC-machined and fabricated metal parts.",
};

export default async function WorkPage() {
  const products = await getProducts();

  return (
    <SiteShell>
      <section className="border-b border-steel-700">
        <div className="container-wide py-16">
          <p className="label">Portfolio</p>
          <h1 className="heading mt-2 text-4xl sm:text-5xl">The Work</h1>
          <p className="mt-4 max-w-xl text-steel-400">
            Parts we&apos;ve cut, turned and fabricated. Tap any piece for the
            material, process and dimensions.
          </p>
        </div>
      </section>

      <section className="container-wide py-14">
        {products.length > 0 ? (
          <>
            <p className="label mb-8">
              {products.length} {products.length === 1 ? "piece" : "pieces"}
            </p>
            <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {products.map((p) => (
                <ProductCard key={p.id} product={p} />
              ))}
            </div>
          </>
        ) : (
          <div className="frame flex flex-col items-center justify-center gap-3 py-24 text-center">
            <p className="heading text-xl text-steel-400">No products yet</p>
            <p className="max-w-sm text-sm text-steel-500">
              Once the shop adds work from the admin panel, it&apos;ll show up here.
            </p>
          </div>
        )}
      </section>
    </SiteShell>
  );
}
