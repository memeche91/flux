/** Portail des intervenants : connexion par code personnel, documents du chantier selon les
 * droits, dépôts, avis, accusés de lecture, préférences de courriels. */
import { HardHat, LogOut, Mail } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate, useParams } from "react-router";

import { ErreurApi } from "../api/client";
import { CLASSE_CHAMP } from "../components/Filtres";
import Logo from "../components/Logo";
import { apiPortail, clientPortail, EVENEMENT_PORTAIL_EXPIRE, jetonCsrfPortail } from "../ged/client";
import Explorateur from "../ged/Explorateur";
import Journal from "../ged/Journal";
import { CLASSE_BOUTON, CLASSE_BOUTON_PRINCIPAL, messageErreur } from "../ged/outils";
import type { EspacePortail, Frequence } from "../ged/types";

export default function Portail() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/ged" element={<Session />} />
        <Route path="/ged/document/:documentId" element={<Session />} />
        <Route path="*" element={<Navigate to="/ged" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

/** « k7qm2xpa9rtd » → « K7QM-2XPA-9RTD » pendant la saisie. */
function formaterCode(saisie: string): string {
  const propre = saisie
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "")
    .slice(0, 12);
  return propre.match(/.{1,4}/g)?.join("-") ?? "";
}

/** Code du lien d'invitation « …/ged#code=XXXX », s'il y en a un. */
function codeDuLien(): string {
  const trouve = window.location.hash.match(/code=([A-Za-z0-9-]+)/);
  return trouve ? formaterCode(trouve[1]) : "";
}

function Session() {
  // Le lien d'invitation prime sur une session déjà ouverte sur l'appareil (poste de chantier
  // partagé) : la personne valide elle-même son code, ce qui ferme la session précédente.
  const [codeInvitation, setCodeInvitation] = useState(codeDuLien);
  const [espace, setEspace] = useState<EspacePortail | null>(null);
  const [verification, setVerification] = useState(!codeInvitation);
  const [expiree, setExpiree] = useState(false);
  const [sessionExistante, setSessionExistante] = useState<EspacePortail | null>(null);

  useEffect(() => {
    if (codeInvitation) {
      // Code retiré de l'adresse (historique, captures d'écran).
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
      // Session déjà ouverte : proposée si le code du lien n'est plus valide.
      apiPortail<EspacePortail>("/ged/portail/espace")
        .then(setSessionExistante)
        .catch(() => setSessionExistante(null));
    } else {
      apiPortail<EspacePortail>("/ged/portail/espace")
        .then(setEspace)
        .catch(() => setEspace(null))
        .finally(() => setVerification(false));
    }
    const surExpiration = () => {
      setEspace((actuel) => {
        if (actuel) setExpiree(true);
        return null;
      });
    };
    window.addEventListener(EVENEMENT_PORTAIL_EXPIRE, surExpiration);
    return () => window.removeEventListener(EVENEMENT_PORTAIL_EXPIRE, surExpiration);
  }, []);

  if (verification) return <p className="p-8 text-attenue">Chargement…</p>;
  if (!espace)
    return (
      <Connexion
        codeInitial={codeInvitation}
        expiree={expiree}
        sessionExistante={sessionExistante}
        surConnecte={(e) => {
          setExpiree(false);
          setCodeInvitation("");
          setEspace(e);
        }}
      />
    );
  return <Espace espace={espace} surMaj={setEspace} surDeconnecte={() => setEspace(null)} />;
}

function Connexion({
  codeInitial,
  expiree,
  sessionExistante,
  surConnecte,
}: {
  codeInitial: string;
  expiree: boolean;
  sessionExistante: EspacePortail | null;
  surConnecte: (espace: EspacePortail) => void;
}) {
  const [code, setCode] = useState(codeInitial);
  const [memoriser, setMemoriser] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  async function valider(evenement: FormEvent) {
    evenement.preventDefault();
    setEnvoi(true);
    setErreur(null);
    try {
      await jetonCsrfPortail(true);
      const espace = await apiPortail<EspacePortail>("/ged/acces", { method: "POST", body: JSON.stringify({ code, memoriser }) });
      await jetonCsrfPortail(true);
      surConnecte(espace);
    } catch (p) {
      setErreur(messageErreur(p, "Connexion impossible."));
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 px-4 py-10">
      <header className="flex flex-col gap-5">
        <Logo taille="grand" />
        <div className="flex flex-col gap-1">
          <span className="text-xs font-semibold uppercase tracking-[0.08em] text-accent">Accès des intervenants</span>
          <h1 className="font-titre text-2xl font-bold tracking-tight">Espace documentaire du chantier</h1>
        </div>
      </header>
      <form onSubmit={valider} className="flex flex-col gap-4 rounded-xl border border-bordure bg-surface p-5">
        {expiree && (
          <p className="rounded-lg border border-attention/40 bg-attention/10 px-3 py-2 text-sm">Session terminée : saisissez de nouveau votre code.</p>
        )}
        <div className="flex flex-col gap-1.5">
          <label htmlFor="code-acces" className="text-sm font-semibold">
            Votre code d'accès personnel
          </label>
          <input
            id="code-acces"
            value={code}
            onChange={(e) => setCode(formaterCode(e.target.value))}
            placeholder="XXXX-XXXX-XXXX"
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            required
            className={`${CLASSE_CHAMP} min-h-13 text-center font-mono text-xl tracking-widest`}
          />
        </div>
        <label className="flex items-start gap-2 text-sm text-attenue">
          <input type="checkbox" checked={memoriser} onChange={(e) => setMemoriser(e.target.checked)} className="mt-0.5 size-4 accent-accent" />
          Se souvenir de cet appareil pendant 30 jours (uniquement sur un ordinateur ou un téléphone personnel)
        </label>
        {erreur && (
          <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
            {erreur}
          </p>
        )}
        <button type="submit" disabled={envoi || code.replace(/-/g, "").length < 12} className={`${CLASSE_BOUTON_PRINCIPAL} justify-center`}>
          {envoi ? "Vérification…" : "Accéder aux documents"}
        </button>
      </form>
      {sessionExistante && (
        <button type="button" onClick={() => surConnecte(sessionExistante)} className={`${CLASSE_BOUTON} justify-center`}>
          Continuer avec la session ouverte ({sessionExistante.personne.nom}, {sessionExistante.intervenant.nom})
        </button>
      )}
      <p className="text-sm text-attenue">
        Le code figure dans le courriel d'invitation de la maîtrise d'œuvre. Il est personnel : chacun de vos collègues peut recevoir le sien. Code perdu ou ne
        fonctionnant plus ? Demandez-en un nouveau à la maîtrise d'œuvre.
      </p>
    </main>
  );
}

type OngletPortail = "documents" | "journal";

function Espace({ espace, surMaj, surDeconnecte }: { espace: EspacePortail; surMaj: (e: EspacePortail) => void; surDeconnecte: () => void }) {
  const { documentId } = useParams();
  const naviguer = useNavigate();
  const client = useMemo(() => clientPortail(), []);
  const [onglet, setOnglet] = useState<OngletPortail>("documents");
  const [preferences, setPreferences] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [erreurDeconnexion, setErreurDeconnexion] = useState<string | null>(null);
  const documentOuvert = documentId ? Number(documentId) : null;

  const ouvrir = useCallback((id: number | null) => naviguer(id === null ? "/ged" : `/ged/document/${id}`, { replace: true }), [naviguer]);

  async function deconnexion() {
    setErreurDeconnexion(null);
    try {
      await apiPortail("/ged/portail/deconnexion", { method: "POST" });
      surDeconnecte();
    } catch (p) {
      if (p instanceof ErreurApi && p.statut === 401) {
        surDeconnecte(); // session déjà terminée
        return;
      }
      // Session encore ouverte sur le serveur : l'écran de connexion n'est pas affiché (poste partagé).
      if (p instanceof ErreurApi && p.statut === 403) void jetonCsrfPortail(true).catch(() => undefined); // jeton renouvelé pour le nouvel essai
      setErreurDeconnexion("Déconnexion impossible : réessayez.");
    }
  }

  async function changerFrequence(frequence: Frequence) {
    try {
      surMaj(await apiPortail<EspacePortail>("/ged/portail/preferences", { method: "PATCH", body: JSON.stringify({ frequence }) }));
      setMessage("Préférence enregistrée.");
    } catch (p) {
      setMessage(messageErreur(p, "Enregistrement impossible."));
    }
  }

  const lots = espace.intervenant.lots.map((l) => `${l.code} – ${l.intitule}`).join(", ");
  return (
    <div className="min-h-screen">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b border-bordure bg-entete px-4 py-3 sm:px-8">
        <div className="flex min-w-0 flex-[1_1_300px] items-center gap-3">
          <div aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-md bg-accent text-sur-accent">
            <HardHat className="size-5" />
          </div>
          <div className="flex min-w-0 flex-col leading-tight">
            <span className="truncate font-titre text-lg font-bold">{espace.projet.nom}</span>
            <span className="truncate text-xs text-attenue">
              {espace.intervenant.nom} · {espace.intervenant.profil_libelle}
              {lots ? ` · ${lots}` : ""}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm">{espace.personne.nom}</span>
          <button type="button" onClick={() => setPreferences(!preferences)} aria-expanded={preferences} className={CLASSE_BOUTON}>
            <Mail aria-hidden="true" className="size-4" />
            Mes courriels
          </button>
          <button type="button" onClick={() => void deconnexion()} className={CLASSE_BOUTON}>
            <LogOut aria-hidden="true" className="size-4" />
            Déconnexion
          </button>
        </div>
      </header>

      <main className="mx-auto flex max-w-[1280px] flex-col gap-5 px-4 py-6 sm:px-8">
        {erreurDeconnexion && (
          <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
            {erreurDeconnexion}
          </p>
        )}
        {preferences && (
          <section aria-labelledby="titre-preferences" className="flex flex-col gap-3 rounded-xl border border-bordure bg-surface p-4">
            <h2 id="titre-preferences" className="font-semibold">
              Courriels reçus à {espace.personne.email || "(aucune adresse : demandez à la maîtrise d'œuvre de l'ajouter)"}
            </h2>
            <div className="flex flex-wrap gap-2">
              {espace.frequences.map((f) => (
                <label
                  key={f.code}
                  className={`flex min-h-10 cursor-pointer items-center gap-2 rounded-lg border px-3 text-sm ${espace.personne.frequence === f.code ? "border-accent bg-accent/10" : "border-bordure-forte"}`}
                >
                  <input
                    type="radio"
                    name="frequence"
                    checked={espace.personne.frequence === f.code}
                    onChange={() => void changerFrequence(f.code)}
                    className="accent-accent"
                  />
                  {f.libelle}
                </label>
              ))}
            </div>
            {message && (
              <p role="status" className="text-sm text-attenue">
                {message}
              </p>
            )}
          </section>
        )}

        {espace.statut_espace === "RECEPTION" && (
          <p className="rounded-lg border border-attention/40 bg-attention/10 px-4 py-3 text-sm">
            Chantier réceptionné : seuls le DOE, les éléments du DIUO, les levées de réserves et les photos sont encore attendus.
          </p>
        )}
        {espace.message_accueil && <p className="whitespace-pre-line text-attenue">{espace.message_accueil}</p>}

        <div role="tablist" aria-label="Sections" className="flex gap-1 border-b border-bordure">
          {(
            [
              ["documents", "Documents"],
              ["journal", "Dernières nouveautés"],
            ] as const
          ).map(([cle, libelle]) => (
            <button
              key={cle}
              type="button"
              role="tab"
              aria-selected={onglet === cle}
              onClick={() => setOnglet(cle)}
              className={`-mb-px flex min-h-11 items-center border-b-2 px-4 font-semibold ${onglet === cle ? "border-accent text-white" : "border-transparent text-attenue hover:text-texte"}`}
            >
              {libelle}
            </button>
          ))}
        </div>
        <div role="tabpanel">
          {onglet === "documents" ? (
            <Explorateur client={client} droits={espace.droits} referentiels={espace} documentOuvert={documentOuvert} surOuvrir={ouvrir} />
          ) : (
            <Journal
              client={client}
              surOuvrirDocument={(id) => {
                setOnglet("documents");
                ouvrir(id);
              }}
            />
          )}
        </div>
      </main>
    </div>
  );
}
