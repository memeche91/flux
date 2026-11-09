import { Archive, Download, FolderPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { api } from "../api/client";
import type { Lot, Projet, ProjetResume } from "../api/types";
import EnTetePage from "../components/EnTetePage";
import { CLASSE_CHAMP, Champ } from "../components/Filtres";
import type { ArchiveProjet } from "../ged/types";
import { formaterDate, formaterTaille, pluriel } from "../lib/format";
import { useRequete } from "../lib/useRequete";

export default function Projets() {
  const projets = useRequete<ProjetResume[]>("/projets");
  const [formulaireOuvert, setFormulaireOuvert] = useState(false);

  return (
    <>
      <EnTetePage
        surtitre="Étape 1 · Pièces écrites"
        titre="Projets"
        sousTitre="Chaque projet réunit ses lots : la même structure produit le CCTP et la DPGF, avec leurs PSE et variantes."
        actions={
          !formulaireOuvert && (
            <button
              type="button"
              onClick={() => setFormulaireOuvert(true)}
              className="flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4.5 font-bold text-sur-accent hover:bg-accent-clair"
            >
              <FolderPlus aria-hidden="true" className="size-4" />
              Nouveau projet
            </button>
          )
        }
      />

      {formulaireOuvert && <NouveauProjet surAnnuler={() => setFormulaireOuvert(false)} />}

      {projets.erreur && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-danger">
          {projets.erreur}
        </p>
      )}

      {projets.donnees && projets.donnees.length === 0 && !formulaireOuvert && (
        <p className="rounded-xl border border-bordure bg-surface px-5 py-6 text-attenue">
          Aucun projet pour l'instant. Créez votre premier projet pour rédiger ses CCTP et DPGF.
        </p>
      )}

      <ul className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,320px),1fr))]">
        {(projets.donnees ?? []).map((projet) => (
          <li key={projet.id}>
            <Link
              to={`/projets/${projet.id}`}
              className="flex h-full flex-col gap-2 rounded-xl border border-bordure bg-surface p-4.5 text-texte no-underline transition-colors hover:border-bordure-forte hover:bg-surface-2"
            >
              <span className="text-xs font-semibold uppercase tracking-[0.06em] text-accent">
                {[projet.numero, projet.type_marche === "PUBLIC" ? "Marché public" : "Marché privé", projet.phase].filter(Boolean).join(" · ")}
              </span>
              <span className="font-titre text-lg font-semibold">{projet.nom}</span>
              {projet.maitre_ouvrage && <span className="text-attenue">{projet.maitre_ouvrage}</span>}
              <span className="mt-auto text-xs text-attenue">
                {pluriel(projet.nb_lots, "lot")} · modifié le {formaterDate(projet.modifie_le)}
              </span>
            </Link>
          </li>
        ))}
      </ul>

      <ArchivesProjets />
    </>
  );
}

/** Archives de fin de chantier, y compris celles des projets dont les fichiers ont été purgés. */
function ArchivesProjets() {
  const archives = useRequete<ArchiveProjet[]>("/archives");
  const liste = (archives.donnees ?? []).filter((a) => a.statut === "VERIFIEE");
  if (!liste.length) return null;
  return (
    <section aria-labelledby="titre-archives" className="flex flex-col gap-3">
      <h2 id="titre-archives" className="flex items-center gap-2 font-titre text-lg font-semibold">
        <Archive aria-hidden="true" className="size-5 text-attenue" />
        Archives des chantiers
      </h2>
      <ul className="flex flex-col gap-2">
        {liste.map((a) => (
          <li key={a.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-bordure bg-surface px-4 py-3">
            <span className="flex min-w-0 flex-[1_1_260px] flex-col">
              {a.projet_id ? (
                <Link to={`/projets/${a.projet_id}/ged?onglet=cloture`} className="font-semibold">
                  {a.nom_projet}
                </Link>
              ) : (
                <span className="font-semibold">{a.nom_projet}</span>
              )}
              <span className="text-xs text-attenue">
                {formaterDate(a.cree_le)} · {formaterTaille(a.taille)}
                {a.fichiers_purges_le ? " · fichiers du projet purgés : cette archive en est la seule copie" : ""}
                {a.conserver_jusqu_au ? ` · à conserver jusqu'au ${formaterDate(a.conserver_jusqu_au)}` : ""}
              </span>
            </span>
            {a.fichier_present ? (
              <a
                href={`/api/archives/${a.id}/telecharger`}
                className="flex min-h-10 items-center gap-2 rounded-lg border border-bordure-forte px-3 text-sm font-semibold text-texte no-underline hover:bg-surface-2"
              >
                <Download aria-hidden="true" className="size-4" />
                Télécharger
              </a>
            ) : (
              <span className="text-sm text-danger">Fichier absent du dossier d'archives</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function NouveauProjet({ surAnnuler }: { surAnnuler: () => void }) {
  const naviguer = useNavigate();
  const lots = useRequete<Lot[]>("/referentiel/lots");
  const [nom, setNom] = useState("");
  const [maitreOuvrage, setMaitreOuvrage] = useState("");
  const [typeMarche, setTypeMarche] = useState<"PUBLIC" | "PRIVE">("PUBLIC");
  const [procedure, setProcedure] = useState("Procédure adaptée (MAPA)");
  const [choisis, setChoisis] = useState<number[]>([]);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  async function creer(evenement: FormEvent) {
    evenement.preventDefault();
    setErreur(null);
    setEnvoi(true);
    try {
      const projet = await api<Projet>("/projets", {
        method: "POST",
        body: JSON.stringify({ nom: nom.trim(), maitre_ouvrage: maitreOuvrage.trim(), type_marche: typeMarche, procedure, lots: choisis }),
      });
      naviguer(`/projets/${projet.id}`);
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Création impossible.");
      setEnvoi(false);
    }
  }

  const basculer = (id: number) => setChoisis((liste) => (liste.includes(id) ? liste.filter((x) => x !== id) : [...liste, id]));

  return (
    <form onSubmit={creer} className="flex flex-col gap-4 rounded-xl border border-bordure-forte bg-surface p-5">
      <h2 className="font-titre text-lg font-semibold">Nouveau projet</h2>
      <div className="flex flex-wrap gap-3">
        <Champ id="nouveau-nom" libelle="Nom de l'opération (obligatoire)" large>
          <input
            id="nouveau-nom"
            required
            value={nom}
            onChange={(e) => setNom(e.target.value)}
            placeholder="Ex. Réhabilitation du groupe scolaire"
            className={CLASSE_CHAMP}
          />
        </Champ>
        <Champ id="nouveau-moa" libelle="Maître d'ouvrage" large>
          <input id="nouveau-moa" value={maitreOuvrage} onChange={(e) => setMaitreOuvrage(e.target.value)} className={CLASSE_CHAMP} />
        </Champ>
        <Champ id="nouveau-marche" libelle="Marché">
          <select id="nouveau-marche" value={typeMarche} onChange={(e) => setTypeMarche(e.target.value as "PUBLIC" | "PRIVE")} className={CLASSE_CHAMP}>
            <option value="PUBLIC">Public</option>
            <option value="PRIVE">Privé</option>
          </select>
        </Champ>
        <Champ id="nouveau-procedure" libelle="Procédure">
          <input id="nouveau-procedure" value={procedure} onChange={(e) => setProcedure(e.target.value)} className={CLASSE_CHAMP} />
        </Champ>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-xs font-semibold text-attenue">Lots du projet ({choisis.length} choisis) — modifiables ensuite</legend>
        <div className="grid gap-1 [grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr))]">
          {(lots.donnees ?? []).map((lot) => (
            <label key={lot.id} className="flex min-h-11 cursor-pointer items-center gap-2.5 rounded-lg px-2.5 hover:bg-surface-2">
              <input type="checkbox" checked={choisis.includes(lot.id)} onChange={() => basculer(lot.id)} className="size-4.5 accent-accent" />
              <span className="w-8 font-titre text-xs font-semibold text-attenue">{lot.code}</span>
              <span>{lot.intitule}</span>
            </label>
          ))}
        </div>
      </fieldset>

      {erreur && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {erreur}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-2.5">
        <button type="button" onClick={surAnnuler} className="min-h-11 rounded-lg border border-bordure-forte px-4 hover:bg-surface-2">
          Annuler
        </button>
        <button
          type="submit"
          disabled={envoi || !nom.trim()}
          className="min-h-11 rounded-lg bg-accent px-4.5 font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-50"
        >
          {envoi ? "Création…" : "Créer le projet"}
        </button>
      </div>
    </form>
  );
}
