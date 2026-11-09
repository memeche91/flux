/** Clôture du projet : archive complète vérifiée (pièces écrites, DCE, offres, GED, registre,
 * journal), téléchargement ou copie sur le serveur, puis purge différée des fichiers. */
import { Archive, CheckCircle2, Download, HardDrive, Loader2, Trash2, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import { formaterTaille, pluriel } from "../lib/format";
import { CLASSE_BOUTON, CLASSE_BOUTON_PRINCIPAL, formaterDateHeure, formaterJour, messageErreur } from "./outils";
import type { ArchiveProjet, EtatArchives } from "./types";

export default function Cloture({ projetId, surPurge }: { projetId: number; surPurge?: () => void }) {
  const [etat, setEtat] = useState<EtatArchives | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [occupe, setOccupe] = useState(false);

  const charger = useCallback(() => {
    api<EtatArchives>(`/projets/${projetId}/archives`)
      .then((resultat) => {
        setEtat(resultat);
        setErreur(null);
      })
      .catch((p: unknown) => setErreur(messageErreur(p, "Archives indisponibles.")));
  }, [projetId]);

  useEffect(charger, [charger]);

  // Préparation en tâche de fond : suivi jusqu'à la fin.
  const enCours = Boolean(etat?.archives.some((a) => a.statut === "EN_COURS"));
  useEffect(() => {
    if (!enCours) return;
    const minuterie = window.setInterval(charger, 3000);
    return () => window.clearInterval(minuterie);
  }, [enCours, charger]);

  async function executer(chemin: string, options: RequestInit, defaut: string) {
    setOccupe(true);
    setErreur(null);
    try {
      await api(chemin, options);
      charger();
      return true;
    } catch (p) {
      setErreur(messageErreur(p, defaut));
      return false;
    } finally {
      setOccupe(false);
    }
  }

  if (!etat) {
    return erreur ? (
      <p role="alert" className="text-danger">
        {erreur}
      </p>
    ) : (
      <p className="text-attenue">Chargement…</p>
    );
  }

  const purge = etat.archives.find((a) => a.fichiers_purges_le);
  return (
    <section aria-labelledby="titre-cloture" className="flex flex-col gap-4 rounded-xl border border-bordure bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex max-w-3xl flex-col gap-1">
          <h2 id="titre-cloture" className="font-titre text-lg font-semibold">
            Clôture et archivage du projet
          </h2>
          <p className="text-sm text-attenue">
            L'archive .zip rassemble tout le projet, classé et lisible sans l'application : pièces écrites, DCE, offres et rapport d'analyse, GED (indices en
            vigueur et antérieurs, visas, sources), registre Excel et journal. Elle est vérifiée puis enregistrée dans le dossier d'archives du PC ;
            téléchargez-la ou copiez-la sur le serveur du cabinet, puis libérez la place.
          </p>
        </div>
        {!purge && (
          <button
            type="button"
            onClick={() => void executer(`/projets/${projetId}/archives`, { method: "POST" }, "Archivage impossible.")}
            disabled={occupe || enCours}
            className={CLASSE_BOUTON_PRINCIPAL}
          >
            {enCours ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : <Archive aria-hidden="true" className="size-4" />}
            {enCours ? "Archive en préparation…" : "Préparer l'archive complète"}
          </button>
        )}
      </div>

      <dl className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <div>
          <dt className="text-xs text-attenue">Fichiers du projet dans l'application</dt>
          <dd className="font-semibold">{purge ? "purgés" : formaterTaille(etat.bilan.octets)}</dd>
        </div>
        <div>
          <dt className="text-xs text-attenue">GED</dt>
          <dd className="font-semibold">
            {pluriel(etat.bilan.documents_ged, "document")}, {pluriel(etat.bilan.indices_ged, "indice")}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-attenue">Offres conservées (prix de référence)</dt>
          <dd className="font-semibold">
            {pluriel(etat.bilan.offres, "offre")}, {pluriel(etat.bilan.prix_recus, "prix", "prix")}
          </dd>
        </div>
        {etat.espace_libre !== null && (
          <div>
            <dt className="text-xs text-attenue">Place libre pour les archives</dt>
            <dd className="font-semibold">{formaterTaille(etat.espace_libre)}</dd>
          </div>
        )}
      </dl>

      {erreur && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {erreur}
        </p>
      )}

      {etat.archives.length > 0 && (
        <ul className="flex flex-col gap-3">
          {etat.archives.map((a) => (
            <CarteArchive
              key={a.id}
              archive={a}
              delai={etat.delai_purge_jours}
              administrateur={etat.est_administrateur}
              occupe={occupe}
              executer={executer}
              recharger={charger}
              surPurge={surPurge}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function CarteArchive({
  archive: a,
  delai,
  administrateur,
  occupe,
  executer,
  recharger,
  surPurge,
}: {
  archive: ArchiveProjet;
  recharger: () => void;
  delai: number;
  administrateur: boolean;
  occupe: boolean;
  executer: (chemin: string, options: RequestInit, defaut: string) => Promise<boolean>;
  surPurge?: () => void;
}) {
  const prete = a.statut === "VERIFIEE" && a.fichier_present;
  const sauvegardee = Boolean(a.telechargee_le || a.copie_confirmee_le);
  return (
    <li className="flex flex-col gap-3 rounded-lg border border-bordure-forte bg-fond px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-semibold">Archive du {formaterDateHeure(a.cree_le)}</span>
        <span
          className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${
            a.statut === "VERIFIEE"
              ? "border-succes/40 bg-succes/10 text-succes"
              : a.statut === "ERREUR"
                ? "border-danger/40 bg-danger/10 text-danger"
                : "border-info/40 bg-info/10 text-info"
          }`}
        >
          {a.statut_libelle}
        </span>
        {a.statut === "VERIFIEE" && (
          <span className="text-sm text-attenue">
            {pluriel(a.nb_fichiers, "fichier")} · {formaterTaille(a.taille)}
          </span>
        )}
      </div>
      {a.message && <p className={`text-sm ${a.statut === "ERREUR" ? "text-danger" : "text-attenue"}`}>{a.message}</p>}
      {a.statut === "VERIFIEE" && (
        <p className="text-sm text-attenue">
          {a.fichier_present ? (
            <>
              Enregistrée dans <span className="font-mono text-texte">{`${a.dossier}\\${a.nom_fichier}`}</span>
            </>
          ) : (
            <span className="text-danger">Fichier absent du dossier d'archives ({a.nom_fichier}).</span>
          )}
          {a.conserver_jusqu_au ? ` · à conserver jusqu'au ${formaterJour(a.conserver_jusqu_au)} (réception + 10 ans)` : ""}
          <br />
          Empreinte SHA-256 : <span className="break-all font-mono text-xs">{a.empreinte}</span>
        </p>
      )}

      {prete && (
        <div className="flex flex-wrap gap-2">
          <a href={`/api/archives/${a.id}/telecharger`} className={CLASSE_BOUTON} onClick={() => window.setTimeout(recharger, 2000)}>
            <Download aria-hidden="true" className="size-4" />
            Télécharger (.zip)
          </a>
          {!a.copie_confirmee_le && (
            <button
              type="button"
              disabled={occupe}
              onClick={() => void executer(`/archives/${a.id}/copie-confirmee`, { method: "POST" }, "Confirmation impossible.")}
              className={CLASSE_BOUTON}
            >
              <HardDrive aria-hidden="true" className="size-4" />
              Je l'ai copiée sur le serveur du cabinet
            </button>
          )}
        </div>
      )}
      {(a.telechargee_le || a.copie_confirmee_le) && (
        <p className="flex items-center gap-1.5 text-sm text-succes">
          <CheckCircle2 aria-hidden="true" className="size-4" />
          {a.copie_confirmee_le ? `Copie confirmée le ${formaterDateHeure(a.copie_confirmee_le)}` : `Téléchargée le ${formaterDateHeure(a.telechargee_le!)}`}
        </p>
      )}

      {a.fichiers_purges_le ? (
        <p className="text-sm">
          Fichiers purgés le {formaterDateHeure(a.fichiers_purges_le)} ({formaterTaille(a.octets_liberes)} libérés). Les données (lots, prix, offres, registre)
          restent consultables ; cette archive est la seule copie des fichiers.
        </p>
      ) : a.purge_prevue_le ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-attention/50 bg-attention/10 px-3 py-2">
          <p className="text-sm">
            Purge des fichiers programmée le <strong>{formaterJour(a.purge_prevue_le)}</strong> : jusque-là, tout reste disponible et la purge peut être
            annulée. Un document déposé ou visé après l'archive empêche la purge : préparez alors une nouvelle archive.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={occupe}
              onClick={() => void executer(`/archives/${a.id}/purge`, { method: "DELETE" }, "Annulation impossible.")}
              className={CLASSE_BOUTON}
            >
              <Undo2 aria-hidden="true" className="size-4" />
              Annuler la purge
            </button>
            {administrateur && (
              <button
                type="button"
                disabled={occupe}
                onClick={() => {
                  if (!window.confirm("Purger maintenant les fichiers de ce projet ? L'archive deviendra la seule copie des fichiers.")) return;
                  void executer(`/archives/${a.id}/purge`, { method: "POST", body: JSON.stringify({ maintenant: true }) }, "Purge impossible.").then(
                    (ok) => ok && surPurge?.(),
                  );
                }}
                className={`${CLASSE_BOUTON} text-danger`}
              >
                Purger maintenant
              </button>
            )}
          </div>
        </div>
      ) : (
        prete &&
        a.projet_id !== null && (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-attenue">
              {sauvegardee
                ? `Libérez la place : les fichiers du projet seront supprimés de l'application dans ${delai} jours (annulable). Les données restent.`
                : "Pour libérer la place, téléchargez d'abord l'archive ou confirmez sa copie sur le serveur."}
            </p>
            <button
              type="button"
              disabled={occupe || !sauvegardee}
              onClick={() =>
                void executer(`/archives/${a.id}/purge`, { method: "POST", body: JSON.stringify({ maintenant: false }) }, "Programmation impossible.")
              }
              className={`${CLASSE_BOUTON} text-danger`}
            >
              <Trash2 aria-hidden="true" className="size-4" />
              Programmer la purge des fichiers
            </button>
          </div>
        )
      )}

      {!a.fichiers_purges_le && a.statut !== "EN_COURS" && (
        <button
          type="button"
          disabled={occupe}
          onClick={() => {
            if (!window.confirm("Supprimer cette archive de l'application et du dossier d'archives ?")) return;
            void executer(`/archives/${a.id}`, { method: "DELETE" }, "Suppression impossible.");
          }}
          className="self-end text-xs text-attenue underline-offset-2 hover:text-danger hover:underline"
        >
          Supprimer cette archive
        </button>
      )}
    </li>
  );
}
