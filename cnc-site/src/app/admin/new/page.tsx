import Link from "next/link";
import { ProductForm } from "@/components/ProductForm";
import { createProduct } from "@/app/admin/actions";

export default function NewProductPage() {
  return (
    <div className="mx-auto max-w-2xl">
      <Link
        href="/admin"
        className="font-mono text-xs uppercase tracking-[0.2em] text-steel-400 hover:text-hazard-400"
      >
        ← Products
      </Link>
      <h1 className="heading mb-8 mt-4 text-3xl">New Product</h1>
      <ProductForm action={createProduct} submitLabel="Publish product" />
    </div>
  );
}
