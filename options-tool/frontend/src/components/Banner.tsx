export function Banner({ text }: { text: string }) {
  return (
    <div className="bg-amber-600 text-slate-950 text-sm font-medium py-2 px-4 text-center">
      {text}
    </div>
  );
}
