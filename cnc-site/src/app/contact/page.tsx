import type { Metadata } from "next";
import { SiteShell } from "@/components/SiteShell";
import { ContactForm } from "@/components/ContactForm";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Contact",
  description: `Request a quote from ${site.name}. Custom CNC machining and fabrication.`,
};

export default function ContactPage() {
  const details = [
    { label: "Phone", value: site.phone, href: `tel:${site.phone.replace(/[^\d+]/g, "")}` },
    { label: "Email", value: site.email, href: `mailto:${site.email}` },
    { label: "Location", value: site.location, href: null },
  ];

  return (
    <SiteShell>
      <section className="border-b border-steel-700">
        <div className="container-wide py-16">
          <p className="label">Get in touch</p>
          <h1 className="heading mt-2 text-4xl sm:text-5xl">Request a Quote</h1>
          <p className="mt-4 max-w-xl text-steel-400">
            Send the details of your part and we&apos;ll get back to you with
            pricing and lead time.
          </p>
        </div>
      </section>

      <section className="container-wide grid gap-12 py-14 lg:grid-cols-[1fr_1.4fr]">
        <div>
          <p className="label mb-6">Direct</p>
          <ul className="space-y-6">
            {details.map((d) => (
              <li key={d.label} className="border-l-2 border-hazard-500 pl-4">
                <p className="label">{d.label}</p>
                {d.href ? (
                  <a href={d.href} className="mt-1 block text-lg text-white hover:text-hazard-400">
                    {d.value}
                  </a>
                ) : (
                  <p className="mt-1 text-lg text-white">{d.value}</p>
                )}
              </li>
            ))}
          </ul>
          <div className="mt-10 border border-steel-700 bg-steel-900 p-5">
            <p className="label mb-2">Shop hours</p>
            <p className="text-sm text-steel-300">Mon–Fri · 7:00a – 4:00p</p>
            <p className="mt-1 text-sm text-steel-500">Quotes answered within 1 business day.</p>
          </div>
        </div>

        <div>
          <ContactForm />
        </div>
      </section>
    </SiteShell>
  );
}
