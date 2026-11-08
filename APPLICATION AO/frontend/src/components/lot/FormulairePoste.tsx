import { Calculator } from "lucide-react";
import { useState } from "react";

import { api } from "../../api/client";
import type { GenrePoste, OptionLot, PagePrix } from "../../api/types";
import { formaterEuros } from "../../lib/format";
import { CLASSE_CHAMP, Champ } from "../Filtres";
import EditeurRiche from "./EditeurRiche";

export interface Brouillon {
  genre: GenrePoste;
  titre: string;
  description: string;
  unite: string;
  quantite: string;
  prix_unitaire: string;
  option_id: string;
}

interface Proprietes {
  numero: string;
  brouillon: Brouillon;
  surChangement: (changement: Partial<Brouillon>) => void;
  options: OptionLot[];
  police: string;
  taille: number;
  modifie: boolean;
  enregistrement: boolean;
  surEnregistrer: () => void;
  surAbandonner: () => void;
  identifiant: number;
  /** Change quand l'éditeur doit relire le contenu enregistré (bouton « Annuler »). */
  versionEditeur: number;
}

export function nombreSaisi(valeur: string): number | null {
  const texte = valeur.replace(/\s/g, "").replace(",", ".");
  if (!texte) return null;
  const nombre = Number(texte);
  return Number.isFinite(nombre) ? nombre : null;
}

export default function FormulairePoste({
  numero,
  brouillon,
  surChangement,
  options,
  police,
  taille,
  modifie,
  enregistrement,
  surEnregistrer,
  surAbandonner,
  identifiant,
  versionEditeur,
}: Proprietes) {
  const quantite = nombreSaisi(brouillon.quantite);
  const prix = nombreSaisi(brouillon.prix_unitaire);
  const montant = quantite != null && prix != null ? Math.round(quantite * prix * 100) / 100 : null;

  return (
    <section aria-labelledby="titre-poste" className="flex flex-col gap-4 rounded-xl border border-bordure bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="titre-poste" className="font-titre text-lg font-semibold">
          <span className="mr-2 text-accent">{numero}</span>
          {brouillon.genre === "CHAPITRE" ? "Chapitre" : brouillon.genre === "ARTICLE" ? "Article (CCTP seul)" : "Ouvrage (CCTP + DPGF)"}
        </h2>
        <div className="flex items-center gap-2">
          {modifie && <span className="text-xs font-semibold text-accent">Modifications non enregistrées</span>}
          <button type="button" onClick={surAbandonner} disabled={!modifie || enregistrement} className="min-h-10 rounded-lg px-3 text-attenue hover:bg-surface-2 hover:text-texte disabled:opacity-40">
            Annuler
          </button>
          <button type="button" onClick={surEnregistrer} disabled={!modifie || enregistrement} className="min-h-10 rounded-lg bg-accent px-4 font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-40">
            {enregistrement ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <Champ id="poste-titre" libelle="Titre" large>
          <input id="poste-titre" value={brouillon.titre} onChange={(e) => surChangement({ titre: e.target.value })} className={CLASSE_CHAMP} />
        </Champ>
        <Champ id="poste-genre" libelle="Nature">
          <select id="poste-genre" value={brouillon.genre} onChange={(e) => surChangement({ genre: e.target.value as GenrePoste })} className={CLASSE_CHAMP}>
            <option value="CHAPITRE">Chapitre</option>
            <option value="ARTICLE">Article (CCTP seul)</option>
            <option value="OUVRAGE">Ouvrage (CCTP + DPGF)</option>
          </select>
        </Champ>
      </div>

      {brouillon.genre === "OUVRAGE" && (
        <div className="flex flex-col gap-3 rounded-lg border border-bordure bg-fond/50 p-3">
          <div className="flex flex-wrap items-end gap-3">
            <Champ id="poste-unite" libelle="Unité">
              <input id="poste-unite" value={brouillon.unite} onChange={(e) => surChangement({ unite: e.target.value })} placeholder="u, m², ml, ft…" className={CLASSE_CHAMP} />
            </Champ>
            <Champ id="poste-quantite" libelle="Quantité">
              <input id="poste-quantite" inputMode="decimal" value={brouillon.quantite} onChange={(e) => surChangement({ quantite: e.target.value })} className={CLASSE_CHAMP} />
            </Champ>
            <Champ id="poste-prix" libelle="PU estimé HT (€)">
              <input id="poste-prix" inputMode="decimal" value={brouillon.prix_unitaire} onChange={(e) => surChangement({ prix_unitaire: e.target.value })} className={CLASSE_CHAMP} />
            </Champ>
            <Champ id="poste-option" libelle="Solution">
              <select id="poste-option" value={brouillon.option_id} onChange={(e) => surChangement({ option_id: e.target.value })} className={CLASSE_CHAMP}>
                <option value="">Solution de base</option>
                {options.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.nom_court} – {o.libelle}
                  </option>
                ))}
              </select>
            </Champ>
            <div className="flex min-h-11 flex-[1_1_150px] flex-col justify-end">
              <span className="text-xs text-attenue">Montant estimé</span>
              <span className="font-titre text-lg font-semibold tabular-nums">{formaterEuros(montant)}</span>
            </div>
          </div>
          <SuggestionPrix
            key={identifiant}
            titre={brouillon.titre}
            surChoix={(pu, unite) => surChangement({ prix_unitaire: String(pu).replace(".", ","), ...(brouillon.unite ? {} : { unite }) })}
          />
        </div>
      )}

      {brouillon.genre !== "CHAPITRE" && (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold text-attenue" id="libelle-description">
            Description (CCTP)
          </span>
          <EditeurRiche
            key={`${identifiant}-${versionEditeur}`}
            valeur={brouillon.description}
            surChangement={(html) => surChangement({ description: html })}
            police={police}
            taille={taille}
            libelle="Description de l'élément"
          />
        </div>
      )}
    </section>
  );
}

function SuggestionPrix({ titre, surChoix }: { titre: string; surChoix: (pu: number, unite: string) => void }) {
  const [ouvert, setOuvert] = useState(false);
  const [recherche, setRecherche] = useState(titre.split(/\s+/).slice(0, 3).join(" "));
  const [resultat, setResultat] = useState<PagePrix | null>(null);
  const [chargement, setChargement] = useState(false);

  async function chercher() {
    setChargement(true);
    try {
      setResultat(await api<PagePrix>(`/prix?chiffrees=true&recherche=${encodeURIComponent(recherche)}&page=1`));
    } finally {
      setChargement(false);
    }
  }

  if (!ouvert) {
    return (
      <button
        type="button"
        onClick={() => {
          setOuvert(true);
          void chercher();
        }}
        className="flex min-h-10 items-center gap-2 self-start rounded-lg border border-bordure-forte px-3 text-sm hover:bg-surface-2"
      >
        <Calculator aria-hidden="true" className="size-4 text-accent" />
        Proposer un prix depuis mes anciennes DPGF
      </button>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-bordure p-3">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void chercher();
        }}
      >
        <Champ id="recherche-prix-poste" libelle="Rechercher dans les prix de référence" large>
          <input id="recherche-prix-poste" value={recherche} onChange={(e) => setRecherche(e.target.value)} className={CLASSE_CHAMP} />
        </Champ>
        <button type="submit" className="min-h-11 rounded-lg border border-bordure-forte px-3 hover:bg-surface-2">
          Chercher
        </button>
      </form>
      {chargement && <p className="text-attenue">Recherche…</p>}
      {resultat && !chargement && (
        resultat.statistiques.length === 0 ? (
          <p className="text-attenue">Aucun prix trouvé. Essayez avec moins de mots.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {resultat.statistiques.slice(0, 4).map((s) => (
              <li key={s.unite} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-surface-2 px-3 py-2">
                <span>
                  <strong className="tabular-nums">{formaterEuros(s.mediane)}</strong>
                  <span className="text-attenue"> / {s.unite} · médiane de {s.nombre} prix ({formaterEuros(s.minimum)} à {formaterEuros(s.maximum)})</span>
                </span>
                <button type="button" onClick={() => surChoix(s.mediane, s.unite === "—" ? "" : s.unite)} className="min-h-9 rounded-lg bg-accent/15 px-3 text-sm font-semibold text-accent hover:bg-accent/25">
                  Utiliser la médiane
                </button>
              </li>
            ))}
          </ul>
        )
      )}
    </div>
  );
}
