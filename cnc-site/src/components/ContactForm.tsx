"use client";

import { useState } from "react";

type Status = "idle" | "sending" | "sent" | "error";

export function ContactForm() {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("sending");
    setError(null);

    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form).entries());

    try {
      const res = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error ?? "Something went wrong.");
      }
      setStatus("sent");
      form.reset();
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Something went wrong.");
    }
  }

  if (status === "sent") {
    return (
      <div className="frame p-8 text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center border border-hazard-500 text-2xl text-hazard-500">
          ✓
        </div>
        <p className="heading text-xl">Message sent</p>
        <p className="mt-2 text-sm text-steel-400">
          Thanks — we&apos;ll get back to you shortly.
        </p>
        <button
          type="button"
          onClick={() => setStatus("idle")}
          className="btn-ghost mt-6"
        >
          Send another
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {/* Honeypot: hidden from users, catches bots */}
      <input
        type="text"
        name="company"
        tabIndex={-1}
        autoComplete="off"
        className="hidden"
        aria-hidden="true"
      />

      <div className="grid gap-5 sm:grid-cols-2">
        <div>
          <label htmlFor="name" className="field-label">
            Name *
          </label>
          <input id="name" name="name" required className="input" placeholder="Jane Smith" />
        </div>
        <div>
          <label htmlFor="email" className="field-label">
            Email *
          </label>
          <input
            id="email"
            name="email"
            type="email"
            required
            className="input"
            placeholder="jane@example.com"
          />
        </div>
      </div>

      <div>
        <label htmlFor="phone" className="field-label">
          Phone
        </label>
        <input id="phone" name="phone" className="input" placeholder="(555) 000-0000" />
      </div>

      <div>
        <label htmlFor="message" className="field-label">
          Project details *
        </label>
        <textarea
          id="message"
          name="message"
          required
          rows={6}
          className="input resize-y"
          placeholder="Tell us about the part — material, quantity, tolerances, timeline. Attach a drawing later by email if you have one."
        />
      </div>

      {status === "error" && (
        <p className="border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </p>
      )}

      <button type="submit" disabled={status === "sending"} className="btn-primary w-full">
        {status === "sending" ? "Sending…" : "Send message"}
      </button>
    </form>
  );
}
