"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import type { FormState } from "@/lib/form";

const BUCKET = "product-images";

function fields(formData: FormData) {
  const title = String(formData.get("title") ?? "").trim();
  return {
    title,
    description: String(formData.get("description") ?? "").trim() || null,
    material: String(formData.get("material") ?? "").trim() || null,
    process: String(formData.get("process") ?? "").trim() || null,
    dimensions: String(formData.get("dimensions") ?? "").trim() || null,
    lead_time: String(formData.get("lead_time") ?? "").trim() || null,
    featured: formData.get("featured") === "on",
  };
}

async function requireUser() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) throw new Error("Not authenticated");
  return supabase;
}

async function uploadImages(
  supabase: Awaited<ReturnType<typeof createClient>>,
  productId: string,
  formData: FormData,
  startOrder: number,
) {
  const files = formData.getAll("image") as File[];
  const captions = formData.getAll("caption").map(String);
  const alts = formData.getAll("alt").map(String);

  let order = startOrder;
  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    if (!file || typeof file === "string" || file.size === 0) continue;

    const ext = file.name.includes(".") ? file.name.split(".").pop() : "jpg";
    const path = `${productId}/${crypto.randomUUID()}.${ext}`;

    const { error: uploadError } = await supabase.storage
      .from(BUCKET)
      .upload(path, file, { contentType: file.type || "image/jpeg", upsert: false });
    if (uploadError) throw uploadError;

    const { data: pub } = supabase.storage.from(BUCKET).getPublicUrl(path);

    const { error: rowError } = await supabase.from("product_images").insert({
      product_id: productId,
      storage_path: path,
      url: pub.publicUrl,
      caption: captions[i]?.trim() || null,
      alt: alts[i]?.trim() || null,
      sort_order: order++,
    });
    if (rowError) throw rowError;
  }
}

export async function createProduct(
  _prev: FormState,
  formData: FormData,
): Promise<FormState> {
  const data = fields(formData);
  if (!data.title) return { error: "A title is required." };

  try {
    const supabase = await requireUser();
    const { data: product, error } = await supabase
      .from("products")
      .insert(data)
      .select()
      .single();
    if (error) throw error;

    await uploadImages(supabase, product.id, formData, 0);
  } catch (err) {
    return { error: err instanceof Error ? err.message : "Could not save product." };
  }

  revalidatePath("/");
  revalidatePath("/work");
  redirect("/admin");
}

export async function updateProduct(
  id: string,
  _prev: FormState,
  formData: FormData,
): Promise<FormState> {
  const data = fields(formData);
  if (!data.title) return { error: "A title is required." };

  try {
    const supabase = await requireUser();
    const { error } = await supabase.from("products").update(data).eq("id", id);
    if (error) throw error;

    const { count } = await supabase
      .from("product_images")
      .select("*", { count: "exact", head: true })
      .eq("product_id", id);

    await uploadImages(supabase, id, formData, count ?? 0);
  } catch (err) {
    return { error: err instanceof Error ? err.message : "Could not update product." };
  }

  revalidatePath("/");
  revalidatePath("/work");
  revalidatePath(`/work/${id}`);
  redirect("/admin");
}

export async function deleteProduct(formData: FormData) {
  const id = String(formData.get("id") ?? "");
  if (!id) return;

  const supabase = await requireUser();

  const { data: images } = await supabase
    .from("product_images")
    .select("storage_path")
    .eq("product_id", id);

  if (images?.length) {
    await supabase.storage.from(BUCKET).remove(images.map((i) => i.storage_path));
  }
  await supabase.from("products").delete().eq("id", id);

  revalidatePath("/");
  revalidatePath("/work");
  revalidatePath("/admin");
}

export async function deleteImage(formData: FormData) {
  const imageId = String(formData.get("imageId") ?? "");
  const productId = String(formData.get("productId") ?? "");
  if (!imageId) return;

  const supabase = await requireUser();

  const { data: image } = await supabase
    .from("product_images")
    .select("storage_path")
    .eq("id", imageId)
    .single();

  if (image) {
    await supabase.storage.from(BUCKET).remove([image.storage_path]);
    await supabase.from("product_images").delete().eq("id", imageId);
  }

  revalidatePath("/");
  revalidatePath("/work");
  if (productId) {
    revalidatePath(`/work/${productId}`);
    redirect(`/admin/${productId}/edit`);
  }
}

export async function signOut() {
  const supabase = await createClient();
  await supabase.auth.signOut();
  redirect("/admin/login");
}
