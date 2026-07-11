import { createClient } from "@/lib/supabase/server";
import type { ProductWithImages } from "@/lib/types";

const SELECT = "*, product_images(*)";

function sortImages(products: ProductWithImages[]) {
  for (const p of products) {
    p.product_images?.sort((a, b) => a.sort_order - b.sort_order);
  }
  return products;
}

export async function getProducts(options?: {
  featuredOnly?: boolean;
  limit?: number;
}): Promise<ProductWithImages[]> {
  try {
    const supabase = await createClient();
    let query = supabase
      .from("products")
      .select(SELECT)
      .order("created_at", { ascending: false });

    if (options?.featuredOnly) query = query.eq("featured", true);
    if (options?.limit) query = query.limit(options.limit);

    const { data, error } = await query;
    if (error) throw error;
    return sortImages((data as ProductWithImages[]) ?? []);
  } catch {
    // Supabase not configured yet, or a transient error — show an empty gallery.
    return [];
  }
}

export async function getProduct(id: string): Promise<ProductWithImages | null> {
  try {
    const supabase = await createClient();
    const { data, error } = await supabase
      .from("products")
      .select(SELECT)
      .eq("id", id)
      .single();
    if (error) throw error;
    return sortImages([data as ProductWithImages])[0] ?? null;
  } catch {
    return null;
  }
}
