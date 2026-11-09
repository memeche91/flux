import { ArrowRight, FilePlus2, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";

import { api } from "../../api/client";
import { NOMS_PIECES, type DocumentReference, type LotResume, type Modele, type PieceDetail, type PieceResume, type TypePiece } from "../../api/types";
import { formaterDate, pluriel } from "../../lib/format";
import { CLASSE_CHAMP } from "../Filtres";

interface Proprietes {
  projetId: number;
  typeMarche: "PUBLIC" | "PRIVE";
  lots: LotResume[];
}

type Cible = { type: TypePiece; lot: LotResume | null } | { type: "AE_TOUS" };

export default function PiecesAdministratives({ projetId, typeMarche, lots }: Proprietes) {
  const naviguer = useNavigate();
  const [pieces, setPieces] = useState<PieceResume[] | null>(null);
  const [cible, setCible] = useState<Cible | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    api<PieceResume[]>(`/projets/${projetId}/pieces`)
      .then(setPieces)
      .catch((probleme: unknown) => setErreur(probleme instanceof Error ? probleme.message : "Pièces administratives indisponibles."));
  }, [projetId, version, lots.length]);

  if (!pieces) {
    return erreur ? (
      <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
        {erreur}
      </p>
    ) : null;
  }
  const trouver = (type: TypePiece, lotId: number | null) => pieces.find((p) => p.type_piece === type && (p.lot?.id ?? null) === lotId);
  const actesManquants = lots.filter((l) => !trouver("AE", l.id)).length;

  async function supprimer(piece: PieceResume) {
    const nom = piece.lot ? `${NOMS_PIECES[piece.type_piece]} du lot ${piece.lot.code}` : NOMS_PIECES[piece.type_piece];
    if (!window.confirm(`Supprimer ${nom} et tout son contenu ?`)) return;
    setErreur(null);
    try {
      await api(`/pieces/${piece.id}`, { method: "DELETE" });
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Suppression impossible.");
    }
    setVersion((v) => v + 1);
  }

  const formulaire = (pour: Cible) => (
    <CreationPiece
      projetId={projetId}
      typeMarche={typeMarche}
      cible={pour}
      surAnnuler={() => setCible(null)}
      surErreur={setErreur}
      surCree={(pieceId) => {
        setCible(null);
        setVersion((v) => v + 1);
        if (pieceId) naviguer(`/projets/${projetId}/pieces/${pieceId}`);
      }}
    />
  );

  const ligne = (type: TypePiece, lot: LotResume | null) => {
    const piece = trouver(type, lot?.id ?? null);
    const libelle = lot ? `Lot ${lot.code} – ${lot.intitule}` : NOMS_PIECES[type];
    const nomCreation = lot ? `Créer l'acte d'engagement du lot ${lot.code}` : `Créer le ${NOMS_PIECES[type]}`;
    const ouvert = cible !== null && cible.type === type && (cible.lot?.id ?? null) === (lot?.id ?? null);
    return (
      <li key={`${type}-${lot?.id ?? "projet"}`} className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-bordure bg-surface px-4 py-3">
        <span className="w-12 font-titre text-sm font-semibold text-accent">{lot ? "AE" : type}</span>
        <div className="flex min-w-0 flex-[1_1_220px] flex-col">
          <span className="font-semibold">{libelle}</span>
          <span className="text-xs text-attenue">
            {piece ? `${pluriel(piece.nb_clauses, "clause")} · ${piece.origine} · modifié le ${formaterDate(piece.modifie_le)}` : "Pas encore rédigé"}
          </span>
        </div>
        {piece ? (
          <>
            <Link
              to={`/projets/${projetId}/pieces/${piece.id}`}
              className="flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4 font-bold text-sur-accent no-underline hover:bg-accent-clair"
            >
              Rédiger
              <ArrowRight aria-hidden="true" className="size-4" />
            </Link>
            <button
              type="button"
              onClick={() => void supprimer(piece)}
              aria-label={`Supprimer ${libelle}`}
              className="grid size-11 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger"
            >
              <Trash2 aria-hidden="true" className="size-4.5" />
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setCible(ouvert ? null : { type, lot })}
            aria-expanded={ouvert}
            aria-label={nomCreation}
            className="flex min-h-11 items-center gap-2 rounded-lg border border-accent/60 px-4 font-semibold text-accent hover:bg-accent/10"
          >
            <FilePlus2 aria-hidden="true" className="size-4" />
            Créer
          </button>
        )}
        {ouvert && cible && <div className="basis-full">{formulaire(cible)}</div>}
      </li>
    );
  };

  return (
    <section aria-labelledby="titre-pieces" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h2 id="titre-pieces" className="font-titre text-lg font-semibold">
          Pièces administratives
        </h2>
        <p className="text-attenue">CCAP et règlement de consultation communs à tous les lots ; un acte d'engagement par lot.</p>
      </div>
      {erreur && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {erreur}
        </p>
      )}
      <ul className="flex flex-col gap-2">
        {ligne("CCAP", null)}
        {ligne("RC", null)}
      </ul>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">Actes d'engagement</h3>
        {actesManquants > 1 && (
          <button
            type="button"
            onClick={() => setCible(cible?.type === "AE_TOUS" ? null : { type: "AE_TOUS" })}
            aria-expanded={cible?.type === "AE_TOUS"}
            className="flex min-h-10 items-center gap-2 rounded-lg border border-bordure-forte px-3 text-sm font-semibold hover:bg-surface-2"
          >
            <FilePlus2 aria-hidden="true" className="size-4" />
            Créer les {actesManquants} actes d'engagement manquants
          </button>
        )}
      </div>
      {cible?.type === "AE_TOUS" && formulaire(cible)}
      {lots.length === 0 ? (
        <p className="text-attenue">Ajoutez des lots au projet pour rédiger leurs actes d'engagement.</p>
      ) : (
        <ul className="flex flex-col gap-2">{lots.map((lot) => ligne("AE", lot))}</ul>
      )}

    </section>
  );
}

function CreationPiece({
  projetId,
  typeMarche,
  cible,
  surAnnuler,
  surCree,
  surErreur,
}: {
  projetId: number;
  typeMarche: "PUBLIC" | "PRIVE";
  cible: Cible;
  surAnnuler: () => void;
  surCree: (pieceId: number | null) => void;
  surErreur: (message: string | null) => void;
}) {
  const type: TypePiece = cible.type === "AE_TOUS" ? "AE" : cible.type;
  const [modeles, setModeles] = useState<Modele[] | null>(null);
  const [documents, setDocuments] = useState<DocumentReference[]>([]);
  const [source, setSource] = useState("");
  const [envoi, setEnvoi] = useState(false);

  useEffect(() => {
    api<Modele[]>(`/modeles?type_piece=${type}`)
      .then((liste) => {
        // Le modèle de base correspondant au type de marché du projet est proposé en premier.
        const tries = [...liste].sort((a, b) => Number(b.marche === typeMarche) - Number(a.marche === typeMarche) || a.origine.localeCompare(b.origine));
        setModeles(tries);
        setSource(tries[0] ? `modele:${tries[0].id}` : "vide");
      })
      .catch(() => {
        // Sans la liste des modèles, on peut toujours partir d'une page blanche ou d'un ancien document.
        setModeles([]);
        setSource("vide");
      });
    if (cible.type !== "AE_TOUS") {
      api<DocumentReference[]>(`/bibliotheque/documents?type_document=${type}`)
        .then((liste) => setDocuments(liste.filter((d) => d.statut_analyse === "ANALYSE")))
        .catch(() => setDocuments([]));
    }
  }, [type, typeMarche, cible.type]);

  async function creer() {
    surErreur(null);
    setEnvoi(true);
    const modeleId = source.startsWith("modele:") ? source.slice(7) : null;
    const documentId = source.startsWith("document:") ? Number(source.slice(9)) : null;
    try {
      if (cible.type === "AE_TOUS") {
        await api(`/projets/${projetId}/pieces/actes-engagement`, { method: "POST", body: JSON.stringify({ modele_id: modeleId }) });
        surCree(null);
      } else {
        const piece = await api<PieceDetail>(`/projets/${projetId}/pieces`, {
          method: "POST",
          body: JSON.stringify({ type_piece: cible.type, lot_id: cible.lot?.id ?? null, modele_id: modeleId, document_id: documentId }),
        });
        surCree(piece.id);
      }
    } catch (probleme) {
      surErreur(probleme instanceof Error ? probleme.message : "Création impossible.");
      setEnvoi(false);
    }
  }

  const titre =
    cible.type === "AE_TOUS"
      ? "Créer les actes d'engagement manquants"
      : cible.lot
        ? `Créer l'acte d'engagement du lot ${cible.lot.code}`
        : `Créer le ${NOMS_PIECES[cible.type]}`;

  return (
    <div className="mt-2 flex flex-col gap-3 rounded-xl border border-accent/40 bg-fond/40 p-4" role="group" aria-label={titre}>
      <h3 className="font-titre text-base font-semibold">{titre}</h3>
      <label htmlFor="source-piece" className="text-xs font-semibold text-attenue">
        Point de départ
      </label>
      <select id="source-piece" value={source} onChange={(e) => setSource(e.target.value)} className={CLASSE_CHAMP} disabled={!modeles}>
        {modeles && modeles.length > 0 && (
          <optgroup label="Modèles">
            {modeles.map((m) => (
              <option key={m.id} value={`modele:${m.id}`}>
                {m.nom} {m.origine === "CABINET" ? "(modèle du cabinet)" : "(modèle de base)"} · {m.nb_clauses} clauses
                {m.marche === typeMarche ? " · recommandé" : ""}
              </option>
            ))}
          </optgroup>
        )}
        {documents.length > 0 && (
          <optgroup label="Reprendre un ancien document">
            {documents.map((d) => (
              <option key={d.id} value={`document:${d.id}`}>
                {d.nom_original} · {pluriel(d.nb_articles, "clause")}
              </option>
            ))}
          </optgroup>
        )}
        <option value="vide">Page blanche</option>
      </select>
      <p className="text-xs text-attenue">
        Les modèles de base sont à relire et à adapter à chaque opération ; leurs références juridiques ont été vérifiées à la date de leur rédaction.
      </p>
      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" onClick={surAnnuler} className="min-h-11 rounded-lg border border-bordure-forte px-4 hover:bg-surface-2">
          Annuler
        </button>
        <button type="button" onClick={() => void creer()} disabled={envoi || !modeles} className="min-h-11 rounded-lg bg-accent px-4.5 font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-50">
          {envoi ? "Création…" : cible.type === "AE_TOUS" ? "Créer les actes d'engagement" : "Créer la pièce"}
        </button>
      </div>
    </div>
  );
}
