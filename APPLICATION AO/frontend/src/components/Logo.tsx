export default function Logo({ taille = "normal" }: { taille?: "normal" | "grand" }) {
  const grand = taille === "grand";
  return (
    <div className="flex items-center gap-2.5">
      <div
        aria-hidden="true"
        className={`grid place-items-center rounded-md bg-accent font-titre font-bold text-sur-accent ${
          grand ? "size-11 text-lg" : "size-9 text-sm"
        }`}
      >
        AO
      </div>
      <span className={`font-titre font-bold tracking-tight ${grand ? "text-2xl" : "text-lg"}`}>Application AO</span>
    </div>
  );
}
