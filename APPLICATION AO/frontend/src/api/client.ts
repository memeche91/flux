/** Accès à l'API Django : session + jeton CSRF, messages d'erreur en français. */

export const EVENEMENT_SESSION_EXPIREE = "application-ao:session-expiree";

export class ErreurApi extends Error {
  readonly statut: number;

  constructor(statut: number, message: string) {
    super(message);
    this.statut = statut;
  }
}

function lireCookie(nom: string): string | null {
  const prefixe = `${nom}=`;
  for (const morceau of document.cookie.split(";")) {
    const valeur = morceau.trim();
    if (valeur.startsWith(prefixe)) return decodeURIComponent(valeur.slice(prefixe.length));
  }
  return null;
}

export async function assurerJetonCsrf(): Promise<string> {
  let jeton = lireCookie("csrftoken");
  if (!jeton) {
    await fetch("/api/auth/csrf", { credentials: "same-origin" });
    jeton = lireCookie("csrftoken");
  }
  return jeton ?? "";
}

export function messageDepuisCorps(corps: unknown, statut: number): string {
  if (corps && typeof corps === "object" && "detail" in corps) {
    const detail = (corps as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((element) => (element && typeof element === "object" && "msg" in element ? String(element.msg) : ""))
        .filter(Boolean)
        .join(" ; ");
    }
  }
  if (statut === 413) return "Fichier trop volumineux pour le serveur.";
  if (statut >= 500) return "Le serveur a rencontré une erreur. Réessayez dans un instant.";
  return `Erreur ${statut}`;
}

export function signalerSiSessionExpiree(statut: number, chemin: string) {
  if (statut === 401 && !chemin.startsWith("/auth/")) {
    window.dispatchEvent(new Event(EVENEMENT_SESSION_EXPIREE));
  }
}

export async function api<T>(chemin: string, options: RequestInit = {}): Promise<T> {
  const methode = (options.method ?? "GET").toUpperCase();
  const entetes = new Headers(options.headers);
  if (methode !== "GET" && methode !== "HEAD") {
    entetes.set("X-CSRFToken", await assurerJetonCsrf());
  }
  if (options.body && !(options.body instanceof FormData) && !entetes.has("Content-Type")) {
    entetes.set("Content-Type", "application/json");
  }

  let reponse: Response;
  try {
    reponse = await fetch(`/api${chemin}`, { ...options, headers: entetes, credentials: "same-origin" });
  } catch {
    throw new ErreurApi(0, "Connexion au serveur impossible. Vérifiez que l'application est démarrée.");
  }

  if (!reponse.ok) {
    signalerSiSessionExpiree(reponse.status, chemin);
    const corps = await reponse.json().catch(() => null);
    throw new ErreurApi(reponse.status, messageDepuisCorps(corps, reponse.status));
  }
  if (reponse.status === 204) return undefined as T;
  return (await reponse.json()) as T;
}

/** Envoi d'un fichier avec suivi de la progression (fetch ne le permet pas). */
export async function televerser<T>(
  chemin: string,
  donnees: FormData,
  surProgression: (fraction: number) => void,
): Promise<T> {
  const jeton = await assurerJetonCsrf();
  return new Promise<T>((resoudre, rejeter) => {
    const requete = new XMLHttpRequest();
    requete.open("POST", `/api${chemin}`);
    requete.withCredentials = true;
    requete.setRequestHeader("X-CSRFToken", jeton);
    requete.upload.onprogress = (evenement) => {
      if (evenement.lengthComputable) surProgression(evenement.loaded / evenement.total);
    };
    requete.onload = () => {
      let corps: unknown = null;
      try {
        corps = JSON.parse(requete.responseText);
      } catch {
        corps = null;
      }
      if (requete.status >= 200 && requete.status < 300) {
        resoudre(corps as T);
      } else {
        signalerSiSessionExpiree(requete.status, chemin);
        rejeter(new ErreurApi(requete.status, messageDepuisCorps(corps, requete.status)));
      }
    };
    requete.onerror = () => rejeter(new ErreurApi(0, "Connexion au serveur interrompue."));
    requete.send(donnees);
  });
}
