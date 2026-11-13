import { Archive, Download, FolderPlus, Plus, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { api } from "../api/client";
import type { Lot, Projet, ProjetResume } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import EnTetePage from "../components/EnTetePage";
import { CLASSE_CHAMP, Champ } from "../components/Filtres";
import { LONGUEUR_INTITULE_LOT, LONGUEUR_NUMERO_LOT, MESSAGE_NUMERO_INVALIDE, cleNumeroLot, numeroLotValide } from "../components/lot/EditionLot";
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

const CLASSE_SAISIE_LOT = "min-h-11 rounded-lg border bg-fond px-3 text-texte";

/** Lot retenu dans le formulaire de création : de la liste proposée (lotId) ou hors liste (lotId nul). */
interface LotRetenu {
  cle: string;
  lotId: number | null;
  /** Numéro dans la liste proposée : accepté tel quel s'il n'est pas modifié (même un ancien « 3 bis »). */
  codeListe: string | null;
  code: string;
  intitule: string;
}

function NouveauProjet({ surAnnuler }: { surAnnuler: () => void }) {
  const naviguer = useNavigate();
  const { utilisateur } = useAuth();
  const lots = useRequete<Lot[]>("/referentiel/lots?projets=true");
  const { recharger: rechargerLots } = lots;
  // La liste des lots proposés s'ouvre dans un autre onglet : elle est relue au retour sur celui-ci.
  useEffect(() => {
    window.addEventListener("focus", rechargerLots);
    return () => window.removeEventListener("focus", rechargerLots);
  }, [rechargerLots]);
  const [nom, setNom] = useState("");
  const [maitreOuvrage, setMaitreOuvrage] = useState("");
  const [typeMarche, setTypeMarche] = useState<"PUBLIC" | "PRIVE">("PUBLIC");
  const [procedure, setProcedure] = useState("Procédure adaptée (MAPA)");
  const [retenus, setRetenus] = useState<LotRetenu[]>([]);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const compteur = useRef(0);

  // Lots de la liste dans l'ordre de la liste, puis les autres dans l'ordre d'ajout : hors liste, ou retirés entre-temps
  // de la liste proposée (autre onglet) ; ceux-ci restent visibles, retirables et envoyés.
  const listeProposee = lots.donnees ?? [];
  const affiches = [
    ...listeProposee.flatMap((lot) => retenus.filter((r) => r.lotId === lot.id)),
    ...retenus.filter((r) => r.lotId === null || !listeProposee.some((l) => l.id === r.lotId)),
  ];
  const occurrences = new Map<string, number>();
  for (const r of retenus) if (r.code.trim()) occurrences.set(cleNumeroLot(r.code), (occurrences.get(cleNumeroLot(r.code)) ?? 0) + 1);
  const enDouble = (r: LotRetenu) => Boolean(r.code.trim()) && (occurrences.get(cleNumeroLot(r.code)) ?? 0) > 1;
  const invalide = (r: LotRetenu) => Boolean(r.code.trim()) && r.code.trim() !== r.codeListe && !numeroLotValide(r.code);
  const incomplets = retenus.some((r) => !r.code.trim() || !r.intitule.trim());
  const doublons = retenus.some(enDouble);
  const invalides = retenus.some(invalide);

  async function creer(evenement: FormEvent) {
    evenement.preventDefault();
    setErreur(null);
    setEnvoi(true);
    try {
      const projet = await api<Projet>("/projets", {
        method: "POST",
        body: JSON.stringify({
          nom: nom.trim(),
          maitre_ouvrage: maitreOuvrage.trim(),
          type_marche: typeMarche,
          procedure,
          lots_choisis: affiches.map((r) => ({ lot_id: r.lotId, code: r.code.trim(), intitule: r.intitule.trim() })),
        }),
      });
      naviguer(`/projets/${projet.id}`);
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Création impossible.");
      setEnvoi(false);
    }
  }

  const basculer = (lot: Lot) =>
    setRetenus((liste) =>
      liste.some((r) => r.lotId === lot.id)
        ? liste.filter((r) => r.lotId !== lot.id)
        : [...liste, { cle: `liste-${lot.id}`, lotId: lot.id, codeListe: lot.code, code: lot.code, intitule: lot.intitule }],
    );
  const modifier = (cle: string, champ: "code" | "intitule", valeur: string) =>
    setRetenus((liste) => liste.map((r) => (r.cle === cle ? { ...r, [champ]: valeur } : r)));
  function retirer(cle: string) {
    // Le focus passe au lot suivant (ou au bouton d'ajout) au lieu de retomber en haut de la page.
    const rang = affiches.findIndex((r) => r.cle === cle);
    const suivant = affiches[rang + 1] ?? affiches[rang - 1];
    setRetenus((liste) => liste.filter((r) => r.cle !== cle));
    requestAnimationFrame(() => document.getElementById(suivant ? `numero-${suivant.cle}` : "ajouter-lot-hors-liste")?.focus());
  }
  function ajouterHorsListe() {
    compteur.current += 1;
    const cle = `hors-liste-${compteur.current}`;
    setRetenus((liste) => [...liste, { cle, lotId: null, codeListe: null, code: "", intitule: "" }]);
    requestAnimationFrame(() => document.getElementById(`numero-${cle}`)?.focus());
  }

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
        <legend className="mb-1 flex w-full flex-wrap items-baseline justify-between gap-x-4 text-xs font-semibold text-attenue">
          <span>Lots du projet ({retenus.length} choisis) — numéros et intitulés modifiables ci-dessous, et ensuite dans le projet</span>
          {utilisateur?.est_administrateur && (
            <Link to="/lots" target="_blank" rel="noopener" className="font-normal">
              Modifier la liste des lots proposés (nouvel onglet)
            </Link>
          )}
        </legend>
        <div className="grid gap-1 [grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr))]">
          {listeProposee.map((lot) => (
            <label key={lot.id} className="flex min-h-11 cursor-pointer items-center gap-2.5 rounded-lg px-2.5 hover:bg-surface-2">
              <input
                type="checkbox"
                checked={retenus.some((r) => r.lotId === lot.id)}
                onChange={() => basculer(lot)}
                className="size-4.5 accent-accent"
              />
              <span className="w-8 font-titre text-xs font-semibold text-attenue">{lot.code}</span>
              <span>{lot.intitule}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <section aria-label="Numéros et intitulés des lots pour ce projet" className="flex flex-col gap-2">
        {affiches.length > 0 && (
          <h3 className="text-xs font-semibold text-attenue">Numéros et intitulés pour ce projet</h3>
        )}
        {affiches.length > 0 && (
          <ul className="flex flex-col gap-3 sm:gap-1.5">
            {affiches.map((r) => (
              <li key={r.cle} className="flex flex-wrap items-center gap-2">
                <label htmlFor={`numero-${r.cle}`} className="sr-only">
                  Numéro du lot {r.intitule || "hors liste"}
                </label>
                <input
                  id={`numero-${r.cle}`}
                  value={r.code}
                  onChange={(e) => modifier(r.cle, "code", e.target.value)}
                  maxLength={LONGUEUR_NUMERO_LOT}
                  placeholder="N°"
                  autoComplete="off"
                  aria-invalid={enDouble(r) || invalide(r) || !r.code.trim()}
                  aria-describedby={enDouble(r) || invalide(r) ? `probleme-${r.cle}` : undefined}
                  className={`${CLASSE_SAISIE_LOT} w-20 sm:w-24 ${enDouble(r) || invalide(r) ? "border-danger" : "border-bordure-forte"}`}
                />
                <label htmlFor={`intitule-${r.cle}`} className="sr-only">
                  Intitulé du lot {r.code}
                </label>
                <input
                  id={`intitule-${r.cle}`}
                  value={r.intitule}
                  onChange={(e) => modifier(r.cle, "intitule", e.target.value)}
                  maxLength={LONGUEUR_INTITULE_LOT}
                  placeholder="Intitulé du lot"
                  autoComplete="off"
                  aria-invalid={!r.intitule.trim()}
                  className={`${CLASSE_SAISIE_LOT} min-w-0 flex-[1_1_100px] border-bordure-forte`}
                />
                <button
                  type="button"
                  onClick={() => retirer(r.cle)}
                  aria-label={`Retirer le lot ${r.code || r.intitule || "hors liste"}`}
                  className="grid size-11 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger"
                >
                  <X aria-hidden="true" className="size-4.5" />
                </button>
                {(enDouble(r) || invalide(r)) && (
                  <span id={`probleme-${r.cle}`} className="basis-full text-xs text-danger">
                    {invalide(r) ? MESSAGE_NUMERO_INVALIDE : "Numéro déjà utilisé par un autre lot de ce projet."}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        <button
          id="ajouter-lot-hors-liste"
          type="button"
          onClick={ajouterHorsListe}
          className="flex min-h-11 items-center gap-2 self-start rounded-lg border border-dashed border-bordure-forte px-3.5 text-sm hover:bg-surface-2"
        >
          <Plus aria-hidden="true" className="size-4" />
          Ajouter un lot qui n’est pas dans la liste
        </button>
      </section>

      {erreur && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {erreur}
        </p>
      )}
      <div className="flex flex-wrap items-center justify-end gap-2.5">
        {(incomplets || doublons || invalides) && (
          <p className="text-sm text-attenue">
            {doublons
              ? "Deux lots ont le même numéro : changez l’un des deux."
              : invalides
                ? "Un numéro de lot n’est pas valide."
                : "Indiquez le numéro et l’intitulé de chaque lot."}
          </p>
        )}
        <button type="button" onClick={surAnnuler} className="min-h-11 rounded-lg border border-bordure-forte px-4 hover:bg-surface-2">
          Annuler
        </button>
        <button
          type="submit"
          disabled={envoi || !nom.trim() || incomplets || doublons || invalides}
          className="min-h-11 rounded-lg bg-accent px-4.5 font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-50"
        >
          {envoi ? "Création…" : "Créer le projet"}
        </button>
      </div>
    </form>
  );
}
