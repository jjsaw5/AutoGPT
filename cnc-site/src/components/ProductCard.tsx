import Image from "next/image";
import Link from "next/link";
import type { ProductWithImages } from "@/lib/types";

export function ProductCard({ product }: { product: ProductWithImages }) {
  const cover = product.product_images?.[0];

  return (
    <Link href={`/work/${product.id}`} className="group block">
      <div className="frame aspect-[4/3] overflow-hidden">
        {cover ? (
          <Image
            src={cover.url}
            alt={cover.alt ?? product.title}
            fill
            sizes="(max-width: 640px) 100vw, 33vw"
            className="object-cover transition-transform duration-500 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-grid-steel bg-[size:20px_20px] text-steel-600">
            <span className="label">No photo</span>
          </div>
        )}
        {product.featured && (
          <span className="absolute left-0 top-0 bg-hazard-500 px-2 py-1 font-mono text-[10px] font-bold uppercase tracking-widest text-steel-950">
            Featured
          </span>
        )}
      </div>
      <div className="mt-3">
        <h3 className="heading text-base transition-colors group-hover:text-hazard-400">
          {product.title}
        </h3>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-xs text-steel-400">
          {product.material && <span>{product.material}</span>}
          {product.process && <span className="text-steel-500">/ {product.process}</span>}
        </div>
      </div>
    </Link>
  );
}
