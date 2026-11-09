import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Download,
  ExternalLink,
  FilePlus2,
  FileSpreadsheet,
  FileText,
  Loader2,
  MessageSquareText,
  RefreshCw,
  RotateCcw,
  Trash2,
  Trophy,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { api, televerser } from "../api/client";
import type {
  ComparatifLot,
  EntrepriseResume,
  EtatOffres,
  LotAnalyse,
  MethodePrix,
  OffreAnalyse,
  Projet,
  StatutLectureOffre,
} from "../api/types";
import EnTetePage from "../components/EnTetePage";
import { CLASSE_CHAMP, Champ } from "../components/Filtres";
import { formaterDate, formaterEuros, formaterQuantite, pluriel } from "../lib/format";

const FORMATS_OFFRE = ".xlsx,.xlsm,.xls,.ods,.csv,.pdf,.docx,.doc,.odt";
const CLASSE_BOUTON_SECONDAIRE =
  "flex min-h-10 items-center gap-2 rounded-lg border border-bordure-forte px-3 text-sm font-semibold text-texte no-underline hover:bg-surface-2 disabled:opacity-50";

const STYLE_STATUT: Record<StatutLectureOffre, string> = {
  EN_COURS: "border-info/40 bg-info/10 text-info",
  LUE: "border-succes/40 bg-succes/10 text-succes",
  A_VERIFIER: "border-accent/50 bg-accent/10 text-accent",
  NON_LUE: "border-danger/40 bg-danger/10 text-danger",
  MANUELLE: "border-bordure-forte bg-surface-2 text-attenue",
};

/** « 12 500,50 » → 12500.5 ; vide → null ; illisible → NaN. */
function lireMontant(texte: string): number | null {
  const propre = texte.replace(/[\s  €]/g, "").replace(",", ".");
  if (!propre) return null;
  return /^\d+(\.\d{0,2})?$/.test(propre) ? Number(propre) : Number.NaN;
}

function formaterSaisie(valeur: number | null): string {
  return valeur == null ? "" : valeur.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formaterNote(valeur: number | null | undefined): string {
  return valeur == null ? "—" : valeur.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
}

function formaterEcart(valeur: number | null): string {
  if (valeur == null) return "—";
  return `${valeur > 0 ? "+" : ""}${valeur.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`;
}

const message = (probleme: unknown, defaut: string) => (probleme instanceof Error ? probleme.message : defaut);

export default function Offres() {
  const { projetId } = useParams();
  const [parametres, setParametres] = useSearchParams();
  const [projet, setProjet] = useState<Projet | null>(null);
  const [etat, setEtat] = useState<EtatOffres | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(() => {
    api<EtatOffres>(`/projets/${projetId}/offres`)
      .then(setEtat)
      .catch((p: unknown) => setErreur(message(p, "Analyse des offres indisponible.")));
  }, [projetId]);

  useEffect(() => {
    api<Projet>(`/projets/${projetId}`)
      .then(setProjet)
      .catch((p: unknown) => setErreur(message(p, "Projet introuvable.")));
    charger();
  }, [projetId, charger]);

  const majLot = useCallback((lot: LotAnalyse) => setEtat((e) => e && { ...e, lots: e.lots.map((l) => (l.id === lot.id ? lot : l)) }), []);
  const rechargerLot = useCallback(
    (lotId: number) =>
      api<LotAnalyse>(`/lots-projet/${lotId}/offres`)
        .then(majLot)
        .catch(() => undefined),
    [majLot],
  );

  const lot = etat?.lots.find((l) => String(l.id) === parametres.get("lot")) ?? etat?.lots[0] ?? null;

  // Lecture des offres en tâche de fond : suivi jusqu'à la fin.
  const lectureEnCours = Boolean(lot?.offres.some((o) => o.statut_lecture === "EN_COURS"));
  const lotId = lot?.id;
  useEffect(() => {
    if (!lectureEnCours || lotId === undefined) return;
    const minuteur = window.setInterval(() => void rechargerLot(lotId), 2500);
    return () => window.clearInterval(minuteur);
  }, [lectureEnCours, lotId, rechargerLot]);

  if (erreur && !etat) {
    return (
      <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-danger">
        {erreur}
      </p>
    );
  }
  if (!projet || !etat) return <p className="text-attenue">Chargement de l'analyse des offres…</p>;

  const base = `/api/projets/${projet.id}`;
  return (
    <>
      <nav aria-label="Fil d'Ariane" className="text-sm text-attenue">
        <Link to="/projets" className="text-attenue hover:text-texte">
          Projets
        </Link>{" "}
        /{" "}
        <Link to={`/projets/${projet.id}`} className="text-attenue hover:text-texte">
          {projet.nom}
        </Link>{" "}
        / <span className="text-texte">Analyse des offres</span>
      </nav>
      <EnTetePage
        surtitre={`Étape 3 · ${etat.type_marche === "PUBLIC" ? "Marché public" : "Marché privé"}`}
        titre="Analyse des offres"
        sousTitre="Déposez les DPGF remplies ou les devis : les prix sont lus et rapprochés de votre estimation, ouvrage par ouvrage. Notez la valeur technique, l'application calcule la note de prix, classe les offres et rédige le rapport d'analyse."
        actions={
          etat.lots.length > 0 && (
            <>
              <a href={`${base}/rapport-act/docx`} className={CLASSE_BOUTON_SECONDAIRE}>
                <FileText aria-hidden="true" className="size-4 text-accent" />
                Rapport ACT Word
              </a>
              <a href={`${base}/rapport-act/pdf`} className={CLASSE_BOUTON_SECONDAIRE}>
                <Download aria-hidden="true" className="size-4 text-accent" />
                PDF
              </a>
              <a href={`${base}/comparatif-offres.xlsx`} className={CLASSE_BOUTON_SECONDAIRE}>
                <FileSpreadsheet aria-hidden="true" className="size-4 text-accent" />
                Comparatif Excel
              </a>
            </>
          )
        }
      />
      {etat.lots.length === 0 || !lot ? (
        <p className="rounded-xl border border-bordure bg-surface p-5 text-attenue">
          Ce projet n'a pas encore de lot. <Link to={`/projets/${projet.id}`}>Ajoutez les lots</Link> et leur DPGF avant d'analyser les offres.
        </p>
      ) : (
        <>
          <OngletsLots lots={etat.lots} courant={lot} surChoix={(id) => setParametres({ lot: String(id) }, { replace: true })} />
          <div role="tabpanel" id={`panneau-lot-${lot.id}`} aria-labelledby={`onglet-lot-${lot.id}`} className="flex flex-col gap-5">
            <OffresRecues key={`offres-${lot.id}`} lot={lot} surLot={majLot} recharger={() => void rechargerLot(lot.id)} />
            {lot.offres.length > 0 && (
              <>
                <Comparatif key={`comparatif-${lot.id}`} lot={lot} surLot={majLot} />
                <Notation key={`notation-${lot.id}`} lot={lot} projetId={projet.id} surLot={majLot} />
                <Attribution key={`attribution-${lot.id}`} lot={lot} projetId={projet.id} tauxTva={etat.taux_tva} surLot={majLot} />
              </>
            )}
          </div>
        </>
      )}
    </>
  );
}

function OngletsLots({ lots, courant, surChoix }: { lots: LotAnalyse[]; courant: LotAnalyse; surChoix: (id: number) => void }) {
  const references = useRef<Map<number, HTMLButtonElement>>(new Map());
  function clavier(evenement: KeyboardEvent, indice: number) {
    const decalage = { ArrowRight: 1, ArrowLeft: -1 }[evenement.key];
    if (decalage === undefined) return;
    evenement.preventDefault();
    const suivant = lots[(indice + decalage + lots.length) % lots.length];
    surChoix(suivant.id);
    references.current.get(suivant.id)?.focus();
  }
  return (
    <div role="tablist" aria-label="Lots" className="relative flex gap-2 overflow-x-auto pb-1">
      {lots.map((lot, indice) => {
        const actif = lot.id === courant.id;
        const recues = lot.offres.length;
        return (
          <button
            key={lot.id}
            ref={(element) => {
              if (element) references.current.set(lot.id, element);
            }}
            type="button"
            role="tab"
            id={`onglet-lot-${lot.id}`}
            aria-selected={actif}
            aria-controls={`panneau-lot-${lot.id}`}
            tabIndex={actif ? 0 : -1}
            onClick={() => surChoix(lot.id)}
            onKeyDown={(e) => clavier(e, indice)}
            className={`flex min-h-12 shrink-0 flex-col items-start justify-center rounded-lg border px-3.5 py-1.5 text-left ${
              actif ? "border-accent bg-accent/12 text-texte" : "border-bordure bg-surface text-attenue hover:bg-surface-2"
            }`}
          >
            <span className="flex items-center gap-1.5 font-semibold">
              Lot {lot.code}
              {lot.analyse.validee_le && <CheckCircle2 aria-label="proposition validée" className="size-3.5 text-succes" />}
            </span>
            <span className="max-w-48 truncate text-xs">
              {lot.intitule} · {recues ? pluriel(recues, "offre") : "aucune offre"}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function Section({ id, numero, titre, children, actions }: { id: string; numero: number; titre: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex min-w-0 flex-col gap-3 rounded-xl border border-bordure bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={id} className="flex items-center gap-2.5 font-titre text-lg font-semibold">
          <span aria-hidden="true" className="grid size-7 place-items-center rounded-full bg-accent/15 text-sm text-accent">
            {numero}
          </span>
          {titre}
        </h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

// --- 1. Offres reçues -------------------------------------------------------------

function OffresRecues({ lot, surLot, recharger }: { lot: LotAnalyse; surLot: (lot: LotAnalyse) => void; recharger: () => void }) {
  const [annuaire, setAnnuaire] = useState<EntrepriseResume[]>([]);
  const [entrepriseId, setEntrepriseId] = useState("");
  const [fichier, setFichier] = useState<File | null>(null);
  const [montant, setMontant] = useState("");
  const [variante, setVariante] = useState(false);
  const [libelleVariante, setLibelleVariante] = useState("");
  const [progression, setProgression] = useState<number | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [survol, setSurvol] = useState(false);

  useEffect(() => {
    api<EntrepriseResume[]>("/entreprises?actives=true")
      .then(setAnnuaire)
      .catch(() => setAnnuaire([]));
  }, []);

  const attendues = new Set(lot.consultees_sans_offre.map((c) => c.entreprise_id));
  const ayantRemis = new Set(lot.offres.map((o) => o.entreprise_id));
  const autres = annuaire.filter((e) => !attendues.has(e.id));
  const dejaRemise = entrepriseId !== "" && ayantRemis.has(Number(entrepriseId));

  async function enregistrer(evenement: FormEvent) {
    evenement.preventDefault();
    setErreur(null);
    const valeur = lireMontant(montant);
    if (!fichier && (valeur == null || Number.isNaN(valeur))) {
      setErreur("Joignez la DPGF ou le devis de l'entreprise, ou saisissez le montant de son offre.");
      return;
    }
    const donnees = new FormData();
    donnees.append("entreprise_id", entrepriseId);
    if (fichier) donnees.append("fichier", fichier);
    else if (valeur != null) donnees.append("montant_base", String(valeur));
    donnees.append("variante", String(variante));
    if (variante) donnees.append("libelle_variante", libelleVariante);
    setProgression(0);
    try {
      await televerser(`/lots-projet/${lot.id}/offres`, donnees, setProgression);
      setEntrepriseId("");
      setFichier(null);
      setMontant("");
      setVariante(false);
      setLibelleVariante("");
      recharger();
    } catch (probleme) {
      setErreur(message(probleme, "Enregistrement impossible."));
    } finally {
      setProgression(null);
    }
  }

  return (
    <Section id={`offres-recues-${lot.id}`} numero={1} titre="Offres reçues">
      <form onSubmit={enregistrer} className="flex flex-col gap-3 rounded-lg border border-bordure bg-fond/40 p-3.5">
        <div className="flex flex-wrap items-end gap-3">
          <Champ id="offre-entreprise" libelle="Entreprise" large>
            <select id="offre-entreprise" required value={entrepriseId} onChange={(e) => setEntrepriseId(e.target.value)} className={CLASSE_CHAMP}>
              <option value="">Choisir une entreprise…</option>
              {lot.consultees_sans_offre.length > 0 && (
                <optgroup label="Consultées pour ce lot, offre attendue">
                  {lot.consultees_sans_offre.map((c) => (
                    <option key={c.entreprise_id} value={c.entreprise_id}>
                      {c.entreprise}
                    </option>
                  ))}
                </optgroup>
              )}
              <optgroup label="Annuaire des entreprises">
                {autres.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.raison_sociale}
                    {e.ville ? ` (${e.ville})` : ""}
                    {ayantRemis.has(e.id) ? " · offre déjà reçue" : ""}
                  </option>
                ))}
              </optgroup>
            </select>
          </Champ>
          <Champ id="offre-montant" libelle="Montant HT (sans document)">
            <input
              id="offre-montant"
              inputMode="decimal"
              autoComplete="off"
              placeholder="ex. 48 250,00"
              value={montant}
              disabled={Boolean(fichier)}
              onChange={(e) => setMontant(e.target.value)}
              className={`${CLASSE_CHAMP} disabled:opacity-50`}
            />
          </Champ>
        </div>
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setSurvol(true);
          }}
          onDragLeave={() => setSurvol(false)}
          onDrop={(e) => {
            e.preventDefault();
            setSurvol(false);
            setFichier(e.dataTransfer.files[0] ?? null);
          }}
          className={`flex min-h-20 cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed px-4 py-3 text-center focus-within:ring-2 focus-within:ring-accent ${
            survol ? "border-accent bg-accent/10" : "border-bordure-forte hover:bg-surface-2"
          }`}
        >
          <FilePlus2 aria-hidden="true" className="size-5 text-accent" />
          <span className="font-semibold">{fichier ? fichier.name : "DPGF remplie ou devis : déposez le fichier ici ou cliquez pour le choisir"}</span>
          <span className="text-xs text-attenue">Excel, PDF (même scanné), Word, CSV. Les prix sont lus automatiquement.</span>
          <input
            type="file"
            accept={FORMATS_OFFRE}
            className="sr-only"
            onChange={(e) => {
              setFichier(e.target.files?.[0] ?? null);
              e.target.value = "";
            }}
          />
        </label>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <label className="flex min-h-10 items-center gap-2 text-sm">
            <input type="checkbox" checked={variante} onChange={(e) => setVariante(e.target.checked)} className="size-4 accent-[var(--color-accent)]" />
            Variante proposée par l'entreprise
          </label>
          {variante && (
            <input
              aria-label="Libellé de la variante"
              placeholder="Libellé de la variante (ex. menuiseries PVC)"
              value={libelleVariante}
              maxLength={255}
              onChange={(e) => setLibelleVariante(e.target.value)}
              className={`${CLASSE_CHAMP} max-w-sm flex-1`}
            />
          )}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {fichier && (
              <button type="button" onClick={() => setFichier(null)} className={CLASSE_BOUTON_SECONDAIRE}>
                Retirer le fichier
              </button>
            )}
            <button
              type="submit"
              disabled={progression !== null || !entrepriseId}
              className="flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4.5 font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-50"
            >
              {progression !== null ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : <FilePlus2 aria-hidden="true" className="size-4" />}
              {progression !== null ? `Envoi ${Math.round(progression * 100)} %` : "Enregistrer l'offre"}
            </button>
          </div>
        </div>
        {dejaRemise && !variante && (
          <p className="text-sm text-accent">Cette entreprise a déjà remis une offre pour ce lot : cochez « Variante » ou modifiez l'offre existante ci-dessous.</p>
        )}
        {erreur && (
          <p role="alert" className="text-sm text-danger">
            {erreur}
          </p>
        )}
      </form>

      {lot.consultees_sans_offre.length > 0 && (
        <p className="text-sm text-attenue">
          Sans offre à ce jour : {lot.consultees_sans_offre.map((c) => c.entreprise + (c.statut === "EXCUSEE" ? " (excusée)" : "")).join(", ")}.
        </p>
      )}
      {lot.offres.length === 0 ? (
        <p className="text-attenue">Aucune offre enregistrée pour ce lot.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {lot.offres.map((offre) => (
            <CarteOffre key={offre.id} offre={offre} lot={lot} surLot={surLot} recharger={recharger} />
          ))}
        </ul>
      )}
    </Section>
  );
}

/** Champ de montant enregistré quand on le quitte (ou avec Entrée). */
function ChampMontant({
  id,
  libelle,
  valeur,
  surEnregistrer,
  indication,
}: {
  id: string;
  libelle: string;
  valeur: number | null;
  surEnregistrer: (valeur: number | null) => Promise<void>;
  indication?: string;
}) {
  const [texte, setTexte] = useState(formaterSaisie(valeur));
  const [invalide, setInvalide] = useState(false);
  useEffect(() => setTexte(formaterSaisie(valeur)), [valeur]);

  async function valider() {
    const lu = lireMontant(texte);
    if (lu != null && Number.isNaN(lu)) {
      setInvalide(true);
      return;
    }
    setInvalide(false);
    if (lu === valeur) {
      setTexte(formaterSaisie(valeur));
      return;
    }
    await surEnregistrer(lu);
  }

  return (
    <Champ id={id} libelle={libelle}>
      <input
        id={id}
        inputMode="decimal"
        autoComplete="off"
        value={texte}
        aria-invalid={invalide}
        aria-describedby={indication ? `${id}-aide` : undefined}
        onChange={(e) => setTexte(e.target.value)}
        onBlur={() => void valider()}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        }}
        className={`${CLASSE_CHAMP} text-right tabular-nums ${invalide ? "border-danger" : ""}`}
      />
      {(indication || invalide) && (
        <span id={`${id}-aide`} className={`text-xs ${invalide ? "text-danger" : "text-attenue"}`}>
          {invalide ? "Montant invalide (ex. 12 500,00)." : indication}
        </span>
      )}
    </Champ>
  );
}

function CarteOffre({ offre, lot, surLot, recharger }: { offre: OffreAnalyse; lot: LotAnalyse; surLot: (lot: LotAnalyse) => void; recharger: () => void }) {
  const [erreur, setErreur] = useState<string | null>(null);
  const [motif, setMotif] = useState(offre.motif_ecart);
  const [delai, setDelai] = useState(offre.delai_propose);
  useEffect(() => setMotif(offre.motif_ecart), [offre.motif_ecart]);
  useEffect(() => setDelai(offre.delai_propose), [offre.delai_propose]);

  const modifier = useCallback(
    async (donnees: Record<string, unknown>) => {
      setErreur(null);
      try {
        surLot(await api<LotAnalyse>(`/offres/${offre.id}`, { method: "PATCH", body: JSON.stringify(donnees) }));
      } catch (probleme) {
        setErreur(message(probleme, "Enregistrement impossible."));
      }
    },
    [offre.id, surLot],
  );

  async function relire() {
    setErreur(null);
    try {
      await api(`/offres/${offre.id}/relire`, { method: "POST" });
      recharger();
    } catch (probleme) {
      setErreur(message(probleme, "Relecture impossible."));
    }
  }

  async function supprimer() {
    if (!window.confirm(`Supprimer l'offre de ${offre.nom} ? Les notes saisies seront perdues.`)) return;
    try {
      await api(`/offres/${offre.id}`, { method: "DELETE" });
      recharger();
    } catch (probleme) {
      setErreur(message(probleme, "Suppression impossible."));
    }
  }

  const enCours = offre.statut_lecture === "EN_COURS";
  const IconeStatut = enCours ? Loader2 : offre.statut_lecture === "LUE" ? CheckCircle2 : offre.statut_lecture === "MANUELLE" ? FileText : offre.statut_lecture === "NON_LUE" ? XCircle : AlertTriangle;
  const ecartTotaux =
    offre.montant_base_declare != null && offre.montant_base_calcule != null && Math.abs(offre.montant_base_declare - offre.montant_base_calcule) > 1;

  return (
    <li className={`flex flex-col gap-3 rounded-lg border p-3.5 ${offre.ecartee ? "border-danger/30 bg-danger/5" : "border-bordure"}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-0 flex-[1_1_240px]">
          <Link to={`/entreprises/${offre.entreprise_id}`} className={`font-semibold text-texte ${offre.ecartee ? "line-through decoration-danger/60" : ""}`}>
            {offre.nom}
          </Link>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-attenue">
            <span>Reçue le {formaterDate(offre.recue_le)}</span>
            {offre.nom_original && <span className="max-w-64 truncate">· {offre.nom_original}</span>}
          </div>
        </div>
        <span className={`inline-flex min-h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs font-semibold ${STYLE_STATUT[offre.statut_lecture]}`}>
          <IconeStatut aria-hidden="true" className={`size-3.5 ${enCours ? "animate-spin" : ""}`} />
          {offre.statut_libelle}
        </span>
        {offre.anormalement_basse && !offre.ecartee && (
          <span className="inline-flex min-h-7 items-center gap-1.5 rounded-full border border-danger/40 bg-danger/10 px-2.5 text-xs font-semibold text-danger">
            <AlertTriangle aria-hidden="true" className="size-3.5" />
            Anormalement basse ?
          </span>
        )}
        <div className="flex flex-wrap items-center gap-1.5">
          {offre.a_un_fichier && (
            <a href={`/api/offres/${offre.id}/fichier`} target="_blank" rel="noreferrer" className={CLASSE_BOUTON_SECONDAIRE}>
              <ExternalLink aria-hidden="true" className="size-4" />
              Document
            </a>
          )}
          {offre.a_un_fichier && (
            <button type="button" onClick={() => void relire()} disabled={enCours} className={CLASSE_BOUTON_SECONDAIRE} aria-label={`Relire le document de ${offre.nom}`}>
              <RefreshCw aria-hidden="true" className="size-4" />
              Relire
            </button>
          )}
          <button
            type="button"
            onClick={() => void modifier({ ecartee: !offre.ecartee })}
            className={CLASSE_BOUTON_SECONDAIRE}
            aria-label={offre.ecartee ? `Réintégrer l'offre de ${offre.nom}` : `Écarter l'offre de ${offre.nom}`}
          >
            {offre.ecartee ? <RotateCcw aria-hidden="true" className="size-4" /> : <Ban aria-hidden="true" className="size-4" />}
            {offre.ecartee ? "Réintégrer" : "Écarter"}
          </button>
          <button
            type="button"
            onClick={() => void supprimer()}
            aria-label={`Supprimer l'offre de ${offre.nom}`}
            className="grid size-10 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger"
          >
            <Trash2 aria-hidden="true" className="size-4" />
          </button>
        </div>
      </div>

      {offre.message_lecture && !enCours && <p className="text-sm text-attenue">{offre.message_lecture}</p>}
      {enCours && <p className="text-sm text-info">Lecture du document… Un PDF scanné peut demander une minute.</p>}

      <div className="flex flex-wrap items-start gap-3">
        <ChampMontant
          id={`offre-${offre.id}-base`}
          libelle="Solution de base HT"
          valeur={offre.montant_base}
          indication={ecartTotaux ? `Total déclaré ${formaterEuros(offre.montant_base_declare)} · lignes ${formaterEuros(offre.montant_base_calcule)}` : undefined}
          surEnregistrer={(v) => modifier({ montant_base: v })}
        />
        {lot.options.map((option) => (
          <ChampMontant
            key={option.id}
            id={`offre-${offre.id}-option-${option.id}`}
            libelle={`${option.nom} HT`}
            valeur={offre.montants_options[String(option.id)] ?? null}
            surEnregistrer={(v) => modifier({ montants_options: { [option.id]: v } })}
          />
        ))}
        <Champ id={`offre-${offre.id}-delai`} libelle="Délai proposé">
          <input
            id={`offre-${offre.id}-delai`}
            value={delai}
            maxLength={255}
            placeholder="ex. 4 mois dont 1 de préparation"
            onChange={(e) => setDelai(e.target.value)}
            onBlur={() => delai !== offre.delai_propose && void modifier({ delai_propose: delai })}
            className={CLASSE_CHAMP}
          />
        </Champ>
      </div>
      {offre.ecartee && (
        <Champ id={`offre-${offre.id}-motif`} libelle="Motif de l'écart (repris dans le rapport)" large>
          <input
            id={`offre-${offre.id}-motif`}
            value={motif}
            maxLength={500}
            placeholder="ex. Offre irrégulière : DPGF non signée"
            onChange={(e) => setMotif(e.target.value)}
            onBlur={() => motif !== offre.motif_ecart && void modifier({ motif_ecart: motif })}
            className={CLASSE_CHAMP}
          />
        </Champ>
      )}
      {erreur && (
        <p role="alert" className="text-sm text-danger">
          {erreur}
        </p>
      )}
    </li>
  );
}

// --- 2. Comparatif ------------------------------------------------------------------

function Comparatif({ lot, surLot }: { lot: LotAnalyse; surLot: (lot: LotAnalyse) => void }) {
  const [donnees, setDonnees] = useState<ComparatifLot | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  // Rechargé quand une offre change (lecture terminée, montant corrigé…).
  const signature = lot.offres.map((o) => `${o.id}:${o.statut_lecture}:${o.montant_base}:${JSON.stringify(o.montants_options)}`).join("|");

  useEffect(() => {
    let actif = true;
    api<ComparatifLot>(`/lots-projet/${lot.id}/comparatif`)
      .then((c) => actif && setDonnees(c))
      .catch((p: unknown) => actif && setErreur(message(p, "Comparatif indisponible.")));
    return () => {
      actif = false;
    };
  }, [lot.id, signature]);

  async function basculerOption(optionId: number, retenue: boolean) {
    const options = retenue ? [...lot.analyse.options_retenues, optionId] : lot.analyse.options_retenues.filter((o) => o !== optionId);
    surLot({ ...lot, analyse: { ...lot.analyse, options_retenues: options } }); // case cochée sans attendre le serveur
    try {
      surLot(await api<LotAnalyse>(`/lots-projet/${lot.id}/analyse`, { method: "PATCH", body: JSON.stringify({ options_retenues: options }) }));
    } catch (probleme) {
      setErreur(message(probleme, "Enregistrement impossible."));
    }
  }

  const offres = lot.offres;
  const estimationComparee =
    (lot.estimation_base ?? 0) + lot.analyse.options_retenues.reduce((somme, o) => somme + (lot.estimation_options[String(o)] ?? 0), 0);
  const colonnes = 5 + offres.length;

  return (
    <Section id={`comparatif-${lot.id}`} numero={2} titre="Comparatif des prix">
      {lot.options.length > 0 && (
        <fieldset className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
          <legend className="mb-1 text-xs font-semibold text-attenue">PSE retenues pour comparer les offres</legend>
          {lot.options.map((option) => (
            <label key={option.id} className="flex min-h-10 items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={lot.analyse.options_retenues.includes(option.id)}
                onChange={(e) => void basculerOption(option.id, e.target.checked)}
                className="size-4 accent-[var(--color-accent)]"
              />
              {option.nom} – {option.libelle}
            </label>
          ))}
        </fieldset>
      )}
      {erreur && (
        <p role="alert" className="text-sm text-danger">
          {erreur}
        </p>
      )}
      {!donnees ? (
        <p className="text-attenue">Chargement du comparatif…</p>
      ) : (
        <div className="relative overflow-x-auto rounded-lg border border-bordure">
          <table className="w-full min-w-[720px] border-collapse text-sm">
            <caption className="sr-only">Comparatif des prix du lot {lot.code}, ouvrage par ouvrage</caption>
            <thead>
              <tr className="bg-surface-2 text-left text-xs text-attenue">
                <th scope="col" className="px-2.5 py-2 font-semibold">
                  N°
                </th>
                <th scope="col" className="min-w-56 px-2.5 py-2 font-semibold">
                  Désignation
                </th>
                <th scope="col" className="px-2.5 py-2 text-center font-semibold">
                  U
                </th>
                <th scope="col" className="px-2.5 py-2 text-right font-semibold">
                  Qté
                </th>
                <th scope="col" className="px-2.5 py-2 text-right font-semibold">
                  Estimation
                </th>
                {offres.map((o) => (
                  <th key={o.id} scope="col" className={`max-w-40 px-2.5 py-2 text-right font-semibold text-texte ${o.ecartee ? "line-through opacity-60" : ""}`}>
                    {o.nom}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {donnees.sections.map((section) => (
                <SectionComparatif key={section.titre} section={section} offres={offres} colonnes={colonnes} />
              ))}
            </tbody>
            <tfoot className="border-t-2 border-bordure-forte">
              <tr className="bg-accent/8 font-semibold">
                <th scope="row" colSpan={4} className="px-2.5 py-2 text-left">
                  Prix comparé HT{lot.analyse.options_retenues.length ? " (base + PSE retenues)" : ""}
                </th>
                <td className="px-2.5 py-2 text-right tabular-nums">{formaterEuros(estimationComparee)}</td>
                {offres.map((o) => (
                  <td key={o.id} className="px-2.5 py-2 text-right tabular-nums">
                    {formaterEuros(o.prix ?? (o.ecartee ? null : o.montant_base))}
                    {o.incomplete && o.montant_base != null && <span className="block text-xs font-normal text-accent">PSE retenue non chiffrée</span>}
                  </td>
                ))}
              </tr>
              <tr className="text-xs text-attenue">
                <th scope="row" colSpan={5} className="px-2.5 py-1.5 text-left font-normal">
                  Écart à l'estimation
                </th>
                {offres.map((o) => (
                  <td key={o.id} className={`px-2.5 py-1.5 text-right tabular-nums ${o.ecart_estimation != null && o.ecart_estimation > 0 ? "text-danger" : ""}`}>
                    {formaterEcart(o.ecart_estimation)}
                  </td>
                ))}
              </tr>
              <tr className="text-xs text-attenue">
                <th scope="row" colSpan={5} className="px-2.5 py-1.5 text-left font-normal">
                  Écart à la moyenne des offres
                </th>
                {offres.map((o) => (
                  <td key={o.id} className="px-2.5 py-1.5 text-right tabular-nums">
                    {formaterEcart(o.ecart_moyenne)}
                    {o.anormalement_basse && <span className="block font-semibold text-danger">anormalement basse ?</span>}
                  </td>
                ))}
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {donnees && Object.values(donnees.hors_dpgf).some((l) => l.length > 0) && (
        <details className="rounded-lg border border-bordure bg-fond/40 text-sm">
          <summary className="flex min-h-10 cursor-pointer items-center px-3 font-semibold">Lignes ajoutées par les entreprises (hors DPGF)</summary>
          <ul className="flex flex-col gap-2 px-3 pb-3">
            {offres
              .filter((o) => donnees.hors_dpgf[String(o.id)]?.length)
              .map((o) => (
                <li key={o.id}>
                  <span className="font-semibold">{o.nom}</span>
                  <ul className="ml-4 list-disc text-attenue">
                    {donnees.hors_dpgf[String(o.id)].map((l, i) => (
                      <li key={i}>
                        {[l.numero, l.designation].filter(Boolean).join(" ")} : {formaterEuros(l.montant)}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
          </ul>
        </details>
      )}
      <p className="text-xs text-attenue">
        <span className="text-succes">Vert</span> : prix le plus bas de la ligne · <span className="text-danger">rouge</span> : le plus élevé · « — » : ouvrage non chiffré ou
        non retrouvé dans l'offre.
      </p>
    </Section>
  );
}

function SectionComparatif({ section, offres, colonnes }: { section: ComparatifLot["sections"][number]; offres: OffreAnalyse[]; colonnes: number }) {
  const totalOffre = (o: OffreAnalyse) => (section.option_id == null ? o.montant_base : (o.montants_options[String(section.option_id)] ?? null));
  return (
    <>
      <tr className="bg-accent/12">
        <th scope="colgroup" colSpan={colonnes} className="px-2.5 py-1.5 text-left font-titre text-xs font-semibold uppercase tracking-wide text-accent">
          {section.titre}
        </th>
      </tr>
      {section.chapitres.map((chapitre) => (
        <ChapitreComparatif key={`${chapitre.numero}-${chapitre.titre}`} chapitre={chapitre} offres={offres} colonnes={colonnes} />
      ))}
      <tr className="border-t border-bordure-forte font-semibold">
        <th scope="row" colSpan={4} className="px-2.5 py-2 text-left">
          Total {section.titre} HT
        </th>
        <td className="px-2.5 py-2 text-right tabular-nums">{formaterEuros(section.estimation)}</td>
        {offres.map((o) => (
          <td key={o.id} className="px-2.5 py-2 text-right tabular-nums">
            {formaterEuros(totalOffre(o))}
          </td>
        ))}
      </tr>
    </>
  );
}

function ChapitreComparatif({
  chapitre,
  offres,
  colonnes,
}: {
  chapitre: ComparatifLot["sections"][number]["chapitres"][number];
  offres: OffreAnalyse[];
  colonnes: number;
}) {
  return (
    <>
      <tr className="border-t border-bordure bg-surface-2/60">
        <th scope="rowgroup" colSpan={colonnes} className="px-2.5 py-1.5 text-left text-xs font-semibold">
          {chapitre.numero} {chapitre.titre}
        </th>
      </tr>
      {chapitre.lignes.map((ligne) => {
        const plusieurs = ligne.minimum != null && ligne.maximum != null && ligne.minimum !== ligne.maximum;
        return (
          <tr key={ligne.poste_id} className="border-t border-bordure/60 align-top">
            <td className="px-2.5 py-1.5 text-xs text-attenue tabular-nums">{ligne.numero}</td>
            <td className="px-2.5 py-1.5">{ligne.designation}</td>
            <td className="px-2.5 py-1.5 text-center text-attenue">{ligne.unite}</td>
            <td className="px-2.5 py-1.5 text-right tabular-nums">{formaterQuantite(ligne.quantite)}</td>
            <td className="px-2.5 py-1.5 text-right tabular-nums text-attenue">
              {formaterEuros(ligne.estimation)}
              {ligne.estimation_pu != null && <span className="block text-xs">PU {formaterEuros(ligne.estimation_pu)}</span>}
            </td>
            {offres.map((o) => {
              const prix = ligne.offres[String(o.id)];
              const montant = prix?.montant ?? null;
              const couleur = plusieurs && montant === ligne.minimum ? "text-succes" : plusieurs && montant === ligne.maximum ? "text-danger" : "";
              return (
                <td key={o.id} className={`px-2.5 py-1.5 text-right tabular-nums ${couleur} ${o.ecartee ? "opacity-50" : ""}`}>
                  {formaterEuros(montant)}
                  {prix?.pu != null && <span className="block text-xs text-attenue">PU {formaterEuros(prix.pu)}</span>}
                  {prix?.quantite != null && ligne.quantite != null && prix.quantite !== ligne.quantite && (
                    <span className="block text-xs text-accent">Qté {formaterQuantite(prix.quantite)}</span>
                  )}
                </td>
              );
            })}
          </tr>
        );
      })}
    </>
  );
}

// --- 3. Notation ----------------------------------------------------------------------

function Notation({ lot, projetId, surLot }: { lot: LotAnalyse; projetId: number; surLot: (lot: LotAnalyse) => void }) {
  const [erreur, setErreur] = useState<string | null>(null);
  const [commentaires, setCommentaires] = useState<Set<number>>(new Set());
  const { analyse, criteres } = lot;
  const notees = lot.offres
    .filter((o) => !o.ecartee && !o.incomplete && o.prix != null && o.prix > 0)
    .sort((a, b) => (a.rang ?? 999) - (b.rang ?? 999));
  const sansPrix = lot.offres.filter((o) => !o.ecartee && (o.montant_base == null || o.montant_base <= 0));
  const incompletes = lot.offres.filter((o) => !o.ecartee && o.montant_base != null && o.montant_base > 0 && o.incomplete);
  const ecartees = lot.offres.filter((o) => o.ecartee);
  const sommePonderations = criteres.reduce((s, c) => s + c.ponderation, 0);

  async function parametrer(donnees: Record<string, unknown>) {
    setErreur(null);
    try {
      surLot(await api<LotAnalyse>(`/lots-projet/${lot.id}/analyse`, { method: "PATCH", body: JSON.stringify(donnees) }));
    } catch (probleme) {
      setErreur(message(probleme, "Enregistrement impossible."));
    }
  }

  async function noter(offre: OffreAnalyse, critere: string, saisie: { note?: number | null; commentaire?: string }) {
    setErreur(null);
    const actuelle = offre.notes[critere] ?? { note: null, commentaire: "" };
    try {
      surLot(
        await api<LotAnalyse>(`/offres/${offre.id}`, {
          method: "PATCH",
          body: JSON.stringify({ notes: { [critere]: { note: actuelle.note, commentaire: actuelle.commentaire, ...saisie } } }),
        }),
      );
    } catch (probleme) {
      setErreur(message(probleme, "Note non enregistrée."));
    }
  }

  async function commenter(offre: OffreAnalyse, commentaire: string) {
    try {
      surLot(await api<LotAnalyse>(`/offres/${offre.id}`, { method: "PATCH", body: JSON.stringify({ commentaire }) }));
    } catch (probleme) {
      setErreur(message(probleme, "Commentaire non enregistré."));
    }
  }

  const basculerCommentaires = (id: number) =>
    setCommentaires((c) => {
      const suivant = new Set(c);
      if (suivant.has(id)) suivant.delete(id);
      else suivant.add(id);
      return suivant;
    });

  return (
    <Section id={`notation-${lot.id}`} numero={3} titre="Notation et classement">
      <div className="flex flex-wrap items-end gap-3">
        <Champ id={`methode-${lot.id}`} libelle="Note de prix" large>
          <select
            id={`methode-${lot.id}`}
            value={analyse.methode_prix}
            onChange={(e) => void parametrer({ methode_prix: e.target.value as MethodePrix })}
            className={CLASSE_CHAMP}
          >
            <option value="PROPORTIONNELLE">Proportionnelle : note max × prix le plus bas ÷ prix de l'offre</option>
            <option value="LINEAIRE">Linéaire : note max × (1 − écart au prix le plus bas)</option>
          </select>
        </Champ>
        <Champ id={`bareme-${lot.id}`} libelle="Notes sur">
          <select id={`bareme-${lot.id}`} value={analyse.bareme} onChange={(e) => void parametrer({ bareme: Number(e.target.value) })} className={CLASSE_CHAMP}>
            {[5, 10, 20, 100].map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </Champ>
        <Champ id={`seuil-${lot.id}`} libelle="Anormalement basse si sous la moyenne ou l'estimation de">
          <select
            id={`seuil-${lot.id}`}
            value={analyse.seuil_anormal}
            onChange={(e) => void parametrer({ seuil_anormal: Number(e.target.value) })}
            className={CLASSE_CHAMP}
          >
            {[10, 15, 20, 25, 30, 40].map((s) => (
              <option key={s} value={s}>
                {s} %
              </option>
            ))}
          </select>
        </Champ>
      </div>
      {criteres.length === 0 ? (
        <p className="rounded-lg border border-accent/40 bg-accent/8 px-3 py-2 text-sm">
          Aucun critère de jugement : renseignez-les dans les <Link to={`/projets/${projetId}`}>paramètres de la consultation</Link> (ils figurent aussi dans le RC).
        </p>
      ) : (
        <p className="text-sm text-attenue">
          Critères du RC : {criteres.map((c) => `${c.libelle} ${c.ponderation.toLocaleString("fr-FR")} %`).join(" · ")}.
          {!criteres.some((c) => c.prix) && " Aucun critère « Prix » : la note de prix n'est pas calculée."}
          {sommePonderations !== 100 && <span className="text-accent"> La somme des pondérations fait {sommePonderations.toLocaleString("fr-FR")} % au lieu de 100 %.</span>}
        </p>
      )}
      {erreur && (
        <p role="alert" className="text-sm text-danger">
          {erreur}
        </p>
      )}
      {notees.length > 0 && criteres.length > 0 && (
        <div className="relative overflow-x-auto rounded-lg border border-bordure">
          <table className="w-full min-w-[640px] border-collapse text-sm">
            <caption className="sr-only">Notes par critère et classement du lot {lot.code}</caption>
            <thead>
              <tr className="bg-surface-2 text-left text-xs text-attenue">
                <th scope="col" className="px-2.5 py-2 font-semibold">
                  Rang
                </th>
                <th scope="col" className="px-2.5 py-2 font-semibold">
                  Offre
                </th>
                {criteres.map((c) => (
                  <th key={c.libelle} scope="col" className="max-w-36 px-2.5 py-2 text-center font-semibold">
                    {c.libelle}
                    <span className="block font-normal">
                      {c.ponderation.toLocaleString("fr-FR")} % · /{analyse.bareme}
                    </span>
                  </th>
                ))}
                <th scope="col" className="px-2.5 py-2 text-right font-semibold">
                  Total /100
                </th>
                <th scope="col" className="px-2.5 py-2">
                  <span className="sr-only">Commentaires</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {notees.map((offre) => (
                <LigneNotation
                  key={offre.id}
                  offre={offre}
                  lot={lot}
                  ouverte={commentaires.has(offre.id)}
                  surBascule={() => basculerCommentaires(offre.id)}
                  surNote={noter}
                  surCommentaire={commenter}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {sansPrix.length > 0 && (
        <p className="text-sm text-accent">Sans montant, donc non classée(s) : {sansPrix.map((o) => o.nom).join(", ")}. Saisissez le montant dans « Offres reçues ».</p>
      )}
      {incompletes.length > 0 && (
        <p className="text-sm text-accent">
          PSE retenue non chiffrée, offre non classée : {incompletes.map((o) => o.nom).join(", ")}. Saisissez le montant de la PSE dans « Offres reçues » (après
          demande de précision à l'entreprise) ou écartez l'offre.
        </p>
      )}
      {ecartees.length > 0 && (
        <p className="text-sm text-attenue">
          Écartée(s) : {ecartees.map((o) => `${o.nom}${o.motif_ecart ? ` (${o.motif_ecart})` : ""}`).join(" ; ")}.
        </p>
      )}
    </Section>
  );
}

function ChampNote({ id, libelle, valeur, bareme, surEnregistrer }: { id: string; libelle: string; valeur: number | null; bareme: number; surEnregistrer: (v: number | null) => void }) {
  const [texte, setTexte] = useState(valeur == null ? "" : String(valeur).replace(".", ","));
  const [invalide, setInvalide] = useState(false);
  useEffect(() => setTexte(valeur == null ? "" : String(valeur).replace(".", ",")), [valeur]);
  function valider() {
    const propre = texte.trim().replace(",", ".");
    const note = propre === "" ? null : Number(propre);
    if (note != null && (Number.isNaN(note) || note < 0 || note > bareme)) {
      setInvalide(true);
      return;
    }
    setInvalide(false);
    if (note !== valeur) surEnregistrer(note);
  }
  return (
    <input
      id={id}
      aria-label={libelle}
      aria-invalid={invalide}
      title={invalide ? `Note entre 0 et ${bareme}` : undefined}
      inputMode="decimal"
      autoComplete="off"
      value={texte}
      placeholder="—"
      onChange={(e) => setTexte(e.target.value)}
      onBlur={valider}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
      className={`min-h-10 w-16 rounded-lg border bg-fond px-2 text-center tabular-nums text-texte ${invalide ? "border-danger" : "border-bordure-forte"}`}
    />
  );
}

function LigneNotation({
  offre,
  lot,
  ouverte,
  surBascule,
  surNote,
  surCommentaire,
}: {
  offre: OffreAnalyse;
  lot: LotAnalyse;
  ouverte: boolean;
  surBascule: () => void;
  surNote: (offre: OffreAnalyse, critere: string, saisie: { note?: number | null; commentaire?: string }) => Promise<void>;
  surCommentaire: (offre: OffreAnalyse, commentaire: string) => Promise<void>;
}) {
  const manuels = lot.criteres.filter((c) => !c.prix);
  return (
    <>
      <tr className={`border-t border-bordure align-middle ${offre.rang === 1 ? "bg-succes/5" : ""}`}>
        <td className="px-2.5 py-2 font-titre text-base font-bold tabular-nums">
          {offre.rang ? (
            <span className={`inline-flex items-center gap-1 ${offre.rang === 1 ? "text-succes" : ""}`}>
              {offre.rang === 1 && <Trophy aria-hidden="true" className="size-4" />}
              {offre.rang}
            </span>
          ) : (
            "—"
          )}
        </td>
        <th scope="row" className="px-2.5 py-2 text-left font-semibold">
          {offre.nom}
          <span className="block text-xs font-normal text-attenue">
            {formaterEuros(offre.prix)}
            {offre.anormalement_basse && <span className="text-danger"> · anormalement basse ?</span>}
          </span>
        </th>
        {lot.criteres.map((c) => (
          <td key={c.libelle} className="px-2.5 py-2 text-center">
            {c.prix ? (
              <span className="tabular-nums" title="Calculée automatiquement">
                {formaterNote(offre.notes_calculees[c.libelle])}
              </span>
            ) : (
              <ChampNote
                id={`note-${offre.id}-${c.libelle}`}
                libelle={`${c.libelle} – ${offre.nom}`}
                valeur={offre.notes[c.libelle]?.note ?? null}
                bareme={lot.analyse.bareme}
                surEnregistrer={(note) => void surNote(offre, c.libelle, { note })}
              />
            )}
          </td>
        ))}
        <td className="px-2.5 py-2 text-right font-titre text-base font-bold tabular-nums">
          {formaterNote(offre.total)}
          {!offre.notation_complete && <span className="block text-xs font-normal text-accent">notes à compléter</span>}
        </td>
        <td className="px-1.5 py-2 text-right">
          <button
            type="button"
            onClick={surBascule}
            aria-expanded={ouverte}
            aria-label={`Commentaires sur l'offre de ${offre.nom}`}
            className={`grid size-10 place-items-center rounded-lg hover:bg-surface-2 ${ouverte ? "text-accent" : "text-attenue"}`}
          >
            <MessageSquareText aria-hidden="true" className="size-4" />
          </button>
        </td>
      </tr>
      {ouverte && (
        <tr className="bg-fond/40">
          <td colSpan={lot.criteres.length + 4} className="px-2.5 py-3">
            <div className="flex flex-col gap-3">
              {manuels.map((c) => (
                <ZoneCommentaire
                  key={c.libelle}
                  id={`commentaire-${offre.id}-${c.libelle}`}
                  libelle={`${c.libelle} : justification de la note (reprise dans le rapport)`}
                  valeur={offre.notes[c.libelle]?.commentaire ?? ""}
                  surEnregistrer={(commentaire) => void surNote(offre, c.libelle, { commentaire })}
                />
              ))}
              <ZoneCommentaire
                id={`commentaire-${offre.id}-general`}
                libelle="Observations générales sur l'offre"
                valeur={offre.commentaire}
                surEnregistrer={(commentaire) => void surCommentaire(offre, commentaire)}
              />
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function ZoneCommentaire({ id, libelle, valeur, surEnregistrer }: { id: string; libelle: string; valeur: string; surEnregistrer: (v: string) => void }) {
  const [texte, setTexte] = useState(valeur);
  useEffect(() => setTexte(valeur), [valeur]);
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-xs font-semibold text-attenue">
        {libelle}
      </label>
      <textarea
        id={id}
        rows={2}
        value={texte}
        maxLength={4000}
        onChange={(e) => setTexte(e.target.value)}
        onBlur={() => texte !== valeur && surEnregistrer(texte)}
        className={`${CLASSE_CHAMP} py-2`}
      />
    </div>
  );
}

// --- 4. Proposition d'attribution -------------------------------------------------------

function Attribution({ lot, projetId, tauxTva, surLot }: { lot: LotAnalyse; projetId: number; tauxTva: number; surLot: (lot: LotAnalyse) => void }) {
  const { analyse } = lot;
  const [observations, setObservations] = useState(analyse.observations);
  const [resultat, setResultat] = useState<{ ok: boolean; texte: string } | null>(null);
  const [envoi, setEnvoi] = useState(false);
  useEffect(() => setObservations(analyse.observations), [analyse.observations]);

  const classees = useMemo(() => lot.offres.filter((o) => o.rang != null).sort((a, b) => (a.rang ?? 0) - (b.rang ?? 0)), [lot.offres]);
  const premiere = classees[0] ?? null;
  const proposee = lot.offres.find((o) => o.id === analyse.attributaire_id) ?? premiere;
  const horsClassement = proposee != null && premiere != null && proposee.id !== premiere.id;

  async function parametrer(donnees: Record<string, unknown>) {
    setResultat(null);
    try {
      surLot(await api<LotAnalyse>(`/lots-projet/${lot.id}/analyse`, { method: "PATCH", body: JSON.stringify(donnees) }));
    } catch (probleme) {
      setResultat({ ok: false, texte: message(probleme, "Enregistrement impossible.") });
    }
  }

  async function valider() {
    if (!proposee) return;
    if (!window.confirm(`Proposer ${proposee.nom} pour le lot ${lot.code} ? Dans l'annuaire, l'entreprise passera à « Retenue » et les autres à « Non retenue ».`)) return;
    setEnvoi(true);
    setResultat(null);
    try {
      surLot(await api<LotAnalyse>(`/lots-projet/${lot.id}/analyse/valider`, { method: "POST" }));
      setResultat({ ok: true, texte: "Proposition validée : statuts des entreprises mis à jour dans l'annuaire." });
    } catch (probleme) {
      setResultat({ ok: false, texte: message(probleme, "Validation impossible.") });
    } finally {
      setEnvoi(false);
    }
  }

  const montant = proposee?.prix ?? null;
  const base = `/api/projets/${projetId}`;
  return (
    <Section
      id={`attribution-${lot.id}`}
      numero={4}
      titre="Proposition d'attribution"
      actions={
        <div className="flex flex-wrap gap-2">
          <a href={`${base}/rapport-act/docx?lot_id=${lot.id}`} className={CLASSE_BOUTON_SECONDAIRE}>
            <FileText aria-hidden="true" className="size-4 text-accent" />
            Rapport du lot (Word)
          </a>
          <a href={`${base}/rapport-act/pdf?lot_id=${lot.id}`} className={CLASSE_BOUTON_SECONDAIRE}>
            <Download aria-hidden="true" className="size-4 text-accent" />
            PDF
          </a>
          <a href={`${base}/comparatif-offres.xlsx?lot_id=${lot.id}`} className={CLASSE_BOUTON_SECONDAIRE}>
            <FileSpreadsheet aria-hidden="true" className="size-4 text-accent" />
            Excel
          </a>
        </div>
      }
    >
      {!premiere ? (
        <p className="text-attenue">Les offres seront classées dès qu'elles auront un montant et que les critères seront définis.</p>
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-3">
            <Champ id={`attributaire-${lot.id}`} libelle="Offre proposée" large>
              <select
                id={`attributaire-${lot.id}`}
                value={analyse.attributaire_id ?? ""}
                onChange={(e) => void parametrer({ attributaire_id: e.target.value ? Number(e.target.value) : null })}
                className={CLASSE_CHAMP}
              >
                <option value="">Offre la mieux classée ({premiere.nom})</option>
                {classees.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.rang}. {o.nom} – {formaterNote(o.total)}/100 – {formaterEuros(o.prix)} HT
                  </option>
                ))}
              </select>
            </Champ>
            <dl className="grid flex-[2_1_320px] grid-cols-3 gap-2 text-sm">
              {[
                ["Montant HT", montant],
                [`TVA ${tauxTva.toLocaleString("fr-FR")} %`, montant == null ? null : Math.round(montant * tauxTva) / 100],
                ["Montant TTC", montant == null ? null : Math.round(montant * (100 + tauxTva)) / 100],
              ].map(([libelle, valeur]) => (
                <div key={String(libelle)} className="rounded-lg border border-bordure bg-fond/40 px-3 py-2">
                  <dt className="text-xs text-attenue">{libelle}</dt>
                  <dd className="font-titre font-semibold tabular-nums">{formaterEuros(valeur as number | null)}</dd>
                </div>
              ))}
            </dl>
          </div>
          {horsClassement && <p className="text-sm text-accent">L'offre proposée n'est pas la mieux classée : justifiez ce choix dans les observations.</p>}
          {proposee?.anormalement_basse && (
            <p className="text-sm text-danger">
              Offre possiblement anormalement basse : demandez des précisions écrites à l'entreprise avant de la retenir (articles R2152-3 et suivants du code de la commande
              publique).
            </p>
          )}
          {proposee?.incomplete && <p className="text-sm text-accent">Une PSE retenue n'est pas chiffrée dans cette offre.</p>}
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`observations-${lot.id}`} className="text-xs font-semibold text-attenue">
              Observations (reprises dans le rapport)
            </label>
            <textarea
              id={`observations-${lot.id}`}
              rows={3}
              value={observations}
              onChange={(e) => setObservations(e.target.value)}
              onBlur={() => observations !== analyse.observations && void parametrer({ observations })}
              placeholder="ex. Mise au point à prévoir sur le phasage ; confirmation des délais d'approvisionnement des menuiseries."
              className={`${CLASSE_CHAMP} py-2`}
            />
          </div>
          <div className="flex flex-wrap items-center justify-end gap-3">
            {analyse.validee_le && !resultat && <span className="text-sm text-succes">Proposition validée le {formaterDate(analyse.validee_le)}.</span>}
            {resultat && (
              <span role={resultat.ok ? "status" : "alert"} className={`text-sm ${resultat.ok ? "text-succes" : "text-danger"}`}>
                {resultat.texte}
              </span>
            )}
            <button
              type="button"
              onClick={() => void valider()}
              disabled={envoi || !proposee}
              className="flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4.5 font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-50"
            >
              <CheckCircle2 aria-hidden="true" className="size-4" />
              {analyse.validee_le ? "Valider de nouveau" : "Valider la proposition"}
            </button>
          </div>
        </>
      )}
    </Section>
  );
}
