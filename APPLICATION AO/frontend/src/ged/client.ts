/** Accès à l'API de la GED, identique pour le cabinet et pour le portail des intervenants :
 * seules l'adresse de base et la protection CSRF diffèrent. */
import { api, ErreurApi, messageDepuisCorps, televerser } from "../api/client";
import type { DocumentGed, PageJournal } from "./types";

export interface Transport {
  requete<T>(chemin: string, options?: RequestInit): Promise<T>;
  televerser<T>(chemin: string, donnees: FormData, surProgression: (fraction: number) => void): Promise<T>;
}

export interface ClientGed {
  /** Préfixe des téléchargements (liens directs du navigateur). */
  base: string;
  cabinet: boolean;
  lister(): Promise<DocumentGed[]>;
  deposer(donnees: FormData, surProgression: (fraction: number) => void): Promise<DocumentGed>;
  ajouterIndice(documentId: number, donnees: FormData, surProgression: (fraction: number) => void): Promise<DocumentGed>;
  donnerAvis(versionId: number, donnees: FormData): Promise<DocumentGed>;
  accuserLecture(versionId: number): Promise<DocumentGed>;
  viser?(versionId: number, donnees: FormData): Promise<DocumentGed>;
  modifierDocument?(documentId: number, donnees: Record<string, unknown>): Promise<DocumentGed>;
  journal(page: number): Promise<PageJournal>;
  urlVersion(versionId: number, quoi: "fichier" | "annote" | "fiche"): string;
  urlSource(sourceId: number): string;
  urlAvis(avisId: number): string;
  urlRegistre(): string;
}

function construire(transport: Transport, base: string, cabinet: boolean): ClientGed {
  const formulaire = (donnees: FormData) => ({ method: "POST", body: donnees });
  return {
    base: `/api${base}`,
    cabinet,
    lister: () => transport.requete<DocumentGed[]>(`${base}/documents`),
    deposer: (donnees, progression) => transport.televerser<DocumentGed>(`${base}/documents`, donnees, progression),
    ajouterIndice: (documentId, donnees, progression) => transport.televerser<DocumentGed>(`${base}/documents/${documentId}/versions`, donnees, progression),
    donnerAvis: (versionId, donnees) => transport.requete<DocumentGed>(`${base}/versions/${versionId}/avis`, formulaire(donnees)),
    accuserLecture: (versionId) => transport.requete<DocumentGed>(`${base}/versions/${versionId}/lecture`, { method: "POST" }),
    ...(cabinet
      ? {
          viser: (versionId: number, donnees: FormData) => transport.requete<DocumentGed>(`${base}/versions/${versionId}/visa`, formulaire(donnees)),
          modifierDocument: (documentId: number, donnees: Record<string, unknown>) =>
            transport.requete<DocumentGed>(`${base}/documents/${documentId}`, { method: "PATCH", body: JSON.stringify(donnees) }),
        }
      : {}),
    journal: (page) => transport.requete<PageJournal>(`${base}/journal?page=${page}`),
    urlVersion: (versionId, quoi) => `/api${base}/versions/${versionId}/${quoi}`,
    urlSource: (sourceId) => `/api${base}/sources/${sourceId}`,
    urlAvis: (avisId) => `/api${base}/avis/${avisId}/fichier`,
    urlRegistre: () => `/api${base}/registre.xlsx`,
  };
}

/** Cabinet : session de l'application, routes /ged/espaces/{id}. */
export function clientCabinet(espaceId: number): ClientGed {
  return construire({ requete: api, televerser }, `/ged/espaces/${espaceId}`, true);
}

// --- Portail : jeton CSRF demandé au serveur (le cookie porte un autre nom sur l'adresse publique) ---

export const EVENEMENT_PORTAIL_EXPIRE = "ged:session-expiree";
let jetonPortail: string | null = null;

export async function jetonCsrfPortail(renouveler = false): Promise<string> {
  if (!jetonPortail || renouveler) {
    const reponse = await fetch("/api/ged/portail/csrf", { credentials: "same-origin" });
    jetonPortail = reponse.ok ? ((await reponse.json()) as { csrftoken: string }).csrftoken : "";
  }
  return jetonPortail ?? "";
}

function signalerExpiration(statut: number) {
  if (statut === 401) window.dispatchEvent(new Event(EVENEMENT_PORTAIL_EXPIRE));
}

export async function apiPortail<T>(chemin: string, options: RequestInit = {}): Promise<T> {
  const methode = (options.method ?? "GET").toUpperCase();
  const entetes = new Headers(options.headers);
  if (methode !== "GET" && methode !== "HEAD") entetes.set("X-CSRFToken", await jetonCsrfPortail());
  if (options.body && !(options.body instanceof FormData) && !entetes.has("Content-Type")) entetes.set("Content-Type", "application/json");
  let reponse: Response;
  try {
    reponse = await fetch(`/api${chemin}`, { ...options, headers: entetes, credentials: "same-origin" });
  } catch {
    throw new ErreurApi(0, "Connexion impossible : vérifiez votre accès à Internet.");
  }
  if (!reponse.ok) {
    if (chemin !== "/ged/acces") signalerExpiration(reponse.status);
    const corps = await reponse.json().catch(() => null);
    throw new ErreurApi(reponse.status, messageDepuisCorps(corps, reponse.status));
  }
  if (reponse.status === 204) return undefined as T;
  return (await reponse.json()) as T;
}

export async function televerserPortail<T>(chemin: string, donnees: FormData, surProgression: (fraction: number) => void): Promise<T> {
  const jeton = await jetonCsrfPortail();
  return new Promise<T>((resoudre, rejeter) => {
    const requete = new XMLHttpRequest();
    requete.open("POST", `/api${chemin}`);
    requete.withCredentials = true;
    requete.setRequestHeader("X-CSRFToken", jeton);
    requete.upload.onprogress = (e) => {
      if (e.lengthComputable) surProgression(e.loaded / e.total);
    };
    requete.onload = () => {
      let corps: unknown = null;
      try {
        corps = JSON.parse(requete.responseText);
      } catch {
        corps = null;
      }
      if (requete.status >= 200 && requete.status < 300) resoudre(corps as T);
      else {
        signalerExpiration(requete.status);
        rejeter(new ErreurApi(requete.status, messageDepuisCorps(corps, requete.status)));
      }
    };
    requete.onerror = () => rejeter(new ErreurApi(0, "Connexion interrompue : réessayez (le dépôt n'a pas abouti)."));
    requete.send(donnees);
  });
}

/** Portail des intervenants : session ouverte avec le code d'accès, routes /ged/portail. */
export function clientPortail(): ClientGed {
  return construire({ requete: apiPortail, televerser: televerserPortail }, "/ged/portail", false);
}
