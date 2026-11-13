import { Eye, EyeOff, Pencil, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";

import { api } from "../api/client";
import type { LotCatalogue } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import EnTetePage from "../components/EnTetePage";
import EditionLot from "../components/lot/EditionLot";
import { useRequete } from "../lib/useRequete";

/** Liste des lots proposée à la création de chaque projet : numéros et intitulés, réservée à l'administrateur. */
export default function LotsProposes() {
  const { utilisateur } = useAuth();
  const administrateur = Boolean(utilisateur?.est_administrateur);
  const lots = useRequete<LotCatalogue[]>("/referentiel/lots/tous");
  const [enEdition, setEnEdition] = useState<number | "nouveau" | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  // Focus rendu une fois la liste rechargée (un lot renuméroté change de place dans la page).
  const [focusApres, setFocusApres] = useState<{ cible: string; avant: LotCatalogue[] | null } | null>(null);
  useEffect(() => {
    if (!focusApres || lots.donnees === focusApres.avant) return;
    document.getElementById(focusApres.cible)?.focus();
    setFocusApres(null);
  }, [focusApres, lots.donnees]);

  function annuler(id: number | "nouveau") {
    setEnEdition(null);
    requestAnimationFrame(() => document.getElementById(id === "nouveau" ? "ajouter-lot-propose" : `modifier-lot-propose-${id}`)?.focus());
  }

  async function enregistrer(id: number | "nouveau", code: string, intitule: string) {
    let cible = id;
    if (id === "nouveau") {
      cible = (await api<LotCatalogue>("/referentiel/lots", { method: "POST", body: JSON.stringify({ code, intitule }) })).id;
    } else {
      await api(`/referentiel/lots/${id}`, { method: "PATCH", body: JSON.stringify({ code, intitule }) });
    }
    setEnEdition(null);
    setFocusApres({ cible: `modifier-lot-propose-${cible}`, avant: lots.donnees });
    lots.recharger();
  }

  async function basculerProposition(lot: LotCatalogue) {
    setErreur(null);
    try {
      await api(`/referentiel/lots/${lot.id}`, { method: "PATCH", body: JSON.stringify({ propose: !lot.propose }) });
      setFocusApres({ cible: `proposer-lot-${lot.id}`, avant: lots.donnees });
      lots.recharger();
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Modification impossible.");
    }
  }

  return (
    <>
      <nav aria-label="Fil d'Ariane" className="text-sm text-attenue">
        <Link to="/projets" className="text-attenue hover:text-texte">
          Projets
        </Link>{" "}
        / <span className="text-texte">Lots proposés</span>
      </nav>
      <EnTetePage
        surtitre="Paramétrage"
        titre="Lots proposés"
        sousTitre="La liste cochée à la création de chaque projet. Chaque projet garde ensuite ses propres numéros et intitulés, modifiables dans le projet."
        actions={
          administrateur &&
          enEdition !== "nouveau" && (
            <button
              id="ajouter-lot-propose"
              type="button"
              onClick={() => setEnEdition("nouveau")}
              className="flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4.5 font-bold text-sur-accent hover:bg-accent-clair"
            >
              <Plus aria-hidden="true" className="size-4" />
              Ajouter un lot
            </button>
          )
        }
      />

      <div className="flex flex-col gap-1 rounded-xl border border-bordure bg-surface px-4 py-3 text-sm text-attenue">
        <p>
          Modifier un numéro ou un intitulé ici ne change pas les projets déjà créés. Les documents de la bibliothèque, les articles et les
          entreprises rattachés à ce lot affichent le nouvel intitulé. Pour un autre corps d’état, ajoutez plutôt un nouveau lot.
        </p>
        <p>« Ne plus proposer » retire seulement le lot de la liste cochée à la création des projets : il reste disponible ailleurs.</p>
        <p>Les lots sont classés par numéro : TCE, 00, 01, 2, 3a, 3bis, 10…</p>
        {!administrateur && <p className="text-texte">Seul l’administrateur modifie cette liste.</p>}
      </div>

      {(lots.erreur || erreur) && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-danger">
          {lots.erreur || erreur}
        </p>
      )}

      {enEdition === "nouveau" && (
        <div className="rounded-xl border border-bordure-forte bg-surface px-4 py-3">
          <EditionLot
            code=""
            intitule=""
            libelleBouton="Ajouter le lot"
            indication="Il sera proposé à la création des prochains projets."
            surEnregistrer={(code, intitule) => enregistrer("nouveau", code, intitule)}
            surAnnuler={() => annuler("nouveau")}
          />
        </div>
      )}

      {!lots.donnees && !lots.erreur && <p className="text-attenue">Chargement…</p>}
      <ul className="flex flex-col gap-2">
        {(lots.donnees ?? []).map((lot) =>
          enEdition === lot.id ? (
            <li key={lot.id} className="rounded-xl border border-bordure-forte bg-surface px-4 py-3">
              <EditionLot
                code={lot.code}
                intitule={lot.intitule}
                numeroVerrouille={lot.code_reserve}
                indication={
                  lot.code_reserve
                    ? "Le numéro TCE est réservé aux documents « tous corps d’état » : seul l’intitulé se modifie."
                    : `Les projets déjà créés gardent leurs numéros et intitulés${lot.projets > 0 ? `, mais restent rattachés à ce lot (suggestions d’entreprises et de documents)` : ""}.`
                }
                surEnregistrer={(code, intitule) => enregistrer(lot.id, code, intitule)}
                surAnnuler={() => annuler(lot.id)}
              />
            </li>
          ) : (
            <li
              key={lot.id}
              className={`flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-bordure bg-surface px-4 py-3 ${lot.actif && lot.propose ? "" : "opacity-70"}`}
            >
              <span className="min-w-10 font-titre text-lg font-semibold text-accent">{lot.code}</span>
              <div className="flex min-w-0 flex-[1_1_220px] flex-col">
                <span className="font-semibold">{lot.intitule}</span>
                <span className="text-xs text-attenue">
                  {!lot.actif ? "Désactivé dans l’administration (masqué partout)" : lot.propose ? "Proposé à la création des projets" : "Plus proposé à la création des projets"}
                  {lot.projets > 0 && ` · repris dans ${lot.projets} projet${lot.projets > 1 ? "s" : ""}`}
                  {lot.utilisations > 0 &&
                    ` · rattaché à ${lot.utilisations} document${lot.utilisations > 1 ? "s" : ""}, article${lot.utilisations > 1 ? "s" : ""} ou entreprise${lot.utilisations > 1 ? "s" : ""}`}
                </span>
              </div>
              {administrateur && (
                <>
                  <button
                    id={`proposer-lot-${lot.id}`}
                    type="button"
                    onClick={() => void basculerProposition(lot)}
                    aria-label={`${lot.propose ? "Ne plus proposer" : "Proposer de nouveau"} le lot ${lot.code} à la création des projets`}
                    className="flex min-h-11 items-center gap-2 rounded-lg border border-bordure-forte px-3 text-sm hover:bg-surface-2"
                  >
                    {lot.propose ? <EyeOff aria-hidden="true" className="size-4" /> : <Eye aria-hidden="true" className="size-4" />}
                    {lot.propose ? "Ne plus proposer" : "Proposer de nouveau"}
                  </button>
                  <button
                    id={`modifier-lot-propose-${lot.id}`}
                    type="button"
                    onClick={() => setEnEdition(lot.id)}
                    aria-label={`Modifier le numéro et l’intitulé du lot ${lot.code}`}
                    title="Modifier le numéro et l’intitulé"
                    className="grid size-11 place-items-center rounded-lg text-attenue hover:bg-surface-2 hover:text-texte"
                  >
                    <Pencil aria-hidden="true" className="size-4.5" />
                  </button>
                </>
              )}
            </li>
          ),
        )}
      </ul>
    </>
  );
}
