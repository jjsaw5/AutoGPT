export interface ProductImage {
  id: string;
  product_id: string;
  storage_path: string;
  url: string;
  caption: string | null;
  alt: string | null;
  sort_order: number;
  created_at: string;
}

export interface Product {
  id: string;
  title: string;
  description: string | null;
  material: string | null;
  process: string | null;
  dimensions: string | null;
  lead_time: string | null;
  featured: boolean;
  created_at: string;
}

export interface ProductWithImages extends Product {
  product_images: ProductImage[];
}
