/**
 * Logo « D’Aplomb » : un fil à plomb stylisé (point d'accroche, fil vertical,
 * plomb effilé vers le bas) dans un carré arrondi vert sauge, suivi du nom.
 * Même dessin que public/favicon.svg.
 */
export default function Logo({ taille = "normal" }: { taille?: "normal" | "grand" }) {
  const grand = taille === "grand";
  return (
    <div className="flex items-center gap-2.5">
      <svg aria-hidden="true" focusable="false" viewBox="0 0 32 32" className={`shrink-0 ${grand ? "size-11" : "size-9"}`}>
        <rect width="32" height="32" rx="6" className="fill-accent" />
        <circle cx="16" cy="5.5" r="2" className="fill-sur-accent" />
        <path d="M16 7v5" strokeWidth="2.25" className="stroke-sur-accent" />
        <rect x="13.5" y="11" width="5" height="2.75" rx="0.75" className="fill-sur-accent" />
        <path d="M16 12.75c3.2 0 6 2 6 4.9L16 28l-6-10.35c0-2.9 2.8-4.9 6-4.9z" className="fill-sur-accent" />
      </svg>
      <span className={`font-titre font-bold tracking-tight ${grand ? "text-2xl" : "text-lg"}`}>D’Aplomb</span>
    </div>
  );
}
