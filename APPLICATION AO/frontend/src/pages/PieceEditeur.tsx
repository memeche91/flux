import { ArrowDown, ArrowUp, BookmarkPlus, FileDown, FileText, Hash, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";

import { api } from "../api/client";
import type { ChampPiece, Clause, DocumentReference, GenreClause, PieceDetail, Projet } from "../api/types";
import { CLASSE_CHAMP, Champ } from "../components/Filtres";
import EditeurRiche from "../components/lot/EditeurRiche";
import PanneauBibliotheque from "../components/lot/PanneauBibliotheque";
import { useAvertirSortie } from "../lib/useAvertirSortie";
import { useRequete } from "../lib/useRequete";

interface Brouillon {
  genre: GenreClause;
  titre: string;
  contenu: string;
}

const versBrouillon = (clause: Clause): Brouillon => ({ genre: clause.genre, titre: clause.titre, contenu: clause.contenu });

export default function PieceEditeur() {
  const { projetId, pieceId } = useParams();
  const projet = useRequete<Projet>(`/projets/${projetId}`);
  const champs = useRequete<ChampPiece[]>(`/pieces/${pieceId}/champs`);
  const [piece, setPiece] = useState<PieceDetail | null>(null);
  const [selection, setSelection] = useState<number | null>(null);
  const [brouillon, setBrouillon] = useState<Brouillon | null>(null);
  const [original, setOriginal] = useState<Brouillon | null>(null);
  const [versionEditeur, setVersionEditeur] = useState(0);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const modifie = brouillon !== null && original !== null && JSON.stringify(brouillon) !== JSON.stringify(original);

  const appliquerSelection = useCallback((detail: PieceDetail, id: number | null) => {
    const clause = detail.clauses.find((c) => c.id === id) ?? null;
    setSelection(clause?.id ?? null);
    const suivant = clause ? versBrouillon(clause) : null;
    setBrouillon(suivant);
    setOriginal(suivant);
  }, []);

  useEffect(() => {
    api<PieceDetail>(`/pieces/${pieceId}`)
      .then((detail) => {
        setPiece(detail);
        const premiere = detail.clauses.find((c) => c.genre === "ARTICLE") ?? detail.clauses[0];
        appliquerSelection(detail, premiere?.id ?? null);
      })
      .catch((probleme: unknown) => setErreur(probleme instanceof Error ? probleme.message : "Pièce introuvable."));
  }, [pieceId, appliquerSelection]);

  useAvertirSortie(modifie);

  async function enregistrer(): Promise<PieceDetail | null> {
    if (!brouillon || selection == null || !piece) return piece;
    setOccupe(true);
    setErreur(null);
    try {
      const resultat = await api<PieceDetail>(`/clauses/${selection}`, {
        method: "PATCH",
        body: JSON.stringify({ genre: brouillon.genre, titre: brouillon.titre.trim() || "Sans titre", contenu: brouillon.contenu }),
      });
      setPiece(resultat);
      appliquerSelection(resultat, selection);
      setMessage("Enregistré.");
      return resultat;
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Enregistrement impossible.");
      return null;
    } finally {
      setOccupe(false);
    }
  }

  const enregistrerRef = useRef(enregistrer);
  enregistrerRef.current = enregistrer;
  useEffect(() => {
    const raccourci = (evenement: KeyboardEvent) => {
      if ((evenement.ctrlKey || evenement.metaKey) && evenement.key.toLowerCase() === "s") {
        evenement.preventDefault();
        void enregistrerRef.current();
      }
    };
    window.addEventListener("keydown", raccourci);
    return () => window.removeEventListener("keydown", raccourci);
  }, []);

  async function executer(action: () => Promise<PieceDetail>, choisir: (avant: PieceDetail, apres: PieceDetail) => number | null) {
    if (!piece) return;
    let avant = piece;
    if (modifie) {
      const sauvegarde = await enregistrer();
      if (!sauvegarde) return;
      avant = sauvegarde;
    }
    setOccupe(true);
    setErreur(null);
    setMessage(null);
    try {
      const apres = await action();
      setPiece(apres);
      appliquerSelection(apres, choisir(avant, apres));
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Action impossible.");
    } finally {
      setOccupe(false);
    }
  }

  const nouvelleClause = (avant: PieceDetail, apres: PieceDetail) => {
    const anciennes = new Set(avant.clauses.map((c) => c.id));
    return apres.clauses.find((c) => !anciennes.has(c.id))?.id ?? selection;
  };

  function selectionner(id: number) {
    if (id === selection) return;
    if (modifie && !window.confirm("Abandonner les modifications non enregistrées de cette clause ?")) return;
    if (piece) appliquerSelection(piece, id);
    setMessage(null);
  }

  if (erreur && !piece) {
    return (
      <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-danger">
        {erreur}
      </p>
    );
  }
  if (!piece) return <p className="text-attenue">Chargement de la pièce…</p>;
  const clauseSelectionnee = piece.clauses.find((c) => c.id === selection);
  const champsInserables = (champs.donnees ?? []).map((c) => ({ cle: c.cle, libelle: c.libelle, bloc: c.bloc }));
  const sousTitre = piece.lot ? `Lot ${piece.lot.code} – ${piece.lot.intitule}` : "Commun à tous les lots";

  return (
    <>
      <nav aria-label="Fil d'Ariane" className="text-sm text-attenue">
        <Link to="/projets" className="text-attenue hover:text-texte">
          Projets
        </Link>{" "}
        /{" "}
        <Link to={`/projets/${projetId}`} className="text-attenue hover:text-texte">
          {piece.projet.nom}
        </Link>{" "}
        /{" "}
        <span className="text-texte">
          {piece.type_piece}
          {piece.lot ? ` lot ${piece.lot.code}` : ""}
        </span>
      </nav>
      <div className="flex flex-col gap-1">
        <span className="text-xs font-semibold uppercase tracking-[0.08em] text-accent">
          {piece.projet.type_marche === "PUBLIC" ? "Marché public" : "Marché privé"} · {sousTitre}
        </span>
        <h1 className="font-titre text-3xl font-bold tracking-tight">{piece.titre}</h1>
        <p className="text-xs text-attenue">Créée à partir de : {piece.origine}</p>
      </div>

      {(erreur || message) && (
        <p
          role={erreur ? "alert" : "status"}
          className={`rounded-lg px-4 py-2.5 ${erreur ? "border border-danger/40 bg-danger/10 text-danger" : "bg-succes/10 text-succes"}`}
        >
          {erreur ?? message}
        </p>
      )}

      <div className="flex flex-wrap items-start gap-4">
        <div className="flex min-w-0 flex-[1_1_290px] flex-col gap-4">
          <PlanPiece
            piece={piece}
            selection={selection}
            occupe={occupe}
            surSelection={selectionner}
            surAjout={(genre) =>
              void executer(
                () =>
                  api<PieceDetail>(`/pieces/${piece.id}/clauses`, {
                    method: "POST",
                    body: JSON.stringify({ genre, titre: genre === "CHAPITRE" ? "Nouvel article" : "Nouveau sous-article", apres_id: selection }),
                  }),
                nouvelleClause,
              )
            }
            surDeplacement={(sens) =>
              void executer(
                () => api<PieceDetail>(`/clauses/${selection}/deplacer`, { method: "POST", body: JSON.stringify({ sens }) }),
                () => selection,
              )
            }
            surSuppression={() => {
              if (!clauseSelectionnee) return;
              if (!window.confirm(`Supprimer « ${clauseSelectionnee.numero} ${clauseSelectionnee.titre} » ?`)) return;
              const indice = piece.clauses.findIndex((c) => c.id === selection);
              const voisin = piece.clauses[indice + 1]?.id ?? piece.clauses[indice - 1]?.id ?? null;
              setBrouillon(original);
              void executer(
                () => api<PieceDetail>(`/clauses/${selection}`, { method: "DELETE" }),
                () => voisin,
              );
            }}
          />
          <PanneauChamps champs={champs.donnees} projetId={Number(projetId)} />
        </div>

        <div className="flex min-w-0 flex-[999_1_520px] flex-col gap-4">
          {brouillon && clauseSelectionnee ? (
            <section aria-labelledby="titre-clause" className="flex flex-col gap-4 rounded-xl border border-bordure bg-surface p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 id="titre-clause" className="font-titre text-lg font-semibold">
                  <span className="mr-2 text-accent">{clauseSelectionnee.numero}</span>
                  {brouillon.genre === "CHAPITRE" ? "Article" : "Sous-article"}
                </h2>
                <div className="flex items-center gap-2">
                  {modifie && <span className="text-xs font-semibold text-attention">Modifications non enregistrées</span>}
                  <button
                    type="button"
                    onClick={() => {
                      setBrouillon(original);
                      setVersionEditeur((v) => v + 1);
                    }}
                    disabled={!modifie || occupe}
                    className="min-h-10 rounded-lg px-3 text-attenue hover:bg-surface-2 hover:text-texte disabled:opacity-40"
                  >
                    Annuler
                  </button>
                  <button
                    type="button"
                    onClick={() => void enregistrer()}
                    disabled={!modifie || occupe}
                    className="min-h-10 rounded-lg bg-accent px-4 font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-40"
                  >
                    {occupe ? "Enregistrement…" : "Enregistrer"}
                  </button>
                </div>
              </div>
              <div className="flex flex-wrap gap-3">
                <Champ id="clause-titre" libelle="Titre" large>
                  <input
                    id="clause-titre"
                    value={brouillon.titre}
                    onChange={(e) => setBrouillon({ ...brouillon, titre: e.target.value })}
                    className={CLASSE_CHAMP}
                  />
                </Champ>
                <Champ id="clause-genre" libelle="Niveau">
                  <select
                    id="clause-genre"
                    value={brouillon.genre}
                    onChange={(e) => setBrouillon({ ...brouillon, genre: e.target.value as GenreClause })}
                    className={CLASSE_CHAMP}
                  >
                    <option value="CHAPITRE">Article (Article 1, 2…)</option>
                    <option value="ARTICLE">Sous-article (1.1, 1.2…)</option>
                  </select>
                </Champ>
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="text-xs font-semibold text-attenue">
                  Texte · les champs entre accolades ({"{{nom_operation}}"}…) sont remplacés par les données du projet à l'export
                </span>
                <EditeurRiche
                  key={`${clauseSelectionnee.id}-${versionEditeur}`}
                  valeur={brouillon.contenu}
                  surChangement={(html) => setBrouillon((b) => (b ? { ...b, contenu: html } : b))}
                  police={projet.donnees?.police ?? "Arial"}
                  taille={projet.donnees?.taille_police ?? 10}
                  libelle="Texte de la clause"
                  champs={champsInserables}
                />
              </div>
            </section>
          ) : (
            <p className="rounded-xl border border-bordure bg-surface px-5 py-8 text-attenue">Sélectionnez une clause dans le plan, ou ajoutez-en une.</p>
          )}
        </div>

        <div className="flex min-w-0 flex-[1_1_290px] flex-col gap-4">
          <ExportsPiece pieceId={piece.id} modifie={modifie} />
          <EnregistrerModele pieceId={piece.id} nomParDefaut={`${piece.type_piece} – ${piece.projet.nom}`} modifie={modifie} enregistrer={enregistrer} />
          <PanneauBibliotheque
            lotReferenceId={null}
            typeDocument={piece.type_piece}
            occupe={occupe}
            surInsertion={(articleId) =>
              executer(
                () =>
                  api<PieceDetail>(`/pieces/${piece.id}/inserer-article`, {
                    method: "POST",
                    body: JSON.stringify({ article_id: articleId, apres_id: selection }),
                  }),
                nouvelleClause,
              )
            }
            surReprise={async (document: DocumentReference) => {
              if (!window.confirm(`Ajouter les clauses de « ${document.nom_original} » après l'élément sélectionné ?`)) return;
              await executer(
                () =>
                  api<PieceDetail>(`/pieces/${piece.id}/importer`, { method: "POST", body: JSON.stringify({ document_id: document.id, apres_id: selection }) }),
                nouvelleClause,
              );
            }}
          />
        </div>
      </div>
    </>
  );
}

function PlanPiece({
  piece,
  selection,
  occupe,
  surSelection,
  surAjout,
  surDeplacement,
  surSuppression,
}: {
  piece: PieceDetail;
  selection: number | null;
  occupe: boolean;
  surSelection: (id: number) => void;
  surAjout: (genre: GenreClause) => void;
  surDeplacement: (sens: "haut" | "bas") => void;
  surSuppression: () => void;
}) {
  const selectionnee = piece.clauses.find((c) => c.id === selection);
  return (
    <section aria-labelledby="titre-plan-piece" className="flex flex-col gap-2 rounded-xl border border-bordure bg-surface p-3">
      <h2 id="titre-plan-piece" className="px-1 font-titre text-base font-semibold">
        Plan
      </h2>
      <div className="flex gap-1" role="group" aria-label="Ajouter après la sélection">
        {(
          [
            ["CHAPITRE", "Article"],
            ["ARTICLE", "Sous-article"],
          ] as [GenreClause, string][]
        ).map(([genre, libelle]) => (
          <button
            key={genre}
            type="button"
            disabled={occupe}
            onClick={() => surAjout(genre)}
            className="flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-lg border border-bordure-forte px-2 text-xs font-semibold hover:bg-surface-2 disabled:opacity-50"
          >
            <Plus aria-hidden="true" className="size-3.5" />
            {libelle}
          </button>
        ))}
      </div>
      <ol className="flex max-h-[62vh] flex-col overflow-y-auto" aria-label="Clauses de la pièce">
        {piece.clauses.map((clause) => {
          const chapitre = clause.genre === "CHAPITRE";
          const actif = clause.id === selection;
          const Icone = chapitre ? Hash : FileText;
          return (
            <li key={clause.id}>
              <button
                type="button"
                onClick={() => surSelection(clause.id)}
                aria-current={actif ? "true" : undefined}
                className={`flex min-h-10 w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left transition-colors ${
                  actif ? "bg-accent/15 text-white ring-1 ring-accent/60" : "hover:bg-surface-2"
                } ${chapitre ? "mt-1.5 font-semibold" : "pl-5"}`}
              >
                <Icone aria-hidden="true" className={`mt-0.5 size-3.5 shrink-0 ${chapitre ? "text-accent" : "text-attenue"}`} />
                <span className={`shrink-0 font-titre text-xs leading-5 ${chapitre ? "text-accent" : "text-attenue"}`}>{clause.numero}</span>
                <span className="min-w-0 flex-1 leading-5">{clause.titre}</span>
              </button>
            </li>
          );
        })}
      </ol>
      {selectionnee && (
        <div className="flex items-center justify-between gap-1 border-t border-bordure pt-2" role="group" aria-label="Clause sélectionnée">
          <span className="truncate px-1 text-xs text-attenue">{selectionnee.numero}</span>
          <div className="flex gap-1">
            {(
              [
                ["Monter", ArrowUp, () => surDeplacement("haut")],
                ["Descendre", ArrowDown, () => surDeplacement("bas")],
              ] as const
            ).map(([libelle, Icone, action]) => (
              <button
                key={libelle}
                type="button"
                aria-label={libelle}
                title={libelle}
                onClick={action}
                disabled={occupe}
                className="grid size-10 place-items-center rounded-lg text-attenue hover:bg-surface-2 hover:text-texte disabled:opacity-40"
              >
                <Icone className="size-4" />
              </button>
            ))}
            <button
              type="button"
              aria-label="Supprimer"
              title="Supprimer"
              onClick={surSuppression}
              disabled={occupe}
              className="grid size-10 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger disabled:opacity-40"
            >
              <Trash2 className="size-4" />
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function PanneauChamps({ champs, projetId }: { champs: ChampPiece[] | null; projetId: number }) {
  if (!champs) return null;
  const manquants = champs.filter((c) => !c.renseigne).length;
  return (
    <section aria-labelledby="titre-champs" className="flex flex-col gap-2 rounded-xl border border-bordure bg-surface p-3">
      <h2 id="titre-champs" className="px-1 font-titre text-base font-semibold">
        Champs du projet
      </h2>
      <p className="px-1 text-xs text-attenue">
        {manquants > 0 ? (
          <>
            {manquants} champ{manquants > 1 ? "s" : ""} à compléter : ils apparaîtront surlignés « [à compléter] » à l'export.{" "}
            <Link to={`/projets/${projetId}`} className="text-accent">
              Compléter le projet
            </Link>
          </>
        ) : (
          "Tous les champs sont renseignés."
        )}
      </p>
      <dl className="flex max-h-72 flex-col gap-1 overflow-y-auto">
        {champs.map((c) => (
          <div key={c.cle} className="rounded-lg bg-fond/40 px-2.5 py-1.5">
            <dt className="text-xs text-attenue">
              {c.libelle} <code className="text-[11px] text-attenue/80">{`{{${c.cle}}}`}</code>
            </dt>
            <dd className={`text-sm ${c.renseigne ? "text-texte" : "font-semibold text-attention"}`}>{c.renseigne ? c.apercu || "—" : "À compléter"}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function ExportsPiece({ pieceId, modifie }: { pieceId: number; modifie: boolean }) {
  return (
    <section aria-labelledby="titre-exports-piece" className="flex flex-col gap-2 rounded-xl border border-bordure bg-surface p-3">
      <h2 id="titre-exports-piece" className="flex items-center gap-2 px-1 font-titre text-base font-semibold">
        <FileDown aria-hidden="true" className="size-4 text-accent" />
        Exporter
      </h2>
      {modifie && (
        <p className="px-1 text-xs font-semibold text-attention">Enregistrez d'abord vos modifications : les exports utilisent la version enregistrée.</p>
      )}
      <div className="flex gap-1.5 px-1">
        <a
          href={`/api/pieces/${pieceId}/export/docx`}
          className="flex min-h-10 items-center rounded-lg border border-bordure-forte px-3 text-sm font-semibold text-texte no-underline hover:bg-surface-2"
        >
          Word
        </a>
        <a
          href={`/api/pieces/${pieceId}/export/pdf`}
          target="_blank"
          rel="noopener"
          className="flex min-h-10 items-center rounded-lg border border-bordure-forte px-3 text-sm font-semibold text-texte no-underline hover:bg-surface-2"
        >
          PDF
        </a>
      </div>
    </section>
  );
}

function EnregistrerModele({
  pieceId,
  nomParDefaut,
  modifie,
  enregistrer,
}: {
  pieceId: number;
  nomParDefaut: string;
  modifie: boolean;
  enregistrer: () => Promise<PieceDetail | null>;
}) {
  const [nom, setNom] = useState(nomParDefaut);
  const [envoi, setEnvoi] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; texte: string } | null>(null);

  async function enregistrerModele() {
    setMessage(null);
    setEnvoi(true);
    try {
      // Le modèle reprend la pièce telle qu'enregistrée : la clause en cours d'abord.
      if (modifie && !(await enregistrer())) return;
      await api(`/pieces/${pieceId}/enregistrer-modele`, { method: "POST", body: JSON.stringify({ nom: nom.trim() }) });
      setMessage({ ok: true, texte: "Modèle enregistré." });
    } catch (probleme) {
      setMessage({ ok: false, texte: probleme instanceof Error ? probleme.message : "Enregistrement impossible." });
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <section aria-labelledby="titre-modele" className="flex flex-col gap-2 rounded-xl border border-bordure bg-surface p-3">
      <h2 id="titre-modele" className="flex items-center gap-2 px-1 font-titre text-base font-semibold">
        <BookmarkPlus aria-hidden="true" className="size-4 text-accent" />
        Modèle du cabinet
      </h2>
      <p className="px-1 text-xs text-attenue">Enregistrez cette pièce pour repartir d'elle sur vos prochains projets.</p>
      <form
        className="flex flex-wrap gap-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          void enregistrerModele();
        }}
      >
        <label htmlFor="nom-modele" className="sr-only">
          Nom du modèle
        </label>
        <input id="nom-modele" value={nom} onChange={(e) => setNom(e.target.value)} className={`${CLASSE_CHAMP} min-w-0 basis-full`} />
        <button
          type="submit"
          disabled={envoi || !nom.trim()}
          className="min-h-11 rounded-lg border border-bordure-forte px-3 text-sm font-semibold hover:bg-surface-2 disabled:opacity-50"
        >
          {envoi ? "Enregistrement…" : "Enregistrer comme modèle"}
        </button>
      </form>
      {message && (
        <p role={message.ok ? "status" : "alert"} className={`px-1 text-xs ${message.ok ? "text-succes" : "text-danger"}`}>
          {message.texte}
        </p>
      )}
    </section>
  );
}
