/** Échanges avec l'assistant IA : réponse en flux continu, transcription et lecture à voix haute. */
import { ErreurApi, assurerJetonCsrf, messageDepuisCorps, signalerSiSessionExpiree } from "./client";
import type { EvenementAssistant } from "./types";

async function envoyer(chemin: string, corps: BodyInit, signal?: AbortSignal, json = true): Promise<Response> {
  const entetes = new Headers({ "X-CSRFToken": await assurerJetonCsrf() });
  if (json) entetes.set("Content-Type", "application/json");
  let reponse: Response;
  try {
    reponse = await fetch(`/api${chemin}`, { method: "POST", body: corps, headers: entetes, credentials: "same-origin", signal });
  } catch (probleme) {
    if (probleme instanceof DOMException && probleme.name === "AbortError") throw probleme;
    throw new ErreurApi(0, "Connexion au serveur impossible. Vérifiez que l'application est démarrée.");
  }
  if (!reponse.ok) {
    signalerSiSessionExpiree(reponse.status, chemin);
    const detail = await reponse.json().catch(() => null);
    throw new ErreurApi(reponse.status, messageDepuisCorps(detail, reponse.status));
  }
  return reponse;
}

/** Pose une question ; chaque événement du flux (sources, morceau de texte, fin) est transmis à `surEvenement`. */
export async function poserQuestion(
  conversationId: number,
  texte: string,
  surEvenement: (evenement: EvenementAssistant) => void,
  signal: AbortSignal,
): Promise<void> {
  const reponse = await envoyer(`/assistant/conversations/${conversationId}/messages`, JSON.stringify({ texte }), signal);
  if (!reponse.body) throw new ErreurApi(0, "Réponse vide du serveur.");
  const lecteur = reponse.body.getReader();
  const decodeur = new TextDecoder();
  let tampon = "";
  for (;;) {
    const { value, done } = await lecteur.read();
    if (done) break;
    tampon += decodeur.decode(value, { stream: true });
    let fin = tampon.indexOf("\n");
    while (fin >= 0) {
      const ligne = tampon.slice(0, fin).trim();
      tampon = tampon.slice(fin + 1);
      if (ligne) surEvenement(JSON.parse(ligne) as EvenementAssistant);
      fin = tampon.indexOf("\n");
    }
  }
  if (tampon.trim()) surEvenement(JSON.parse(tampon) as EvenementAssistant);
}

export async function transcrire(audio: Blob): Promise<string> {
  const formulaire = new FormData();
  const extension = audio.type.includes("mp4") ? "m4a" : audio.type.includes("ogg") ? "ogg" : "webm";
  formulaire.append("audio", audio, `question.${extension}`);
  const reponse = await envoyer("/assistant/transcrire", formulaire, undefined, false);
  return ((await reponse.json()) as { texte: string }).texte;
}

export async function syntheseVocale(texte: string, signal?: AbortSignal): Promise<Blob> {
  const reponse = await envoyer("/assistant/synthese", JSON.stringify({ texte }), signal);
  return reponse.blob();
}
