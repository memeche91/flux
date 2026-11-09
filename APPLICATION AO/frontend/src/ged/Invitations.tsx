/** Codes d'accès à transmettre : affichés une seule fois (seule leur empreinte est conservée).
 * Copie du message, messagerie du poste, envoi par l'application, fiches imprimables. */
import { Check, Copy, Mail, Printer, Send, X } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";
import { CLASSE_BOUTON, CLASSE_BOUTON_PRINCIPAL, messageErreur } from "./outils";
import type { Invitation } from "./types";

/** Copie dans le presse-papiers, y compris sur une adresse http du réseau local (sans API Clipboard). */
export async function copier(texte: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(texte);
      return true;
    }
  } catch {
    /* repli ci-dessous */
  }
  const zone = document.createElement("textarea");
  zone.value = texte;
  zone.setAttribute("readonly", "");
  zone.style.position = "fixed";
  zone.style.opacity = "0";
  document.body.appendChild(zone);
  zone.select();
  const ok = document.execCommand("copy");
  zone.remove();
  return ok;
}

const echapper = (texte: string) => texte.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] ?? c);

/** Fiches d'accès à remettre en main propre (une par page). */
function imprimer(invitations: Invitation[], projet: string) {
  const fenetre = window.open("", "_blank");
  if (!fenetre) return;
  const adresse = (lien: string) => lien.split("#")[0];
  const fiches = invitations
    .map(
      (i) => `<section>
  <p class="surtitre">${echapper(projet)}</p>
  <h1>Accès à l'espace documentaire du chantier</h1>
  <p><strong>${echapper(i.nom)}</strong> – ${echapper(i.intervenant)}</p>
  <p>Adresse : <strong>${echapper(adresse(i.lien))}</strong></p>
  <p class="code">${echapper(i.code)}</p>
  <p>Ce code est personnel : ne le communiquez pas. Vos collègues peuvent recevoir leur propre accès sur simple demande à la maîtrise d'œuvre.</p>
  <p>Utilisez toujours l'indice marqué « À utiliser ». Chaque nouveauté vous est signalée par courriel.</p>
</section>`,
    )
    .join("");
  fenetre.document.write(`<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Fiches d'accès – ${echapper(projet)}</title>
<style>
body{font-family:Arial,sans-serif;color:#111;margin:0}
section{padding:24mm 20mm;page-break-after:always;font-size:12pt;line-height:1.5}
.surtitre{text-transform:uppercase;letter-spacing:.08em;color:#555;font-size:10pt}
h1{font-size:18pt;margin:4px 0 18px}
.code{font-family:Consolas,monospace;font-size:28pt;letter-spacing:.12em;border:2px solid #111;display:inline-block;padding:8px 16px;margin:18px 0}
</style></head><body>${fiches}</body></html>`);
  fenetre.document.close();
  fenetre.focus();
  fenetre.print();
}

interface Proprietes {
  invitations: Invitation[];
  projet: string;
  emailActif: boolean;
  surRemplacer: (ancienne: Invitation, nouvelle: Invitation) => void;
  surFermer: () => void;
}

export default function Invitations({ invitations, projet, emailActif, surRemplacer, surFermer }: Proprietes) {
  const [copie, setCopie] = useState<number | null>(null);
  const [envoi, setEnvoi] = useState<number | null>(null);
  const [messages, setMessages] = useState<Record<number, { ok: boolean; texte: string }>>({});

  async function copierMessage(invitation: Invitation) {
    if (await copier(invitation.message)) {
      setCopie(invitation.acces_id);
      window.setTimeout(() => setCopie(null), 2000);
    }
  }

  async function envoyer(invitation: Invitation) {
    setEnvoi(invitation.acces_id);
    try {
      const nouvelle = await api<Invitation>(`/ged/acces/${invitation.acces_id}/invitation`, { method: "POST", body: JSON.stringify({ envoyer: true }) });
      surRemplacer(invitation, nouvelle);
      setMessages((m) => ({
        ...m,
        [invitation.acces_id]: nouvelle.envoye
          ? { ok: true, texte: `Envoyé à ${nouvelle.destinataire} (nouveau code ci-dessus).` }
          : { ok: false, texte: nouvelle.erreur_envoi ?? "Envoi impossible." },
      }));
    } catch (p) {
      setMessages((m) => ({ ...m, [invitation.acces_id]: { ok: false, texte: messageErreur(p, "Envoi impossible.") } }));
    } finally {
      setEnvoi(null);
    }
  }

  return (
    <section aria-labelledby="titre-invitations" className="flex flex-col gap-4 rounded-xl border-2 border-accent bg-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2 id="titre-invitations" className="font-titre text-lg font-semibold">
            Codes d'accès à transmettre
          </h2>
          <p className="text-sm text-attenue">
            Chaque personne a son propre code. Il n'est affiché qu'ici : envoyez-le ou imprimez la fiche maintenant. Plus tard, « Nouveau code » en crée un
            autre (l'ancien cesse de fonctionner).
          </p>
        </div>
        <button
          type="button"
          onClick={surFermer}
          className="grid size-10 shrink-0 place-items-center rounded-lg text-attenue hover:bg-surface-2"
          aria-label="Fermer les codes d'accès"
        >
          <X aria-hidden="true" className="size-5" />
        </button>
      </div>
      <ul className="flex flex-col gap-3">
        {invitations.map((i) => (
          <li key={i.acces_id} className="flex flex-col gap-2 rounded-lg border border-bordure-forte bg-fond px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="flex flex-col">
                <span className="font-semibold">{i.nom}</span>
                <span className="text-xs text-attenue">
                  {i.intervenant}
                  {i.destinataire ? ` · ${i.destinataire}` : " · pas d'adresse e-mail"}
                </span>
              </span>
              <span className="select-all rounded-lg border border-accent/50 bg-accent/10 px-3 py-1.5 font-mono text-xl font-bold tracking-widest text-accent">
                {i.code}
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => void copierMessage(i)} className={CLASSE_BOUTON}>
                {copie === i.acces_id ? <Check aria-hidden="true" className="size-4 text-succes" /> : <Copy aria-hidden="true" className="size-4" />}
                {copie === i.acces_id ? "Message copié" : "Copier le message"}
              </button>
              <a
                href={`mailto:${encodeURIComponent(i.destinataire)}?subject=${encodeURIComponent(i.objet)}&body=${encodeURIComponent(i.message)}`}
                className={CLASSE_BOUTON}
              >
                <Mail aria-hidden="true" className="size-4" />
                Ouvrir dans ma messagerie
              </a>
              {emailActif && i.destinataire && !i.envoye && (
                <button type="button" onClick={() => void envoyer(i)} disabled={envoi !== null} className={CLASSE_BOUTON}>
                  <Send aria-hidden="true" className="size-4" />
                  {envoi === i.acces_id ? "Envoi…" : "Envoyer par l'application"}
                </button>
              )}
            </div>
            {!messages[i.acces_id] && (i.envoye || i.erreur_envoi) && (
              <p role="status" className={`text-sm ${i.envoye ? "text-succes" : "text-danger"}`}>
                {i.envoye ? `Envoyé par courriel à ${i.destinataire}.` : i.erreur_envoi}
              </p>
            )}
            {messages[i.acces_id] && (
              <p role="status" className={`text-sm ${messages[i.acces_id].ok ? "text-succes" : "text-danger"}`}>
                {messages[i.acces_id].texte}
              </p>
            )}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" onClick={() => imprimer(invitations, projet)} className={CLASSE_BOUTON}>
          <Printer aria-hidden="true" className="size-4" />
          Imprimer les fiches d'accès
        </button>
        <button type="button" onClick={surFermer} className={CLASSE_BOUTON_PRINCIPAL}>
          C'est transmis
        </button>
      </div>
    </section>
  );
}
