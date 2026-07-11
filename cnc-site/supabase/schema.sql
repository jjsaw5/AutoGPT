-- =============================================================================
-- CNC Portfolio Site — database schema
-- Run this in the Supabase SQL editor (Dashboard -> SQL -> New query).
-- =============================================================================

-- --- Products -----------------------------------------------------------------
create table if not exists public.products (
  id          uuid primary key default gen_random_uuid(),
  title       text not null,
  description text,
  material    text,           -- e.g. "6061 Aluminum", "304 Stainless"
  process     text,           -- e.g. "3-axis CNC milling", "CNC turning"
  dimensions  text,           -- e.g. "12 x 6 x 2 in"
  lead_time   text,           -- e.g. "2-3 weeks"
  featured    boolean not null default false,
  created_at  timestamptz not null default now()
);

-- --- Product images -----------------------------------------------------------
-- One product can have several pictures. Each picture carries its own
-- descriptive info (the caption / alt text the admin enters at upload time).
create table if not exists public.product_images (
  id           uuid primary key default gen_random_uuid(),
  product_id   uuid not null references public.products (id) on delete cascade,
  storage_path text not null,       -- path within the storage bucket
  url          text not null,       -- public URL
  caption      text,                -- "info about the picture" shown under it
  alt          text,                -- accessibility / description
  sort_order   int not null default 0,
  created_at   timestamptz not null default now()
);

create index if not exists product_images_product_id_idx
  on public.product_images (product_id);

-- =============================================================================
-- Row Level Security
--   * Anyone (anonymous) can READ products + images -> the public gallery.
--   * Only authenticated users (the admin) can INSERT / UPDATE / DELETE.
-- =============================================================================
alter table public.products       enable row level security;
alter table public.product_images enable row level security;

drop policy if exists "public read products" on public.products;
create policy "public read products"
  on public.products for select
  using (true);

drop policy if exists "admin write products" on public.products;
create policy "admin write products"
  on public.products for all
  to authenticated
  using (true)
  with check (true);

drop policy if exists "public read product_images" on public.product_images;
create policy "public read product_images"
  on public.product_images for select
  using (true);

drop policy if exists "admin write product_images" on public.product_images;
create policy "admin write product_images"
  on public.product_images for all
  to authenticated
  using (true)
  with check (true);

-- =============================================================================
-- Storage bucket for product photos
-- =============================================================================
insert into storage.buckets (id, name, public)
values ('product-images', 'product-images', true)
on conflict (id) do nothing;

drop policy if exists "public read product image files" on storage.objects;
create policy "public read product image files"
  on storage.objects for select
  using (bucket_id = 'product-images');

drop policy if exists "admin upload product image files" on storage.objects;
create policy "admin upload product image files"
  on storage.objects for insert
  to authenticated
  with check (bucket_id = 'product-images');

drop policy if exists "admin update product image files" on storage.objects;
create policy "admin update product image files"
  on storage.objects for update
  to authenticated
  using (bucket_id = 'product-images');

drop policy if exists "admin delete product image files" on storage.objects;
create policy "admin delete product image files"
  on storage.objects for delete
  to authenticated
  using (bucket_id = 'product-images');
