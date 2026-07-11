import Image from "next/image";
import Link from "next/link";
import { getProducts } from "@/lib/products";
import { deleteProduct } from "@/app/admin/actions";

export const dynamic = "force-dynamic";

export default async function AdminDashboard() {
  const products = await getProducts();

  return (
    <div>
      <div className="mb-8 flex items-end justify-between">
        <div>
          <p className="label">Manage</p>
          <h1 className="heading mt-2 text-3xl">Products</h1>
          <p className="mt-2 text-sm text-steel-400">
            {products.length} {products.length === 1 ? "product" : "products"} live on the site.
          </p>
        </div>
        <Link href="/admin/new" className="btn-primary">
          + New product
        </Link>
      </div>

      {products.length === 0 ? (
        <div className="frame flex flex-col items-center justify-center gap-4 py-20 text-center">
          <p className="heading text-xl text-steel-400">No products yet</p>
          <p className="max-w-sm text-sm text-steel-500">
            Add your first piece and it&apos;ll appear in the public gallery.
          </p>
          <Link href="/admin/new" className="btn-primary">
            Add a product
          </Link>
        </div>
      ) : (
        <div className="divide-y divide-steel-800 border border-steel-700">
          {products.map((product) => {
            const cover = product.product_images?.[0];
            return (
              <div
                key={product.id}
                className="flex items-center gap-4 bg-steel-900 p-4"
              >
                <div className="frame relative h-16 w-16 shrink-0 overflow-hidden">
                  {cover ? (
                    <Image
                      src={cover.url}
                      alt={cover.alt ?? product.title}
                      fill
                      sizes="64px"
                      className="object-cover"
                    />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-steel-600">
                      <span className="text-[9px]">—</span>
                    </div>
                  )}
                </div>

                <div className="min-w-0 flex-1">
                  <p className="heading truncate text-base">{product.title}</p>
                  <p className="truncate font-mono text-xs text-steel-400">
                    {[product.material, product.process].filter(Boolean).join(" · ") || "—"}
                    {" · "}
                    {product.product_images?.length ?? 0} photo
                    {(product.product_images?.length ?? 0) === 1 ? "" : "s"}
                  </p>
                </div>

                {product.featured && (
                  <span className="hidden bg-hazard-500 px-2 py-1 font-mono text-[10px] font-bold uppercase tracking-widest text-steel-950 sm:inline">
                    Featured
                  </span>
                )}

                <Link
                  href={`/admin/${product.id}/edit`}
                  className="font-mono text-xs uppercase tracking-[0.2em] text-steel-300 hover:text-hazard-400"
                >
                  Edit
                </Link>

                <form action={deleteProduct}>
                  <input type="hidden" name="id" value={product.id} />
                  <button
                    type="submit"
                    className="font-mono text-xs uppercase tracking-[0.2em] text-steel-500 hover:text-red-400"
                  >
                    Delete
                  </button>
                </form>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
