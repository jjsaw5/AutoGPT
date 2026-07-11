# CNC Portfolio Site

An industrial-styled website for a metal CNC shop. Visitors can browse the
shop's work and send a quote request; the owner has a password-protected
admin panel to add, edit and remove products (with photos and details).

Built with **Next.js (App Router)**, **Tailwind CSS**, **Supabase**
(Postgres + Storage + Auth) and **Resend** (contact-form email).

---

## What's included

| Area              | Route                | Notes                                                        |
| ----------------- | -------------------- | ----------------------------------------------------------- |
| Home              | `/`                  | Hero, capabilities, featured work, CTA                      |
| Work / portfolio  | `/work`              | Grid of every product                                       |
| Product detail    | `/work/[id]`         | Photos with captions + material/process/dimensions specs    |
| Contact           | `/contact`           | Quote form that emails the shop owner                       |
| Admin login       | `/admin/login`       | Supabase email + password                                   |
| Admin dashboard   | `/admin`             | List / delete products                                      |
| Add product       | `/admin/new`         | Product details + multi-photo upload with per-photo info    |
| Edit product      | `/admin/[id]/edit`   | Edit fields, add photos, delete existing photos             |

---

## 1. Install

```bash
cd cnc-site
npm install
```

## 2. Create a Supabase project

1. Go to <https://supabase.com>, create a free project.
2. Open **SQL Editor → New query**, paste the contents of
   [`supabase/schema.sql`](./supabase/schema.sql) and run it. This creates the
   `products` and `product_images` tables, the `product-images` storage bucket,
   and the security rules (public can read; only signed-in admin can write).
3. Create the admin login: **Authentication → Users → Add user**, enter the
   owner's email + a password (check "Auto confirm user").
4. Copy your API keys from **Project Settings → API**.

## 3. Set up a Resend account (contact emails)

1. Sign up at <https://resend.com> and create an API key.
2. For real use, verify the shop's sending domain. For quick testing you can
   send from `onboarding@resend.dev`.

## 4. Configure environment variables

```bash
cp .env.example .env.local
```

Then fill in `.env.local`:

```ini
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
RESEND_API_KEY=...
CONTACT_EMAIL_TO=owner@example.com          # where quote requests land
CONTACT_EMAIL_FROM=Website <onboarding@resend.dev>

# Branding shown around the site
NEXT_PUBLIC_SHOP_NAME=Ironline Machine Works
NEXT_PUBLIC_SHOP_PHONE=(555) 012-3456
NEXT_PUBLIC_SHOP_EMAIL=owner@example.com
NEXT_PUBLIC_SHOP_LOCATION=Cleveland, OH
```

## 5. Run it

```bash
npm run dev
```

Open <http://localhost:3000>. Sign in at <http://localhost:3000/admin/login>
and add your first product.

---

## Deploying

Deploy to **Vercel** (recommended for Next.js): push the repo, import the
project, set the `cnc-site` folder as the root, and add the same environment
variables in the Vercel dashboard. Supabase and Resend run as-is in production.

## How photos + info work

When the owner adds a product, they upload one or more photos. **Each photo**
has its own **caption** (shown under the picture on the product page) and a
short **description** used for accessibility/SEO. Product-level details
(material, process, dimensions, lead time, featured flag) are entered once per
product.

## Security notes

- Product/image reads are public; all writes require an authenticated admin
  session (enforced by Supabase Row Level Security **and** Next.js middleware).
- The contact form has a honeypot field and server-side validation.
- No secrets are committed — everything sensitive lives in `.env.local`.
