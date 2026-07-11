import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ProductForm } from "@/components/ProductForm";
import { getProduct } from "@/lib/products";
import { updateProduct, deleteImage } from "@/app/admin/actions";

export const dynamic = "force-dynamic";

export default async function EditProductPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const product = await getProduct(id);
  if (!product) notFound();

  const action = updateProduct.bind(null, id);
  const images = product.product_images ?? [];

  return (
    <div className="mx-auto max-w-2xl">
      <Link
        href="/admin"
        className="font-mono text-xs uppercase tracking-[0.2em] text-steel-400 hover:text-hazard-400"
      >
        ← Products
      </Link>
      <h1 className="heading mb-8 mt-4 text-3xl">Edit Product</h1>

      {images.length > 0 && (
        <div className="mb-10">
          <p className="label mb-3">Current photos</p>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            {images.map((img) => (
              <div key={img.id} className="frame overflow-hidden">
                <div className="relative aspect-square">
                  <Image
                    src={img.url}
                    alt={img.alt ?? product.title}
                    fill
                    sizes="200px"
                    className="object-cover"
                  />
                </div>
                <div className="flex items-center justify-between gap-2 border-t border-steel-700 bg-steel-900 px-3 py-2">
                  <span className="truncate font-mono text-[11px] text-steel-400">
                    {img.caption ?? "No caption"}
                  </span>
                  <form action={deleteImage}>
                    <input type="hidden" name="imageId" value={img.id} />
                    <input type="hidden" name="productId" value={product.id} />
                    <button
                      type="submit"
                      className="shrink-0 font-mono text-[11px] uppercase tracking-widest text-steel-500 hover:text-red-400"
                    >
                      Delete
                    </button>
                  </form>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <ProductForm action={action} product={product} submitLabel="Save changes" />
    </div>
  );
}
