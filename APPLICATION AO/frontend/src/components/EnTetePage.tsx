import type { ReactNode } from "react";

interface Proprietes {
  surtitre: string;
  titre: string;
  sousTitre?: string;
  actions?: ReactNode;
}

export default function EnTetePage({ surtitre, titre, sousTitre, actions }: Proprietes) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex min-w-0 flex-col gap-1.5">
        <span className="text-xs font-semibold uppercase tracking-[0.08em] text-accent">{surtitre}</span>
        <h1 className="font-titre text-3xl font-bold tracking-tight">{titre}</h1>
        {sousTitre && <p className="max-w-3xl text-attenue">{sousTitre}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2.5">{actions}</div>}
    </div>
  );
}
