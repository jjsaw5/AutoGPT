import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { SiteShell } from "@/components/SiteShell";
import { getProduct } from "@/lib/products";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const product = await getProduct(id);
  return { title: product?.title ?? "Work" };
}

export default async function ProductPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const product = await getProduct(id);
  if (!product) notFound();

  const images = product.product_images ?? [];
  const specs = [
    { label: "Material", value: product.material },
    { label: "Process", value: product.process },
    { label: "Dimensions", value: product.dimensions },
    { label: "Lead time", value: product.lead_time },
  ].filter((s) => s.value);

  return (
    <SiteShell>
      <div className="container-wide py-10">
        <Link
          href="/work"
          className="font-mono text-xs uppercase tracking-[0.2em] text-steel-400 hover:text-hazard-400"
        >
          ← All work
        </Link>

        <div className="mt-8 grid gap-10 lg:grid-cols-[1.4fr_1fr]">
          {/* Images + their info */}
          <div className="space-y-6">
            {images.length > 0 ? (
              images.map((img, i) => (
                <figure key={img.id} className="frame overflow-hidden">
                  <div className="relative aspect-[4/3]">
                    <Image
                      src={img.url}
                      alt={img.alt ?? product.title}
                      fill
                      priority={i === 0}
                      sizes="(max-width: 1024px) 100vw, 60vw"
                      className="object-cover"
                    />
                  </div>
                  {img.caption && (
                    <figcaption className="border-t border-steel-700 bg-steel-900 px-4 py-3 text-sm text-steel-400">
                      <span className="mr-2 font-mono text-xs text-hazard-500">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      {img.caption}
                    </figcaption>
                  )}
                </figure>
              ))
            ) : (
              <div className="frame flex aspect-[4/3] items-center justify-center bg-grid-steel bg-[size:24px_24px] text-steel-600">
                <span className="label">No photos</span>
              </div>
            )}
          </div>

          {/* Details */}
          <div className="lg:sticky lg:top-24 lg:self-start">
            {product.featured && (
              <span className="mb-4 inline-block bg-hazard-500 px-2 py-1 font-mono text-[10px] font-bold uppercase tracking-widest text-steel-950">
                Featured build
              </span>
            )}
            <h1 className="heading text-4xl">{product.title}</h1>

            {product.description && (
              <p className="mt-5 whitespace-pre-line leading-relaxed text-steel-300">
                {product.description}
              </p>
            )}

            {specs.length > 0 && (
              <dl className="mt-8 border-t border-steel-700">
                {specs.map((s) => (
                  <div
                    key={s.label}
                    className="flex justify-between gap-4 border-b border-steel-800 py-3"
                  >
                    <dt className="label">{s.label}</dt>
                    <dd className="text-right font-mono text-sm text-white">
                      {s.value}
                    </dd>
                  </div>
                ))}
              </dl>
            )}

            <Link href="/contact" className="btn-primary mt-8 w-full">
              Request something like this
            </Link>
          </div>
        </div>
      </div>
    </SiteShell>
  );
}
