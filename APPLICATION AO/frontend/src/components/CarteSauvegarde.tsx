/** Carte « Sauvegarde » du tableau de bord : dernière sauvegarde réussie, destination, heure de la
 * sauvegarde de chaque nuit et alertes. L'administrateur peut lancer une sauvegarde immédiate ;
 * l'état est relu toutes les 5 s tant qu'une sauvegarde est en cours. */
import { CircleAlert, CircleCheck, DatabaseBackup, LoaderCircle, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { DerniereSauvegarde, EtatSauvegardes } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formaterTaille } from "../lib/format";

const INTERVALLE_SUIVI_MS = 5000;

const lireEtat = () => api<EtatSauvegardes>("/sauvegardes/etat");

const messageDe = (probleme: unknown, defaut: string) => (probleme instanceof Error && probleme.message ? probleme.message : defaut);

/** Dates et heures lues à l’heure de Paris, comme l’heure de la sauvegarde de chaque nuit et les dates
 * citées dans les alertes du serveur, même si Windows est réglé sur un autre fuseau. */
const PARTIES_PARIS = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris",
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "numeric",
  minute: "numeric",
  hourCycle: "h23",
});
const MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];

function aParis(date: Date) {
  const parties = Object.fromEntries(PARTIES_PARIS.formatToParts(date).map((p) => [p.type, p.value]));
  return {
    annee: Number(parties.year),
    mois: Number(parties.month),
    jour: Number(parties.day),
    heures: Number(parties.hour),
    minutes: Number(parties.minute),
  };
}

/** « 2 h 05 », comme l’heure de la sauvegarde de chaque nuit renvoyée par le serveur. */
function heureDe(date: Date): string {
  const { heures, minutes } = aParis(date);
  return `${heures} h ${String(minutes).padStart(2, "0")}`;
}

/** « aujourd’hui à 2 h 31 », « hier à 2 h 31 », « le 1er novembre 2026 à 2 h 31 ». */
function formaterMoment(iso: string): string {
  const date = new Date(iso);
  const jourDe = (d: ReturnType<typeof aParis>) => Date.UTC(d.annee, d.mois - 1, d.jour);
  const moment = aParis(date);
  const ecart = Math.round((jourDe(aParis(new Date())) - jourDe(moment)) / 86_400_000);
  const heure = heureDe(date);
  if (ecart === 0) return `aujourd’hui à ${heure}`;
  if (ecart === 1) return `hier à ${heure}`;
  const numero = moment.jour === 1 ? "1er" : String(moment.jour);
  return `le ${numero} ${MOIS[moment.mois - 1]} ${moment.annee} à ${heure}`;
}

const majuscule = (texte: string) => texte.charAt(0).toUpperCase() + texte.slice(1);

/** Le serveur réunit ses alertes en un seul texte. L'avertissement « même disque que l'application »
 * (toujours placé en dernier) est un conseil d'installation : il est affiché en couleur attention, le
 * reste (jamais sauvegardé, dernière réussite trop ancienne, échec, copie non vérifiée) en danger. Si
 * sa formulation change, tout le texte reste affiché en danger. La dernière occurrence est retenue,
 * puisque l’avertissement est placé en dernier (après le message d’échec éventuel, qui est libre). */
const DEBUT_MEME_DISQUE = /Les sauvegardes [^.!?]*même disque/g;
function separerAlerte(alerte: string): { grave: string; disque: string } {
  let indice = -1;
  for (const occurrence of alerte.matchAll(DEBUT_MEME_DISQUE)) indice = occurrence.index;
  if (indice < 0) return { grave: alerte.trim(), disque: "" };
  return { grave: alerte.slice(0, indice).trim(), disque: alerte.slice(indice).trim() };
}

function messageFin(derniere: DerniereSauvegarde | null): string {
  if (!derniere || derniere.statut === "EN_COURS") return "";
  if (derniere.statut === "ECHEC") return "La sauvegarde a échoué : le détail est affiché ci-dessous.";
  return derniere.verifiee ? "Sauvegarde terminée et vérifiée." : "Sauvegarde terminée, mais la restauration d’essai n’a pas réussi.";
}

export default function CarteSauvegarde() {
  const { utilisateur } = useAuth();
  const administrateur = Boolean(utilisateur?.est_administrateur);
  const [etat, setEtat] = useState<EtatSauvegardes | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const [erreurLancement, setErreurLancement] = useState<string | null>(null);

  useEffect(() => {
    let actif = true;
    lireEtat()
      .then((resultat) => {
        if (!actif) return;
        setEtat(resultat);
        setErreur(null);
      })
      .catch((probleme: unknown) => {
        if (actif) setErreur(messageDe(probleme, "État des sauvegardes indisponible."));
      });
    return () => {
      actif = false;
    };
  }, []);

  // Suivi toutes les 5 s tant qu'une sauvegarde est en cours (lancée ici, par la nuit ou par la commande).
  const enCours = etat?.en_cours ?? false;
  useEffect(() => {
    if (!enCours) return;
    let actif = true;
    let minuterie: number | undefined;
    const programmer = () => {
      minuterie = window.setTimeout(() => {
        lireEtat()
          .then((resultat) => {
            if (!actif) return;
            setEtat(resultat);
            setErreur(null);
          })
          .catch((probleme: unknown) => {
            if (actif) setErreur(messageDe(probleme, "État des sauvegardes indisponible."));
          })
          .finally(() => {
            if (actif) programmer();
          });
      }, INTERVALLE_SUIVI_MS);
    };
    programmer();
    return () => {
      actif = false;
      window.clearTimeout(minuterie);
    };
  }, [enCours]);

  // Message de fin, annoncé quand une sauvegarde suivie sur cette page se termine.
  const [enCoursPrecedent, setEnCoursPrecedent] = useState(enCours);
  const [fin, setFin] = useState("");
  if (enCours !== enCoursPrecedent) {
    setEnCoursPrecedent(enCours);
    setFin(enCours ? "" : messageFin(etat?.derniere ?? null));
  }

  async function lancer() {
    setEnvoi(true);
    setErreurLancement(null);
    try {
      const resultat = await api<EtatSauvegardes>("/sauvegardes", { method: "POST" });
      setEtat(resultat);
      setErreur(null);
    } catch (probleme) {
      setErreurLancement(messageDe(probleme, "La sauvegarde n’a pas pu être lancée."));
    } finally {
      setEnvoi(false);
    }
  }

  const { grave, disque } = separerAlerte(etat?.alerte ?? "");
  const reussie = etat?.derniere_reussie ?? null;
  const debutEnCours = etat?.en_cours && etat.derniere?.statut === "EN_COURS" ? etat.derniere.debut : null;
  const bordure = grave ? "border-danger/50" : disque ? "border-attention/50" : "border-bordure";

  return (
    <section aria-labelledby="titre-sauvegarde" className={`flex flex-col gap-4 rounded-xl border bg-surface p-5 ${bordure}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="titre-sauvegarde" className="flex items-center gap-2 font-titre text-lg font-semibold">
          <DatabaseBackup aria-hidden="true" className="size-5 text-accent" />
          Sauvegarde
        </h2>
        {administrateur && etat && (
          <button
            type="button"
            onClick={lancer}
            disabled={envoi || etat.en_cours}
            className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-bordure-forte px-4 font-semibold text-texte hover:bg-surface-2 disabled:opacity-60"
          >
            {envoi || etat.en_cours ? (
              <LoaderCircle aria-hidden="true" className="size-4 motion-safe:animate-spin" />
            ) : (
              <DatabaseBackup aria-hidden="true" className="size-4" />
            )}
            {etat.en_cours ? "Sauvegarde en cours…" : envoi ? "Lancement…" : "Sauvegarder maintenant"}
          </button>
        )}
      </div>

      {!etat ? (
        erreur ? (
          <p className="flex items-start gap-2 text-danger">
            <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {erreur}
          </p>
        ) : (
          <p className="text-sm text-attenue">Chargement de l’état des sauvegardes…</p>
        )
      ) : (
        <>
          <dl className="grid gap-x-6 gap-y-4 md:grid-cols-3">
            <div className="flex min-w-0 flex-col gap-1">
              <dt className="text-xs text-attenue">Dernière sauvegarde réussie</dt>
              <dd className="flex flex-col gap-1">
                {reussie ? (
                  <>
                    <span>
                      <span className="font-semibold">{reussie.fin ? majuscule(formaterMoment(reussie.fin)) : "Date inconnue"}</span>
                      {reussie.taille > 0 && <span className="text-attenue"> · {formaterTaille(reussie.taille)}</span>}
                    </span>
                    <span className={`flex items-center gap-1.5 text-sm ${reussie.verifiee ? "text-succes" : "text-attention"}`}>
                      {reussie.verifiee ? (
                        <CircleCheck aria-hidden="true" className="size-4 shrink-0" />
                      ) : (
                        <TriangleAlert aria-hidden="true" className="size-4 shrink-0" />
                      )}
                      {reussie.verifiee ? "Vérifiée par une restauration d’essai" : "Non vérifiée par une restauration d’essai"}
                    </span>
                  </>
                ) : (
                  <span className="font-semibold text-danger">Aucune pour l’instant</span>
                )}
              </dd>
            </div>
            <div className="flex min-w-0 flex-col gap-1">
              <dt className="text-xs text-attenue">Destination</dt>
              <dd className="flex flex-col gap-1">
                <span className="font-mono text-sm break-all">{etat.destination}</span>
                <span className="text-xs text-attenue">
                  {etat.stockage_serveur
                    ? "Partage du serveur de l’agence, où sont déjà enregistrés les fichiers de l’application."
                    : "Les fichiers de l’application y sont recopiés à chaque sauvegarde."}
                </span>
              </dd>
            </div>
            <div className="flex min-w-0 flex-col gap-1">
              <dt className="text-xs text-attenue">Sauvegarde automatique</dt>
              <dd className="flex flex-col gap-1">
                <span className="font-semibold">{etat.heure ? `Chaque nuit à ${etat.heure}` : "Chaque nuit"}</span>
                <span className="text-xs text-attenue">Le PC doit rester allumé, avec l’application démarrée.</span>
              </dd>
            </div>
          </dl>

          {/* Zone annoncée par les lecteurs d’écran : toujours présente, masquée quand elle est vide. */}
          <div role="status" className={debutEnCours || fin ? "" : "sr-only"}>
            {debutEnCours ? (
              <p className="flex items-center gap-2 text-sm text-info">
                <LoaderCircle aria-hidden="true" className="size-4 shrink-0 motion-safe:animate-spin" />
                Sauvegarde en cours depuis {heureDe(new Date(debutEnCours))}. Cette carte se met à jour toute seule.
              </p>
            ) : fin ? (
              <p className="text-sm text-attenue">{fin}</p>
            ) : null}
          </div>

          {grave && (
            <p className="flex items-start gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
              <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              <span>{grave}</span>
            </p>
          )}
          {disque && (
            <p className="flex items-start gap-2 rounded-lg border border-attention/40 bg-attention/10 px-3 py-2 text-attention">
              <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              <span>{disque}</span>
            </p>
          )}
          {erreur && <p className="text-sm text-danger">{erreur}</p>}
        </>
      )}
      {erreurLancement && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {erreurLancement}
        </p>
      )}
    </section>
  );
}
