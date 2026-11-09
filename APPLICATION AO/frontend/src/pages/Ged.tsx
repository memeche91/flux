/** GED de chantier, côté cabinet : ouverture de l'espace, documents et visas, intervenants et
 * codes d'accès, journal, réglages, clôture et archivage du projet. */
import { AlertTriangle, Globe, Lock } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { api } from "../api/client";
import EnTetePage from "../components/EnTetePage";
import { CLASSE_CHAMP, Champ } from "../components/Filtres";
import { clientCabinet } from "../ged/client";
import Cloture from "../ged/Cloture";
import Explorateur from "../ged/Explorateur";
import Intervenants from "../ged/Intervenants";
import Invitations from "../ged/Invitations";
import Journal from "../ged/Journal";
import { CLASSE_BOUTON, CLASSE_BOUTON_PRINCIPAL, formaterJour, messageErreur } from "../ged/outils";
import type { EspaceGed, EtatGed, Invitation, StatutEspace, SuggestionIntervenant } from "../ged/types";
import { pluriel } from "../lib/format";

type Onglet = "documents" | "intervenants" | "journal" | "reglages" | "cloture";
const ONGLETS: { cle: Onglet; libelle: string }[] = [
  { cle: "documents", libelle: "Documents" },
  { cle: "intervenants", libelle: "Intervenants et accès" },
  { cle: "journal", libelle: "Journal" },
  { cle: "reglages", libelle: "Réglages" },
  { cle: "cloture", libelle: "Clôture et archives" },
];

export default function Ged() {
  const { projetId } = useParams();
  const [parametres, setParametres] = useSearchParams();
  const [etat, setEtat] = useState<EtatGed | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [invitations, setInvitations] = useState<Invitation[]>([]);

  const charger = useCallback(() => {
    api<EtatGed>(`/projets/${projetId}/ged`)
      .then((resultat) => {
        setEtat(resultat);
        setErreur(null);
      })
      .catch((p: unknown) => setErreur(messageErreur(p, "GED indisponible.")));
  }, [projetId]);

  useEffect(charger, [charger]);

  const espaceId = etat?.espace?.id;
  const client = useMemo(() => (espaceId ? clientCabinet(espaceId) : null), [espaceId]);
  const onglet = (ONGLETS.find((o) => o.cle === parametres.get("onglet"))?.cle ?? "documents") as Onglet;
  const documentOuvert = parametres.get("document") ? Number(parametres.get("document")) : null;

  const changerParametres = (modifs: Record<string, string | null>) =>
    setParametres(
      (actuels) => {
        const suivants = new URLSearchParams(actuels);
        for (const [cle, valeur] of Object.entries(modifs)) {
          if (valeur === null) suivants.delete(cle);
          else suivants.set(cle, valeur);
        }
        return suivants;
      },
      { replace: true },
    );

  if (erreur && !etat) {
    return (
      <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-danger">
        {erreur}
      </p>
    );
  }
  if (!etat) return <p className="text-attenue">Chargement de la GED…</p>;

  const espace = etat.espace;
  return (
    <>
      <nav aria-label="Fil d'Ariane" className="text-sm text-attenue">
        <Link to="/projets" className="text-attenue hover:text-texte">
          Projets
        </Link>{" "}
        /{" "}
        <Link to={`/projets/${etat.projet.id}`} className="text-attenue hover:text-texte">
          {etat.projet.nom}
        </Link>{" "}
        / <span className="text-texte">GED de chantier</span>
      </nav>
      <EnTetePage
        surtitre={`Étape 4 · ${espace ? espace.statut_libelle : "après la notification des marchés"}`}
        titre="GED de chantier"
        sousTitre="Plans, visas et documents d'exécution partagés avec les entreprises et les intervenants : un code d'accès personnel, un classement par lots, des indices tenus et l'historique complet."
      />

      <AccesInternet urlPublique={etat.url_publique} />

      {invitations.length > 0 && (
        <Invitations
          invitations={invitations}
          projet={etat.projet.nom}
          emailActif={etat.email_actif}
          surRemplacer={(ancienne, nouvelle) => setInvitations((liste) => liste.map((i) => (i.acces_id === ancienne.acces_id ? nouvelle : i)))}
          surFermer={() => setInvitations([])}
        />
      )}

      {!espace ? (
        <>
          <Ouverture
            etat={etat}
            surOuvert={(resultat) => {
              setEtat(resultat);
              setInvitations(resultat.invitations ?? []);
            }}
          />
          <Cloture projetId={etat.projet.id} />
        </>
      ) : (
        <>
          <Statistiques espace={espace} surVoir={(vue) => changerParametres({ onglet: vue })} />
          <div role="tablist" aria-label="Sections de la GED" className="flex flex-wrap gap-1 border-b border-bordure">
            {ONGLETS.map((o) => (
              <button
                key={o.cle}
                type="button"
                role="tab"
                aria-selected={onglet === o.cle}
                onClick={() => changerParametres({ onglet: o.cle === "documents" ? null : o.cle })}
                className={`-mb-px flex min-h-11 items-center border-b-2 px-4 font-semibold ${onglet === o.cle ? "border-accent text-white" : "border-transparent text-attenue hover:text-texte"}`}
              >
                {o.libelle}
              </button>
            ))}
          </div>
          <div role="tabpanel">
            {onglet === "documents" && client && (
              <Explorateur
                client={client}
                droits={espace.droits}
                referentiels={etat}
                documentOuvert={documentOuvert}
                surOuvrir={(id) => changerParametres({ document: id === null ? null : String(id) })}
                surChangement={charger}
              />
            )}
            {onglet === "intervenants" && (
              <Intervenants
                etat={{ ...etat, espace }}
                surMaj={charger}
                // Codes affichés une seule fois : les nouveaux s'ajoutent à ceux déjà à l'écran.
                surInvitations={(nouvelles) =>
                  setInvitations((actuelles) => [...actuelles.filter((a) => !nouvelles.some((n) => n.acces_id === a.acces_id)), ...nouvelles])
                }
              />
            )}
            {onglet === "journal" && client && (
              <Journal client={client} surOuvrirDocument={(id) => changerParametres({ onglet: null, document: String(id) })} />
            )}
            {onglet === "reglages" && <Reglages espace={espace} surMaj={setEtat} />}
            {onglet === "cloture" && <Cloture projetId={etat.projet.id} surPurge={charger} />}
          </div>
        </>
      )}
    </>
  );
}

function AccesInternet({ urlPublique }: { urlPublique: string }) {
  return urlPublique ? (
    <p className="flex flex-wrap items-center gap-2 text-sm text-attenue">
      <Globe aria-hidden="true" className="size-4 text-succes" />
      Les intervenants se connectent sur <span className="font-mono text-texte">{urlPublique.replace(/\/$/, "")}/ged</span>
    </p>
  ) : (
    <p className="flex flex-wrap items-center gap-2 rounded-lg border border-bordure bg-surface px-4 py-3 text-sm text-attenue">
      <Lock aria-hidden="true" className="size-4" />
      GED accessible seulement sur le réseau du cabinet. Pour l'ouvrir aux entreprises sur Internet (gratuitement, avec le nom de domaine du cabinet), videz la
      ligne GED_INTERNET= du fichier .env, puis relancez installer.ps1 et répondez « O » à la question « Ouvrir la GED aux entreprises sur Internet ».
    </p>
  );
}

function Statistiques({ espace, surVoir }: { espace: EspaceGed; surVoir: (onglet: Onglet) => void }) {
  const s = espace.statistiques;
  const actifs = espace.intervenants.filter((i) => i.actif).length;
  return (
    <div className="flex flex-wrap gap-3">
      <Tuile valeur={s.documents} libelle={s.documents > 1 ? "documents" : "document"} />
      <Tuile valeur={s.en_attente_visa} libelle="en attente de visa" attention={s.en_attente_visa > 0} />
      {s.visas_en_retard > 0 && <Tuile valeur={s.visas_en_retard} libelle="visas en retard" alerte />}
      <Tuile valeur={actifs} libelle={actifs > 1 ? "intervenants" : "intervenant"} surClic={() => surVoir("intervenants")} />
      {s.notifications_en_echec > 0 && (
        <p className="flex items-center gap-2 rounded-xl border border-danger/40 bg-danger/10 px-4 py-2 text-sm text-danger">
          <AlertTriangle aria-hidden="true" className="size-4" />
          {pluriel(s.notifications_en_echec, "courriel")} non parti{s.notifications_en_echec > 1 ? "s" : ""} : nouvel essai automatique toutes les 15 minutes
          (réglage de la messagerie ?).
        </p>
      )}
    </div>
  );
}

function Tuile({
  valeur,
  libelle,
  attention,
  alerte,
  surClic,
}: {
  valeur: number;
  libelle: string;
  attention?: boolean;
  alerte?: boolean;
  surClic?: () => void;
}) {
  const contenu = (
    <>
      <span className={`font-titre text-2xl font-bold ${alerte ? "text-danger" : attention ? "text-attention" : ""}`}>{valeur.toLocaleString("fr-FR")}</span>
      <span className="text-sm text-attenue">{libelle}</span>
    </>
  );
  const classe = "flex min-w-36 flex-col rounded-xl border border-bordure bg-surface px-4 py-2.5 text-left";
  return surClic ? (
    <button type="button" onClick={surClic} className={`${classe} hover:bg-surface-2`}>
      {contenu}
    </button>
  ) : (
    <div className={classe}>{contenu}</div>
  );
}

// --- Ouverture de l'espace ----------------------------------------------------------------------

interface ChoixSuggestion extends SuggestionIntervenant {
  retenu: boolean;
}

function Ouverture({ etat, surOuvert }: { etat: EtatGed; surOuvert: (resultat: EtatGed & { invitations?: Invitation[] }) => void }) {
  const [choix, setChoix] = useState<ChoixSuggestion[]>(etat.suggestions.map((s) => ({ ...s, retenu: true })));
  const [importerDce, setImporterDce] = useState(true);
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  async function ouvrir(evenement: FormEvent) {
    evenement.preventDefault();
    setEnvoi(true);
    setErreur(null);
    try {
      const resultat = await api<EtatGed & { invitations: Invitation[]; documents_importes: number }>(`/projets/${etat.projet.id}/ged`, {
        method: "POST",
        body: JSON.stringify({
          importer_dce: importerDce,
          intervenants: choix
            .filter((c) => c.retenu)
            .map((c) => ({
              entreprise_id: c.entreprise_id,
              nom: c.nom,
              profil: "ENTREPRISE",
              lot_ids: c.lots.map((l) => l.id),
              personnes: c.personnes.filter((p) => p.nom.trim() || p.email.trim()),
            })),
        }),
      });
      surOuvert(resultat);
    } catch (p) {
      setErreur(messageErreur(p, "Ouverture impossible."));
    } finally {
      setEnvoi(false);
    }
  }

  const majPersonne = (indice: number, position: number, champ: "nom" | "email", valeur: string) =>
    setChoix((liste) =>
      liste.map((c, i) => (i === indice ? { ...c, personnes: c.personnes.map((p, j) => (j === position ? { ...p, [champ]: valeur } : p)) } : c)),
    );

  return (
    <form onSubmit={ouvrir} className="flex flex-col gap-5 rounded-xl border border-accent/40 bg-surface p-5" aria-labelledby="titre-ouverture">
      <div className="flex flex-col gap-1">
        <h2 id="titre-ouverture" className="font-titre text-lg font-semibold">
          Ouvrir l'espace documentaire du chantier
        </h2>
        <p className="text-sm text-attenue">
          Une fois les marchés notifiés, ouvrez l'espace : chaque personne des entreprises reçoit son propre code d'accès. Vous pourrez ajouter ensuite la
          maîtrise d'œuvre associée, le maître d'ouvrage, le contrôleur technique, le CSPS et l'OPC.
        </p>
      </div>
      {choix.length > 0 ? (
        <fieldset className="flex flex-col gap-3">
          <legend className="mb-2 font-semibold">Entreprises retenues à l'analyse des offres</legend>
          {choix.map((c, indice) => (
            <div
              key={c.entreprise_id}
              className={`flex flex-col gap-2 rounded-lg border px-4 py-3 ${c.retenu ? "border-bordure-forte bg-fond" : "border-bordure opacity-60"}`}
            >
              <label className="flex items-center gap-2 font-semibold">
                <input
                  type="checkbox"
                  checked={c.retenu}
                  onChange={(e) => setChoix((l) => l.map((x, i) => (i === indice ? { ...x, retenu: e.target.checked } : x)))}
                  className="size-4 accent-accent"
                />
                {c.nom} <span className="font-normal text-attenue">· lots {c.lots.map((l) => `${l.code} – ${l.intitule}`).join(", ")}</span>
              </label>
              {c.retenu &&
                (c.personnes.length ? (
                  c.personnes.map((p, position) => (
                    <div key={position} className="flex flex-wrap gap-2 pl-6">
                      <Champ id={`ouverture-${indice}-${position}-nom`} libelle="Nom">
                        <input
                          id={`ouverture-${indice}-${position}-nom`}
                          value={p.nom}
                          onChange={(e) => majPersonne(indice, position, "nom", e.target.value)}
                          className={CLASSE_CHAMP}
                        />
                      </Champ>
                      <Champ id={`ouverture-${indice}-${position}-email`} libelle="E-mail" large>
                        <input
                          id={`ouverture-${indice}-${position}-email`}
                          type="email"
                          value={p.email}
                          onChange={(e) => majPersonne(indice, position, "email", e.target.value)}
                          className={CLASSE_CHAMP}
                        />
                      </Champ>
                    </div>
                  ))
                ) : (
                  <p className="pl-6 text-sm text-attenue">Aucun contact dans l'annuaire : un code est créé au nom de l'entreprise (à remettre vous-même).</p>
                ))}
            </div>
          ))}
        </fieldset>
      ) : (
        <p className="rounded-lg border border-bordure bg-fond px-4 py-3 text-sm text-attenue">
          Aucune entreprise retenue à l'analyse des offres : vous ajouterez les intervenants après l'ouverture (onglet « Intervenants et accès »).
        </p>
      )}
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={importerDce} onChange={(e) => setImporterDce(e.target.checked)} className="size-4 accent-accent" />
        Reprendre les plans et documents joints au DCE comme « Pièces du marché » (indice 0)
      </label>
      {erreur && (
        <p role="alert" className="text-danger">
          {erreur}
        </p>
      )}
      <div className="flex justify-end">
        <button type="submit" disabled={envoi} className={CLASSE_BOUTON_PRINCIPAL}>
          {envoi ? "Ouverture…" : "Ouvrir l'espace et créer les codes"}
        </button>
      </div>
    </form>
  );
}

// --- Réglages -----------------------------------------------------------------------------------

function Reglages({ espace, surMaj }: { espace: EspaceGed; surMaj: (etat: EtatGed) => void }) {
  const [notifications, setNotifications] = useState(espace.notifications);
  const [emails, setEmails] = useState(espace.emails_moe.join("\n"));
  const [accueil, setAccueil] = useState(espace.message_accueil);
  const [delai, setDelai] = useState(String(espace.delai_visa_jours));
  const [interLots, setInterLots] = useState(espace.lecture_inter_lots);
  const [reception, setReception] = useState(espace.date_reception ?? "");
  const [message, setMessage] = useState<{ ok: boolean; texte: string } | null>(null);

  async function envoyer(donnees: Record<string, unknown>, succes: string) {
    setMessage(null);
    try {
      surMaj(await api<EtatGed>(`/ged/espaces/${espace.id}`, { method: "PATCH", body: JSON.stringify(donnees) }));
      setMessage({ ok: true, texte: succes });
    } catch (p) {
      setMessage({ ok: false, texte: messageErreur(p, "Enregistrement impossible.") });
    }
  }

  function enregistrer(evenement: FormEvent) {
    evenement.preventDefault();
    void envoyer(
      {
        notifications,
        emails_moe: emails.split(/[\s,;]+/).filter(Boolean),
        message_accueil: accueil,
        delai_visa_jours: Number(delai),
        lecture_inter_lots: interLots,
      },
      "Réglages enregistrés.",
    );
  }

  function changerStatut(statut: StatutEspace, question: string) {
    if (!window.confirm(question)) return;
    void envoyer({ statut, date_reception: reception || null }, "Statut de l'espace modifié.");
  }

  return (
    <div className="flex flex-col gap-5">
      <form onSubmit={enregistrer} className="flex flex-col gap-4 rounded-xl border border-bordure bg-surface p-5">
        <h2 className="font-titre text-lg font-semibold">Réglages de l'espace</h2>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={notifications} onChange={(e) => setNotifications(e.target.checked)} className="size-4 accent-accent" />
          Prévenir par courriel à chaque nouveauté (chaque personne choisit ensuite : immédiat, récapitulatif quotidien ou aucun)
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={interLots} onChange={(e) => setInterLots(e.target.checked)} className="size-4 accent-accent" />
          Chaque entreprise consulte aussi les documents techniques des autres lots (synthèse) ; les pièces chiffrées restent réservées à leur lot
        </label>
        <div className="flex flex-wrap gap-3">
          <Champ id="reglage-delai" libelle="Délai de visa (jours, CCAG : 15)">
            <input id="reglage-delai" type="number" min={1} max={90} value={delai} onChange={(e) => setDelai(e.target.value)} className={CLASSE_CHAMP} />
          </Champ>
          <Champ id="reglage-emails" libelle="Adresses de la maîtrise d'œuvre prévenues (une par ligne)" large>
            <textarea id="reglage-emails" rows={3} value={emails} onChange={(e) => setEmails(e.target.value)} className={`${CLASSE_CHAMP} py-2`} />
          </Champ>
        </div>
        <Champ id="reglage-accueil" libelle="Message d'accueil affiché aux intervenants" large>
          <textarea
            id="reglage-accueil"
            rows={3}
            value={accueil}
            onChange={(e) => setAccueil(e.target.value)}
            maxLength={4000}
            className={`${CLASSE_CHAMP} py-2`}
          />
        </Champ>
        <div className="flex flex-wrap items-center justify-end gap-3">
          {message && (
            <span role="status" className={message.ok ? "text-succes" : "text-danger"}>
              {message.texte}
            </span>
          )}
          <button type="submit" className={CLASSE_BOUTON_PRINCIPAL}>
            Enregistrer
          </button>
        </div>
      </form>

      <section aria-labelledby="titre-statut" className="flex flex-col gap-3 rounded-xl border border-bordure bg-surface p-5">
        <h2 id="titre-statut" className="font-titre text-lg font-semibold">
          Avancement : {espace.statut_libelle.toLowerCase()}
        </h2>
        <p className="text-sm text-attenue">
          Après la réception, les entreprises ne déposent plus que le DOE, les éléments du DIUO, les levées de réserves et les photos. L'espace clos n'est plus
          accessible aux intervenants ; préparez ensuite l'archive du projet (onglet « Clôture et archives »).
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <Champ id="reglage-reception" libelle="Date de réception des travaux">
            <input id="reglage-reception" type="date" value={reception} onChange={(e) => setReception(e.target.value)} className={CLASSE_CHAMP} />
          </Champ>
          {espace.statut === "OUVERT" && (
            <button
              type="button"
              disabled={!reception}
              onClick={() =>
                changerStatut(
                  "RECEPTION",
                  `Passer l'espace en réception au ${formaterJour(reception)} ? Les entreprises ne déposeront plus que DOE, DIUO, réserves et photos.`,
                )
              }
              className={CLASSE_BOUTON_PRINCIPAL}
            >
              Chantier réceptionné
            </button>
          )}
          {espace.statut === "RECEPTION" && (
            <>
              <button
                type="button"
                onClick={() =>
                  changerStatut(
                    "CLOS",
                    "Clore l'espace ? Plus aucun dépôt ni visa, et les intervenants perdent tout accès (consultation comprise) ; rouvrez l'espace pour le leur rendre.",
                  )
                }
                className={CLASSE_BOUTON_PRINCIPAL}
              >
                Clore l'espace
              </button>
              <button type="button" onClick={() => changerStatut("OUVERT", "Revenir en chantier en cours ?")} className={CLASSE_BOUTON}>
                Revenir en chantier en cours
              </button>
            </>
          )}
          {espace.statut === "CLOS" && (
            <button type="button" onClick={() => changerStatut("RECEPTION", "Rouvrir l'espace (DOE, réserves) ?")} className={CLASSE_BOUTON}>
              Rouvrir l'espace
            </button>
          )}
          {reception !== (espace.date_reception ?? "") && espace.statut !== "OUVERT" && (
            <button
              type="button"
              onClick={() => void envoyer({ date_reception: reception || null }, "Date de réception enregistrée.")}
              className={CLASSE_BOUTON}
            >
              Enregistrer la date
            </button>
          )}
        </div>
      </section>
    </div>
  );
}
