/** Fiche d'un document : historique complet des indices, visas, avis, accusés de lecture,
 * nouvel indice ; pour le cabinet, visa de synthèse, modification et annulation. */
import { CheckCircle2, Download, FileText, Paperclip, PenLine, RotateCcw, Stamp, Upload, XCircle } from "lucide-react";
import { useState, type FormEvent } from "react";

import { CLASSE_CHAMP, Champ } from "../components/Filtres";
import { formaterTaille } from "../lib/format";
import type { ClientGed } from "./client";
import {
  aujourdhuiIso,
  CLASSE_BOUTON,
  CLASSE_BOUTON_PRINCIPAL,
  formaterDateHeure,
  formaterJour,
  FORMAT_INDICE,
  identifiantDepot,
  indiceSuivant,
  messageErreur,
  normaliserIndice,
  STYLE_STATUT,
  STYLE_VISA,
} from "./outils";
import type { DocumentGed, DroitsGed, Referentiels, VersionGed } from "./types";

interface Proprietes {
  document: DocumentGed;
  client: ClientGed;
  droits: DroitsGed;
  referentiels: Referentiels;
  surMaj: (document: DocumentGed) => void;
}

export default function FicheDocument({ document: d, client, droits, referentiels, surMaj }: Proprietes) {
  const [formulaire, setFormulaire] = useState<"indice" | "modifier" | null>(null);
  // Envoi d'un indice en cours : le formulaire ne peut pas être refermé (l'envoi n'est pas annulable).
  const [envoiIndice, setEnvoiIndice] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const clos = droits.statut_espace === "CLOS";
  const categorie = referentiels.categories.find((c) => c.code === d.categorie);

  async function annuler() {
    if (!client.modifierDocument) return;
    const motif = window.prompt(`Annuler ${d.reference} – ${d.titre} ? Le document reste consultable, barré, avec le motif.\n\nMotif de l'annulation :`);
    if (motif === null) return;
    try {
      surMaj(await client.modifierDocument(d.id, { annule: true, motif_annulation: motif }));
    } catch (p) {
      setErreur(messageErreur(p, "Annulation impossible."));
    }
  }

  async function retablir() {
    if (!client.modifierDocument) return;
    try {
      surMaj(await client.modifierDocument(d.id, { annule: false }));
    } catch (p) {
      setErreur(messageErreur(p, "Rétablissement impossible."));
    }
  }

  return (
    <div className="flex flex-col gap-4 border-t border-bordure px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-attenue">Référence</dt>
          <dd className="font-mono">{d.reference}</dd>
          {d.reference_emetteur && (
            <>
              <dt className="text-attenue">N° de l'émetteur</dt>
              <dd className="font-mono">{d.reference_emetteur}</dd>
            </>
          )}
          <dt className="text-attenue">Classement</dt>
          <dd>
            {d.zone === "COMMUN" ? "Commun à tous" : d.zone === "MOE" ? "Maîtrise d'œuvre (réservé)" : `Lot ${d.lot?.code} – ${d.lot?.intitule}`} ·{" "}
            {d.categorie_libelle}
            {categorie?.visa ? " · soumis au visa" : ""}
          </dd>
          <dt className="text-attenue">Créé par</dt>
          <dd>
            {d.auteur}, le {formaterDateHeure(d.cree_le)}
          </dd>
          {d.annule && (
            <>
              <dt className="text-danger">Annulé</dt>
              <dd className="text-danger">{d.motif_annulation || "sans motif indiqué"}</dd>
            </>
          )}
        </dl>
        <div className="flex flex-wrap gap-2">
          {d.peut_ajouter_indice && !d.annule && !clos && (
            <button
              type="button"
              onClick={() => setFormulaire(formulaire === "indice" ? null : "indice")}
              disabled={envoiIndice}
              className={CLASSE_BOUTON_PRINCIPAL}
            >
              <Upload aria-hidden="true" className="size-4" />
              Nouvel indice
            </button>
          )}
          {client.modifierDocument && !clos && (
            <>
              <button
                type="button"
                onClick={() => setFormulaire(formulaire === "modifier" ? null : "modifier")}
                disabled={envoiIndice}
                className={CLASSE_BOUTON}
              >
                <PenLine aria-hidden="true" className="size-4" />
                Modifier
              </button>
              {d.annule ? (
                <button type="button" onClick={() => void retablir()} className={CLASSE_BOUTON}>
                  <RotateCcw aria-hidden="true" className="size-4" />
                  Rétablir
                </button>
              ) : (
                <button type="button" onClick={() => void annuler()} className={`${CLASSE_BOUTON} text-danger`}>
                  <XCircle aria-hidden="true" className="size-4" />
                  Annuler
                </button>
              )}
            </>
          )}
        </div>
      </div>
      {erreur && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {erreur}
        </p>
      )}
      {formulaire === "indice" && (
        <FormulaireIndice
          document={d}
          client={client}
          droits={droits}
          referentiels={referentiels}
          surMaj={surMaj}
          surEnvoi={setEnvoiIndice}
          surFermer={() => setFormulaire(null)}
        />
      )}
      {formulaire === "modifier" && (
        <FormulaireModification document={d} client={client} referentiels={referentiels} surMaj={surMaj} surFermer={() => setFormulaire(null)} />
      )}

      <h4 className="font-titre font-semibold">Historique des indices ({d.versions.length})</h4>
      <ol className="flex flex-col gap-3">
        {d.versions.map((v) => (
          <CarteVersion key={v.id} version={v} document={d} client={client} droits={droits} referentiels={referentiels} surMaj={surMaj} />
        ))}
      </ol>
    </div>
  );
}

function CarteVersion({ version: v, document: d, client, droits, referentiels, surMaj }: { version: VersionGed } & Proprietes) {
  const [erreur, setErreur] = useState<string | null>(null);
  const [lecture, setLecture] = useState(false);
  const [avisTransmis, setAvisTransmis] = useState(false);
  const clos = droits.statut_espace === "CLOS";

  async function accuser() {
    setLecture(true);
    setErreur(null);
    try {
      surMaj(await client.accuserLecture(v.id));
    } catch (p) {
      setErreur(messageErreur(p, "Accusé de lecture impossible."));
    } finally {
      setLecture(false);
    }
  }

  return (
    <li
      className={`flex flex-col gap-3 rounded-lg border px-4 py-3 ${v.statut === "REMPLACEE" ? "border-bordure bg-fond/40" : "border-bordure-forte bg-fond"}`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="font-titre text-lg font-bold">Ind. {v.indice}</span>
        <span className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${STYLE_STATUT[v.statut]}`}>{v.statut_libelle}</span>
        <span className="text-xs text-attenue">{v.diffusion_libelle}</span>
        {v.visa && <span className={`text-sm font-semibold ${STYLE_VISA[v.visa] ?? ""}`}>{v.visa_libelle}</span>}
        {v.visa === "EN_ATTENTE" && v.echeance_visa && (
          <span className={`text-xs ${v.visa_en_retard ? "font-bold text-danger" : "text-attenue"}`}>
            échéance {formaterJour(v.echeance_visa)}
            {v.jours_restants !== null && !v.visa_en_retard ? ` (${v.jours_restants} j)` : v.visa_en_retard ? " – en retard" : ""}
          </span>
        )}
      </div>
      <p className="text-sm text-attenue">
        Déposé par {v.deposee_par} le {formaterDateHeure(v.deposee_le)}
        {v.date_indice ? ` · indice daté du ${formaterJour(v.date_indice)}` : ""}
        {v.objet ? (
          <>
            {" "}
            · <span className="text-texte">{v.objet}</span>
          </>
        ) : null}
      </p>
      {v.indice_force && <p className="text-xs text-accent">Indice accepté hors séquence : {v.indice_force}</p>}

      <div className="flex flex-wrap gap-2">
        {v.fichier_archive ? (
          <span className="text-sm text-attenue">Fichier archivé (purgé de l'application)</span>
        ) : (
          <a href={client.urlVersion(v.id, "fichier")} target="_blank" rel="noopener" className={CLASSE_BOUTON} title={v.nom_telechargement}>
            <Download aria-hidden="true" className="size-4" />
            {v.statut === "REMPLACEE" ? "Ancien indice" : "Ouvrir"} ({formaterTaille(v.taille)})
          </a>
        )}
        {v.sources.map((s) => (
          <a key={s.id} href={client.urlSource(s.id)} className={CLASSE_BOUTON} title="Fichier source (modifiable)">
            <Paperclip aria-hidden="true" className="size-4" />
            {s.nom_original}
          </a>
        ))}
        {v.visa_fichier && (
          <a href={client.urlVersion(v.id, "annote")} target="_blank" rel="noopener" className={CLASSE_BOUTON}>
            <Stamp aria-hidden="true" className="size-4" />
            Document annoté du visa
          </a>
        )}
        {v.fiche_visa && (
          <a href={client.urlVersion(v.id, "fiche")} target="_blank" rel="noopener" className={CLASSE_BOUTON}>
            <FileText aria-hidden="true" className="size-4" />
            Fiche de visa
          </a>
        )}
      </div>

      {(v.visa_commentaire || v.vise_par) && v.visa !== "EN_ATTENTE" && (
        <div className="rounded-lg border border-bordure bg-surface px-3 py-2 text-sm">
          <p className="font-semibold">
            {v.visa_libelle}
            {v.vise_par ? ` – ${v.vise_par}` : ""}
            {v.vise_le ? `, le ${formaterDateHeure(v.vise_le)}` : ""}
          </p>
          {v.visa_commentaire && <p className="whitespace-pre-line text-attenue">{v.visa_commentaire}</p>}
          {v.nouvel_indice_attendu && <p className="mt-1 font-semibold text-accent">Un nouvel indice est attendu.</p>}
        </div>
      )}

      {v.avis.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-semibold text-attenue">Avis de la maîtrise d'œuvre et des contrôleurs</p>
          <ul className="flex flex-col gap-1.5">
            {v.avis.map((a) => (
              <li key={a.id} className="rounded-lg border border-bordure bg-surface px-3 py-2 text-sm">
                <span className="font-semibold">
                  {a.role_libelle} ({a.auteur}) : {a.avis_libelle}
                </span>
                <span className="text-xs text-attenue"> – {formaterDateHeure(a.date)}</span>
                {a.observations && <p className="whitespace-pre-line text-attenue">{a.observations}</p>}
                {a.fichier && (
                  <a href={client.urlAvis(a.id)} target="_blank" rel="noopener" className="text-sm">
                    Document joint à l'avis
                  </a>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {v.lecture_requise && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {droits.cabinet ? (
            v.accuses.length ? (
              <span className="text-succes">Lu par : {v.accuses.map((a) => `${a.intervenant} (${a.lu_par}, ${formaterDateHeure(a.lu_le)})`).join(" ; ")}</span>
            ) : (
              <span className="text-accent">Accusé de lecture attendu de l'entreprise.</span>
            )
          ) : v.lu_le ? (
            <span className="inline-flex items-center gap-1.5 text-succes">
              <CheckCircle2 aria-hidden="true" className="size-4" />
              Lecture confirmée le {formaterDateHeure(v.lu_le)}
            </span>
          ) : (
            v.peut_accuser_lecture && (
              <button type="button" onClick={() => void accuser()} disabled={lecture} className={CLASSE_BOUTON_PRINCIPAL}>
                <CheckCircle2 aria-hidden="true" className="size-4" />
                J'ai pris connaissance de ce document
              </button>
            )
          )}
        </div>
      )}

      {erreur && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {erreur}
        </p>
      )}
      {droits.peut_viser && client.viser && v.visa === "EN_ATTENTE" && !d.annule && !clos && (
        <FormulaireVisa version={v} document={d} client={client} referentiels={referentiels} surMaj={surMaj} />
      )}
      {avisTransmis && (
        <p role="status" className="text-sm text-succes">
          Avis transmis à la maîtrise d'œuvre.
        </p>
      )}
      {v.peut_donner_avis && !clos && (
        <FormulaireAvis version={v} client={client} referentiels={referentiels} surMaj={surMaj} surTransmis={() => setAvisTransmis(true)} />
      )}
    </li>
  );
}

function BarreProgression({ fraction }: { fraction: number | null }) {
  if (fraction === null) return null;
  return (
    <div
      className="h-2 w-full overflow-hidden rounded-full bg-surface-2"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(fraction * 100)}
    >
      <div className="h-full bg-accent transition-[width]" style={{ width: `${Math.round(fraction * 100)}%` }} />
    </div>
  );
}

function FormulaireIndice({
  document: d,
  client,
  droits,
  referentiels,
  surMaj,
  surEnvoi,
  surFermer,
}: { surEnvoi: (enCours: boolean) => void; surFermer: () => void } & Omit<Proprietes, "document"> & { document: DocumentGed }) {
  const precedent = d.versions[0]?.indice;
  const categorie = referentiels.categories.find((c) => c.code === d.categorie);
  const pdfExige = !droits.choix_diffusion && Boolean(categorie?.visa);
  const [fichier, setFichier] = useState<File | null>(null);
  const [sources, setSources] = useState<File[]>([]);
  const [indice, setIndice] = useState("");
  const [objet, setObjet] = useState("");
  const [dateIndice, setDateIndice] = useState("");
  const [diffusion, setDiffusion] = useState("");
  const [forcer, setForcer] = useState("");
  const [progression, setProgression] = useState<number | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const suggestion = indiceSuivant(precedent);
  const indiceSaisi = normaliserIndice(indice);

  async function envoyer(evenement: FormEvent) {
    evenement.preventDefault();
    if (!fichier) return;
    if (indiceSaisi && !FORMAT_INDICE.test(indiceSaisi)) {
      setErreur("Indice invalide : une à trois lettres (A, B… AA) ou un nombre (0, 1, 2…).");
      return;
    }
    const donnees = new FormData();
    donnees.append("fichier", fichier);
    for (const s of sources) donnees.append("sources", s);
    donnees.append("indice", indiceSaisi);
    donnees.append("objet", objet.trim());
    if (dateIndice) donnees.append("date_indice", dateIndice);
    if (diffusion) donnees.append("diffusion", diffusion);
    if (forcer.trim()) donnees.append("forcer", forcer.trim());
    donnees.append("depot", identifiantDepot());
    setErreur(null);
    setProgression(0);
    surEnvoi(true);
    try {
      surMaj(await client.ajouterIndice(d.id, donnees, setProgression));
      surFermer();
    } catch (p) {
      setErreur(messageErreur(p, "Dépôt impossible."));
      setProgression(null);
    } finally {
      surEnvoi(false);
    }
  }

  return (
    <form onSubmit={envoyer} className="flex flex-col gap-3 rounded-lg border border-accent/40 bg-accent/5 p-4">
      <p className="font-semibold">
        Nouvel indice de {d.reference}
        {precedent ? ` (dernier indice : ${precedent} ; suivant proposé : ${suggestion})` : ""}
      </p>
      <div className="flex flex-wrap gap-3">
        <Champ id={`indice-fichier-${d.id}`} libelle={pdfExige ? "Document (PDF)" : "Document"} large>
          <input
            id={`indice-fichier-${d.id}`}
            type="file"
            required
            accept={pdfExige ? ".pdf" : undefined}
            onChange={(e) => setFichier(e.target.files?.[0] ?? null)}
            className={`${CLASSE_CHAMP} py-2`}
          />
        </Champ>
        <Champ id={`indice-sources-${d.id}`} libelle="Fichiers sources (DWG…), facultatif" large>
          <input
            id={`indice-sources-${d.id}`}
            type="file"
            multiple
            onChange={(e) => setSources(Array.from(e.target.files ?? []))}
            className={`${CLASSE_CHAMP} py-2`}
          />
        </Champ>
      </div>
      <div className="flex flex-wrap gap-3">
        <Champ id={`indice-valeur-${d.id}`} libelle="Indice">
          <input
            id={`indice-valeur-${d.id}`}
            value={indice}
            onChange={(e) => setIndice(e.target.value)}
            placeholder={suggestion}
            maxLength={8}
            className={CLASSE_CHAMP}
          />
        </Champ>
        <Champ id={`indice-date-${d.id}`} libelle="Date de l'indice (cartouche)">
          <input
            id={`indice-date-${d.id}`}
            type="date"
            max={aujourdhuiIso()}
            value={dateIndice}
            onChange={(e) => setDateIndice(e.target.value)}
            className={CLASSE_CHAMP}
          />
        </Champ>
        {droits.choix_diffusion && (
          <Champ id={`indice-diffusion-${d.id}`} libelle="Diffusion">
            <select id={`indice-diffusion-${d.id}`} value={diffusion} onChange={(e) => setDiffusion(e.target.value)} className={CLASSE_CHAMP}>
              <option value="">Comme l'indice précédent</option>
              {referentiels.diffusions.map((x) => (
                <option key={x.code} value={x.code}>
                  {x.libelle}
                </option>
              ))}
            </select>
          </Champ>
        )}
        <Champ id={`indice-objet-${d.id}`} libelle="Objet de la modification" large>
          <input
            id={`indice-objet-${d.id}`}
            value={objet}
            onChange={(e) => setObjet(e.target.value)}
            maxLength={500}
            placeholder="Ce qui change par rapport à l'indice précédent"
            className={CLASSE_CHAMP}
          />
        </Champ>
      </div>
      {client.cabinet && (
        <Champ id={`indice-forcer-${d.id}`} libelle="Motif, seulement si l'indice ne suit pas le précédent (indice hors séquence)" large>
          <input id={`indice-forcer-${d.id}`} value={forcer} onChange={(e) => setForcer(e.target.value)} maxLength={300} className={CLASSE_CHAMP} />
        </Champ>
      )}
      <BarreProgression fraction={progression} />
      {erreur && (
        <p role="alert" className="text-danger">
          {erreur}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" onClick={surFermer} disabled={progression !== null} className={CLASSE_BOUTON}>
          Annuler
        </button>
        <button type="submit" disabled={!fichier || progression !== null} className={CLASSE_BOUTON_PRINCIPAL}>
          <Upload aria-hidden="true" className="size-4" />
          Déposer l'indice {indiceSaisi || suggestion}
        </button>
      </div>
      <p className="text-xs text-attenue">Taille maximale : {referentiels.taille_max_mo} Mo par fichier. Un récépissé de dépôt vous est envoyé par courriel.</p>
    </form>
  );
}

function FormulaireModification({
  document: d,
  client,
  referentiels,
  surMaj,
  surFermer,
}: {
  document: DocumentGed;
  client: ClientGed;
  referentiels: Referentiels;
  surMaj: (d: DocumentGed) => void;
  surFermer: () => void;
}) {
  const [titre, setTitre] = useState(d.titre);
  const [reference, setReference] = useState(d.reference);
  const [referenceEmetteur, setReferenceEmetteur] = useState(d.reference_emetteur);
  const [categorie, setCategorie] = useState(d.categorie);
  const [erreur, setErreur] = useState<string | null>(null);

  async function enregistrer(evenement: FormEvent) {
    evenement.preventDefault();
    if (!client.modifierDocument) return;
    try {
      surMaj(await client.modifierDocument(d.id, { titre, reference, reference_emetteur: referenceEmetteur, categorie }));
      surFermer();
    } catch (p) {
      setErreur(messageErreur(p, "Modification impossible."));
    }
  }

  return (
    <form onSubmit={enregistrer} className="flex flex-col gap-3 rounded-lg border border-bordure-forte bg-fond p-4">
      <div className="flex flex-wrap gap-3">
        <Champ id={`modif-titre-${d.id}`} libelle="Titre" large>
          <input id={`modif-titre-${d.id}`} value={titre} onChange={(e) => setTitre(e.target.value)} required maxLength={255} className={CLASSE_CHAMP} />
        </Champ>
        <Champ id={`modif-ref-${d.id}`} libelle="Référence">
          <input id={`modif-ref-${d.id}`} value={reference} onChange={(e) => setReference(e.target.value)} required maxLength={60} className={CLASSE_CHAMP} />
        </Champ>
        <Champ id={`modif-emetteur-${d.id}`} libelle="N° de l'émetteur">
          <input
            id={`modif-emetteur-${d.id}`}
            value={referenceEmetteur}
            onChange={(e) => setReferenceEmetteur(e.target.value)}
            maxLength={80}
            className={CLASSE_CHAMP}
          />
        </Champ>
        <Champ id={`modif-cat-${d.id}`} libelle="Catégorie" large>
          <select id={`modif-cat-${d.id}`} value={categorie} onChange={(e) => setCategorie(e.target.value)} className={CLASSE_CHAMP}>
            {referentiels.categories
              // Pièce confidentielle (OS, avenants, devis, situations, DC4) : jamais dans le Commun.
              .filter((c) => d.zone !== "COMMUN" || !c.confidentielle || c.code === d.categorie)
              .map((c) => (
                <option key={c.code} value={c.code}>
                  {c.libelle}
                </option>
              ))}
          </select>
        </Champ>
      </div>
      {erreur && (
        <p role="alert" className="text-danger">
          {erreur}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <button type="button" onClick={surFermer} className={CLASSE_BOUTON}>
          Annuler
        </button>
        <button type="submit" className={CLASSE_BOUTON_PRINCIPAL}>
          Enregistrer
        </button>
      </div>
    </form>
  );
}

function FormulaireVisa({
  version: v,
  document: d,
  client,
  referentiels,
  surMaj,
}: {
  version: VersionGed;
  document: DocumentGed;
  client: ClientGed;
  referentiels: Referentiels;
  surMaj: (d: DocumentGed) => void;
}) {
  const [statut, setStatut] = useState("");
  const [commentaire, setCommentaire] = useState("");
  const [fichier, setFichier] = useState<File | null>(null);
  const [nouvelIndice, setNouvelIndice] = useState<boolean | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const indiceAttendu = statut === "REF" ? true : (nouvelIndice ?? statut === "VAO");

  async function viser(evenement: FormEvent) {
    evenement.preventDefault();
    if (!client.viser || !statut) return;
    if ((statut === "VAO" || statut === "REF") && !commentaire.trim() && !fichier) {
      setErreur("Indiquez les observations ou joignez le document annoté.");
      return;
    }
    const donnees = new FormData();
    donnees.append("statut", statut);
    donnees.append("commentaire", commentaire.trim());
    if (fichier) donnees.append("fichier", fichier);
    donnees.append("nouvel_indice_attendu", String(indiceAttendu));
    setEnvoi(true);
    setErreur(null);
    try {
      surMaj(await client.viser(v.id, donnees));
    } catch (p) {
      setErreur(messageErreur(p, "Visa impossible."));
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <form onSubmit={viser} className="flex flex-col gap-3 rounded-lg border border-info/40 bg-info/5 p-4">
      <p className="font-semibold">
        Visa de synthèse de l'indice {v.indice} ({d.reference})
      </p>
      <fieldset className="flex flex-wrap gap-2">
        <legend className="sr-only">Avis de visa</legend>
        {referentiels.visas
          .filter((x) => x.code !== "REMPLACE")
          .map((x) => (
            <label
              key={x.code}
              className={`flex min-h-10 cursor-pointer items-center gap-2 rounded-lg border px-3 text-sm ${statut === x.code ? "border-accent bg-accent/10 font-semibold" : "border-bordure-forte"}`}
            >
              <input
                type="radio"
                name={`visa-${v.id}`}
                value={x.code}
                checked={statut === x.code}
                onChange={() => setStatut(x.code)}
                className="accent-accent"
              />
              <span className={STYLE_VISA[x.code]}>{x.libelle}</span>
            </label>
          ))}
      </fieldset>
      <Champ id={`visa-commentaire-${v.id}`} libelle="Observations (reprises sur la fiche de visa envoyée à l'entreprise)" large>
        <textarea
          id={`visa-commentaire-${v.id}`}
          rows={3}
          value={commentaire}
          onChange={(e) => setCommentaire(e.target.value)}
          maxLength={4000}
          className={`${CLASSE_CHAMP} py-2`}
        />
      </Champ>
      <div className="flex flex-wrap items-end gap-3">
        <Champ id={`visa-fichier-${v.id}`} libelle="Document annoté (facultatif)" large>
          <input id={`visa-fichier-${v.id}`} type="file" onChange={(e) => setFichier(e.target.files?.[0] ?? null)} className={`${CLASSE_CHAMP} py-2`} />
        </Champ>
        {statut && statut !== "REF" && (
          <label className="flex min-h-11 items-center gap-2">
            <input type="checkbox" checked={indiceAttendu} onChange={(e) => setNouvelIndice(e.target.checked)} className="size-4 accent-accent" />
            Nouvel indice attendu
          </label>
        )}
      </div>
      {erreur && (
        <p role="alert" className="text-danger">
          {erreur}
        </p>
      )}
      <div className="flex justify-end">
        <button type="submit" disabled={!statut || envoi} className={CLASSE_BOUTON_PRINCIPAL}>
          <Stamp aria-hidden="true" className="size-4" />
          {envoi ? "Visa en cours…" : "Émettre le visa"}
        </button>
      </div>
    </form>
  );
}

function FormulaireAvis({
  version: v,
  client,
  referentiels,
  surMaj,
  surTransmis,
}: {
  version: VersionGed;
  client: ClientGed;
  referentiels: Referentiels;
  surMaj: (d: DocumentGed) => void;
  surTransmis: () => void;
}) {
  const [avis, setAvis] = useState("");
  const [observations, setObservations] = useState("");
  const [fichier, setFichier] = useState<File | null>(null);
  const [cleFichier, setCleFichier] = useState(0);
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  async function envoyer(evenement: FormEvent) {
    evenement.preventDefault();
    if (!avis) return;
    const donnees = new FormData();
    donnees.append("avis", avis);
    donnees.append("observations", observations.trim());
    if (fichier) donnees.append("fichier", fichier);
    setEnvoi(true);
    setErreur(null);
    try {
      surMaj(await client.donnerAvis(v.id, donnees));
      // Formulaire vidé : un second envoi créerait un second avis.
      setAvis("");
      setObservations("");
      setFichier(null);
      setCleFichier((c) => c + 1);
      surTransmis();
    } catch (p) {
      setErreur(messageErreur(p, "Avis impossible."));
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <form onSubmit={envoyer} className="flex flex-col gap-3 rounded-lg border border-info/40 bg-info/5 p-4">
      <p className="font-semibold">Votre avis sur l'indice {v.indice} (transmis à la maîtrise d'œuvre pour le visa)</p>
      <div className="flex flex-wrap gap-3">
        <Champ id={`avis-${v.id}`} libelle="Avis">
          <select id={`avis-${v.id}`} value={avis} onChange={(e) => setAvis(e.target.value)} required className={CLASSE_CHAMP}>
            <option value="">Choisir…</option>
            {referentiels.avis.map((x) => (
              <option key={x.code} value={x.code}>
                {x.libelle}
              </option>
            ))}
          </select>
        </Champ>
        <Champ id={`avis-fichier-${v.id}`} libelle="Document joint (facultatif)" large>
          <input
            key={cleFichier}
            id={`avis-fichier-${v.id}`}
            type="file"
            onChange={(e) => setFichier(e.target.files?.[0] ?? null)}
            className={`${CLASSE_CHAMP} py-2`}
          />
        </Champ>
      </div>
      <Champ id={`avis-obs-${v.id}`} libelle="Observations" large>
        <textarea
          id={`avis-obs-${v.id}`}
          rows={3}
          value={observations}
          onChange={(e) => setObservations(e.target.value)}
          maxLength={4000}
          className={`${CLASSE_CHAMP} py-2`}
        />
      </Champ>
      {erreur && (
        <p role="alert" className="text-danger">
          {erreur}
        </p>
      )}
      <div className="flex justify-end">
        <button type="submit" disabled={!avis || envoi} className={CLASSE_BOUTON_PRINCIPAL}>
          Transmettre l'avis
        </button>
      </div>
    </form>
  );
}
