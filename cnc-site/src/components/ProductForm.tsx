"use client";

import { useActionState, useState } from "react";
import type { FormState } from "@/lib/form";
import type { Product } from "@/lib/types";

interface ImageRow {
  key: number;
  previewUrl: string | null;
  fileName: string | null;
}

interface Props {
  action: (prev: FormState, formData: FormData) => Promise<FormState>;
  product?: Product;
  submitLabel: string;
}

let rowSeq = 0;

export function ProductForm({ action, product, submitLabel }: Props) {
  const [state, formAction, pending] = useActionState<FormState, FormData>(action, {});
  const [rows, setRows] = useState<ImageRow[]>([
    { key: rowSeq++, previewUrl: null, fileName: null },
  ]);

  function addRow() {
    setRows((r) => [...r, { key: rowSeq++, previewUrl: null, fileName: null }]);
  }

  function removeRow(key: number) {
    setRows((r) => (r.length === 1 ? r : r.filter((row) => row.key !== key)));
  }

  function onFileChange(key: number, file: File | null) {
    setRows((r) =>
      r.map((row) =>
        row.key === key
          ? {
              ...row,
              previewUrl: file ? URL.createObjectURL(file) : null,
              fileName: file?.name ?? null,
            }
          : row,
      ),
    );
  }

  return (
    <form action={formAction} className="space-y-8">
      {/* Product details */}
      <fieldset className="space-y-5">
        <legend className="label mb-3">Product details</legend>

        <div>
          <label htmlFor="title" className="field-label">
            Title *
          </label>
          <input
            id="title"
            name="title"
            required
            defaultValue={product?.title ?? ""}
            className="input"
            placeholder="Billet aluminum bracket"
          />
        </div>

        <div>
          <label htmlFor="description" className="field-label">
            Description
          </label>
          <textarea
            id="description"
            name="description"
            rows={4}
            defaultValue={product?.description ?? ""}
            className="input resize-y"
            placeholder="What it is, what it's for, anything notable about the build."
          />
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label htmlFor="material" className="field-label">
              Material
            </label>
            <input
              id="material"
              name="material"
              defaultValue={product?.material ?? ""}
              className="input"
              placeholder="6061 Aluminum"
            />
          </div>
          <div>
            <label htmlFor="process" className="field-label">
              Process
            </label>
            <input
              id="process"
              name="process"
              defaultValue={product?.process ?? ""}
              className="input"
              placeholder="3-axis CNC milling"
            />
          </div>
          <div>
            <label htmlFor="dimensions" className="field-label">
              Dimensions
            </label>
            <input
              id="dimensions"
              name="dimensions"
              defaultValue={product?.dimensions ?? ""}
              className="input"
              placeholder="12 x 6 x 2 in"
            />
          </div>
          <div>
            <label htmlFor="lead_time" className="field-label">
              Lead time
            </label>
            <input
              id="lead_time"
              name="lead_time"
              defaultValue={product?.lead_time ?? ""}
              className="input"
              placeholder="2–3 weeks"
            />
          </div>
        </div>

        <label className="flex cursor-pointer items-center gap-3">
          <input
            type="checkbox"
            name="featured"
            defaultChecked={product?.featured ?? false}
            className="h-4 w-4 accent-hazard-500"
          />
          <span className="font-mono text-xs uppercase tracking-[0.15em] text-steel-300">
            Feature on the homepage
          </span>
        </label>
      </fieldset>

      {/* Photos + info */}
      <fieldset className="space-y-4">
        <legend className="label mb-1">
          Photos {product ? "(add more)" : ""}
        </legend>
        <p className="text-xs text-steel-500">
          Upload one or more pictures. For each, add a caption and a short
          description — the caption shows under the photo on the product page.
        </p>

        <div className="space-y-4">
          {rows.map((row, i) => (
            <div key={row.key} className="border border-steel-700 bg-steel-900 p-4">
              <div className="mb-3 flex items-center justify-between">
                <span className="font-mono text-xs text-hazard-500">
                  Photo {String(i + 1).padStart(2, "0")}
                </span>
                <button
                  type="button"
                  onClick={() => removeRow(row.key)}
                  className="font-mono text-xs uppercase tracking-widest text-steel-500 hover:text-red-400"
                >
                  Remove
                </button>
              </div>

              <div className="grid gap-4 sm:grid-cols-[auto_1fr]">
                <div className="flex flex-col gap-3">
                  <div className="frame flex h-28 w-28 items-center justify-center overflow-hidden">
                    {row.previewUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={row.previewUrl}
                        alt="preview"
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <span className="label text-center text-[10px]">Preview</span>
                    )}
                  </div>
                  <input
                    type="file"
                    name="image"
                    accept="image/*"
                    onChange={(e) => onFileChange(row.key, e.target.files?.[0] ?? null)}
                    className="w-28 text-xs text-steel-400 file:mr-2 file:border file:border-steel-600 file:bg-steel-800 file:px-2 file:py-1 file:text-xs file:text-steel-200"
                  />
                </div>

                <div className="space-y-3">
                  <input
                    name="caption"
                    className="input"
                    placeholder="Caption — e.g. Finished part, anodized black"
                  />
                  <input
                    name="alt"
                    className="input"
                    placeholder="Short description (for accessibility / SEO)"
                  />
                </div>
              </div>
            </div>
          ))}
        </div>

        <button
          type="button"
          onClick={addRow}
          className="btn-ghost w-full border-dashed"
        >
          + Add another photo
        </button>
      </fieldset>

      {state.error && (
        <p className="border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {state.error}
        </p>
      )}

      <button type="submit" disabled={pending} className="btn-primary w-full">
        {pending ? "Saving…" : submitLabel}
      </button>
    </form>
  );
}
