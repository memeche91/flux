import { AlertTriangle, CheckCircle2, Download, FileArchive, FilePlus2, FolderTree, Mail, Send, Trash2, UserPlus, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { api, televerser } from "../api/client";
import {
  CATEGORIES_PIECES_JOINTES,
  STATUTS_CONSULTATION,
  type CategoriePieceJointe,
  type ConsultationDCE,
  type DossierDCE,
  type EnvoiDCE,
  type EtatDCE,
  type Projet,
  type StatutConsultation,
} from "../api/types";
import EnTetePage from "../components/EnTetePage";
import { CLASSE_CHAMP, Champ } from "../components/Filtres";
import { formaterDate, formaterTaille, pluriel } from "../lib/format";

type LotProjetCourt = Projet["lots"][number];

const lienMail = (envoi: { destinataires: string; objet: string; message: string }) =>
  `mailto:${envoi.destinataires.replace(/\s/g, "")}?subject=${encodeURIComponent(envoi.objet)}&body=${encodeURIComponent(envoi.message)}`;

export default function DCE() {
  const { projetId } = useParams();
  const [projet, setProjet] = useState<Projet | null>(null);
  const [etat, setEtat] = useState<EtatDCE | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(() => {
    api<EtatDCE>(`/projets/${projetId}/dce`)
      .then(setEtat)
      .catch((p: unknown) => setErreur(p instanceof Error ? p.message : "DCE indisponible."));
  }, [projetId]);

  useEffect(() => {
    api<Projet>(`/projets/${projetId}`)
      .then(setProjet)
      .catch((p: unknown) => setErreur(p instanceof Error ? p.message : "Projet introuvable."));
    charger();
  }, [projetId, charger]);

  // Suivi des dossiers en préparation et des envois en cours.
  const enCours = Boolean(etat?.dossiers.some((d) => d.statut === "EN_COURS") || etat?.envois.some((e) => e.statut === "PREPARATION"));
  useEffect(() => {
    if (!enCours) return;
    const minuteur = window.setInterval(charger, 2500);
    return () => window.clearInterval(minuteur);
  }, [enCours, charger]);

  if (erreur && !etat) {
    return (
      <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-danger">
        {erreur}
      </p>
    );
  }
  if (!projet || !etat) return <p className="text-attenue">Chargement du DCE…</p>;
  const public_ = etat.type_marche === "PUBLIC";

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
        / <span className="text-texte">DCE</span>
      </nav>
      <EnTetePage
        surtitre={`Étape 2 · ${public_ ? "Marché public" : "Marché privé"}`}
        titre="Dossier de consultation des entreprises"
        sousTitre={
          public_
            ? "Le DCE complet est transmis au maître d'ouvrage, qui le publie sur son profil d'acheteur. Vous pouvez aussi inviter des entreprises à le consulter."
            : "Chaque entreprise consultée reçoit un dossier limité à ses lots, avec une lettre de consultation."
        }
      />
      <Controle etat={etat} />
      <DocumentsJoints projetId={projet.id} lots={projet.lots} etat={etat} surChangement={charger} />
      <Generation projetId={projet.id} etat={etat} surChangement={charger} />
      {public_ && <TransmissionMoa projetId={projet.id} etat={etat} surChangement={charger} />}
      <Entreprises projetId={projet.id} lots={projet.lots} etat={etat} surChangement={charger} />
      <Envois etat={etat} surChangement={charger} />
    </>
  );
}

function Section({ numero, titre, children, actions }: { numero: number; titre: string; children: React.ReactNode; actions?: React.ReactNode }) {
  const id = `section-dce-${numero}`;
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 rounded-xl border border-bordure bg-surface p-5">
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

function Controle({ etat }: { etat: EtatDCE }) {
  const manques = etat.controle.filter((p) => p.niveau !== "OK").length;
  return (
    <Section numero={1} titre="Contrôle du dossier">
      <p className="text-sm text-attenue">
        {manques === 0 ? "Tout est prêt." : `${pluriel(manques, "point")} à vérifier avant de diffuser le DCE. Vous pouvez quand même le générer.`}
      </p>
      <ul className="flex flex-col gap-1.5">
        {etat.controle.map((point, indice) => {
          const Icone = point.niveau === "OK" ? CheckCircle2 : point.niveau === "MANQUE" ? XCircle : AlertTriangle;
          const couleur = point.niveau === "OK" ? "text-succes" : point.niveau === "MANQUE" ? "text-danger" : "text-accent";
          return (
            <li key={indice} className="flex items-start gap-2.5 text-sm">
              <Icone aria-hidden="true" className={`mt-0.5 size-4 shrink-0 ${couleur}`} />
              <span className="sr-only">{point.niveau === "OK" ? "Prêt :" : point.niveau === "MANQUE" ? "Manquant :" : "À vérifier :"}</span>
              {point.lien ? (
                <Link to={point.lien} className="text-texte">
                  {point.texte}
                </Link>
              ) : (
                <span>{point.texte}</span>
              )}
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

function DocumentsJoints({ projetId, lots, etat, surChangement }: { projetId: number; lots: LotProjetCourt[]; etat: EtatDCE; surChangement: () => void }) {
  const [categorie, setCategorie] = useState<CategoriePieceJointe>("PLANS");
  const [lotId, setLotId] = useState("");
  const [envois, setEnvois] = useState<{ nom: string; progression: number; erreur?: string }[]>([]);
  const [survol, setSurvol] = useState(false);

  async function deposer(fichiers: File[]) {
    for (const fichier of fichiers) {
      setEnvois((e) => [{ nom: fichier.name, progression: 0 }, ...e]);
      const donnees = new FormData();
      donnees.append("fichier", fichier);
      donnees.append("categorie", categorie);
      if (lotId) donnees.append("lot_id", lotId);
      try {
        await televerser(`/projets/${projetId}/dce/pieces-jointes`, donnees, (p) =>
          setEnvois((e) => e.map((x) => (x.nom === fichier.name ? { ...x, progression: p } : x))),
        );
        setEnvois((e) => e.filter((x) => x.nom !== fichier.name));
        surChangement();
      } catch (probleme) {
        setEnvois((e) => e.map((x) => (x.nom === fichier.name ? { ...x, erreur: probleme instanceof Error ? probleme.message : "Envoi impossible." } : x)));
      }
    }
  }

  async function supprimer(id: number, titre: string) {
    if (!window.confirm(`Retirer « ${titre} » du DCE ?`)) return;
    await api(`/dce/pieces-jointes/${id}`, { method: "DELETE" }).catch(() => undefined);
    surChangement();
  }

  return (
    <Section numero={2} titre="Plans et documents à joindre">
      <p className="text-sm text-attenue">Plans, études de sol, diagnostics, PGC… Sans limite de nombre. Un document rattaché à un lot est rangé dans le dossier de ce lot.</p>
      <div className="flex flex-wrap items-end gap-3">
        <Champ id="jointe-categorie" libelle="Type de document">
          <select id="jointe-categorie" value={categorie} onChange={(e) => setCategorie(e.target.value as CategoriePieceJointe)} className={CLASSE_CHAMP}>
            {Object.entries(CATEGORIES_PIECES_JOINTES).map(([code, libelle]) => (
              <option key={code} value={code}>
                {libelle}
              </option>
            ))}
          </select>
        </Champ>
        <Champ id="jointe-lot" libelle="Rattacher à">
          <select id="jointe-lot" value={lotId} onChange={(e) => setLotId(e.target.value)} className={CLASSE_CHAMP}>
            <option value="">Tous les lots (commun)</option>
            {lots.map((lot) => (
              <option key={lot.id} value={lot.id}>
                Lot {lot.code} – {lot.intitule}
              </option>
            ))}
          </select>
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
          void deposer(Array.from(e.dataTransfer.files));
        }}
        className={`flex min-h-24 cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed px-4 py-5 text-center focus-within:ring-2 focus-within:ring-accent ${
          survol ? "border-accent bg-accent/10" : "border-bordure-forte hover:bg-surface-2"
        }`}
      >
        <FilePlus2 aria-hidden="true" className="size-6 text-accent" />
        <span className="font-semibold">Déposez vos fichiers ici ou cliquez pour les choisir</span>
        <span className="text-xs text-attenue">PDF, DWG, DXF, images, Word, Excel… · {CATEGORIES_PIECES_JOINTES[categorie]}</span>
        <input type="file" multiple className="sr-only" onChange={(e) => void deposer(Array.from(e.target.files ?? []))} />
      </label>
      {envois.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm" aria-live="polite">
          {envois.map((e) => (
            <li key={e.nom} className={e.erreur ? "text-danger" : "text-attenue"}>
              {e.nom} : {e.erreur ?? `${Math.round(e.progression * 100)} %`}
            </li>
          ))}
        </ul>
      )}
      {etat.pieces_jointes.length > 0 && (
        <ul className="flex flex-col divide-y divide-bordure rounded-lg border border-bordure">
          {etat.pieces_jointes.map((j) => (
            <li key={j.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
              <span className="min-w-0 flex-[1_1_220px]">
                <span className="block truncate font-semibold">{j.titre}</span>
                <span className="text-xs text-attenue">
                  {j.categorie_libelle} · {j.lot ?? "Tous les lots"} · {formaterTaille(j.taille)}
                </span>
              </span>
              <button
                type="button"
                onClick={() => void supprimer(j.id, j.titre)}
                aria-label={`Retirer ${j.titre}`}
                className="grid size-10 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger"
              >
                <Trash2 aria-hidden="true" className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function Generation({ projetId, etat, surChangement }: { projetId: number; etat: EtatDCE; surChangement: () => void }) {
  const [indice, setIndice] = useState(etat.indice || "A");
  const [avecWord, setAvecWord] = useState(false);
  const [apercu, setApercu] = useState<{ racine: string; fichiers: string[] } | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const complets = etat.dossiers.filter((d) => !d.entreprise);
  const enPreparation = complets.some((d) => d.statut === "EN_COURS");

  async function generer() {
    setErreur(null);
    try {
      await api(`/projets/${projetId}/dce/dossiers`, { method: "POST", body: JSON.stringify({ indice, avec_word: avecWord }) });
      surChangement();
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Génération impossible.");
    }
  }

  async function voirApercu(ouvert: boolean) {
    if (!ouvert) return;
    try {
      setApercu(await api(`/projets/${projetId}/dce/apercu?indice=${encodeURIComponent(indice)}&avec_word=${avecWord}`));
    } catch {
      setApercu(null);
    }
  }

  async function supprimer(dossier: DossierDCE) {
    if (!window.confirm(`Supprimer le DCE indice ${dossier.indice} du ${formaterDate(dossier.cree_le)} ?`)) return;
    await api(`/dce/dossiers/${dossier.id}`, { method: "DELETE" }).catch((p: unknown) => setErreur(p instanceof Error ? p.message : "Suppression impossible."));
    surChangement();
  }

  return (
    <Section numero={3} titre="Générer le DCE (.zip)">
      <div className="flex flex-wrap items-end gap-3">
        <Champ id="dce-indice" libelle="Indice du DCE">
          <input id="dce-indice" value={indice} maxLength={10} onChange={(e) => setIndice(e.target.value.toUpperCase())} className={CLASSE_CHAMP} />
        </Champ>
        <label className="flex min-h-11 flex-[2_1_280px] items-center gap-2 text-sm">
          <input type="checkbox" checked={avecWord} onChange={(e) => setAvecWord(e.target.checked)} className="size-4 accent-[var(--color-accent)]" />
          Joindre aussi les versions Word du RC, du CCAP et des CCTP (les actes d'engagement et les DPGF sont toujours modifiables)
        </label>
        <button
          type="button"
          onClick={() => void generer()}
          disabled={enPreparation || !indice.trim()}
          className="flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4.5 font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-50"
        >
          <FileArchive aria-hidden="true" className="size-4" />
          {enPreparation ? "Préparation en cours…" : "Générer le DCE"}
        </button>
      </div>
      <details onToggle={(e) => void voirApercu((e.target as HTMLDetailsElement).open)} className="rounded-lg border border-bordure bg-fond/40">
        <summary className="flex min-h-10 cursor-pointer items-center gap-2 px-3 text-sm font-semibold">
          <FolderTree aria-hidden="true" className="size-4 text-accent" />
          Aperçu de l'arborescence
        </summary>
        {apercu && <Arborescence racine={apercu.racine} chemins={apercu.fichiers} />}
      </details>
      {erreur && (
        <p role="alert" className="text-danger">
          {erreur}
        </p>
      )}
      {complets.length > 0 && (
        <ul className="flex flex-col gap-2">
          {complets.map((d) => (
            <li key={d.id} className="flex flex-col gap-2 rounded-lg border border-bordure px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="min-w-0 flex-[1_1_240px]">
                  <span className="font-semibold">DCE indice {d.indice}</span>
                  <span className="block text-xs text-attenue">
                    {formaterDate(d.cree_le)}
                    {d.statut === "PRET" && ` · ${pluriel(d.nb_fichiers, "fichier")} · ${formaterTaille(d.taille)}`}
                    {d.avec_word && " · versions Word incluses"}
                  </span>
                </span>
                {d.statut === "EN_COURS" && <span className="text-sm text-accent">Préparation…</span>}
                {d.statut === "ERREUR" && <span className="text-sm text-danger">{d.message}</span>}
                {d.statut === "PRET" && (
                  <a
                    href={`/api/dce/dossiers/${d.id}/telecharger`}
                    className="flex min-h-10 items-center gap-2 rounded-lg border border-bordure-forte px-3 text-sm font-semibold text-texte no-underline hover:bg-surface-2"
                  >
                    <Download aria-hidden="true" className="size-4" />
                    Télécharger
                  </a>
                )}
                {d.statut !== "EN_COURS" && (
                  <button
                    type="button"
                    onClick={() => void supprimer(d)}
                    aria-label={`Supprimer le DCE indice ${d.indice}`}
                    className="grid size-10 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger"
                  >
                    <Trash2 aria-hidden="true" className="size-4" />
                  </button>
                )}
              </div>
              {d.statut === "PRET" && (
                <details className="text-sm">
                  <summary className="cursor-pointer text-xs text-attenue">Contenu du dossier</summary>
                  <Arborescence racine="" chemins={d.contenu.map((f) => f.chemin)} />
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

/** Arborescence de dossiers et fichiers (chemins séparés par « / »). */
function Arborescence({ racine, chemins }: { racine: string; chemins: string[] }) {
  const lignes = useMemo(() => {
    const vus = new Set<string>();
    const resultat: { niveau: number; nom: string; dossier: boolean }[] = [];
    for (const chemin of chemins) {
      const morceaux = (racine ? `${racine}/${chemin}` : chemin).split("/");
      morceaux.forEach((nom, indice) => {
        const cle = morceaux.slice(0, indice + 1).join("/");
        if (vus.has(cle)) return;
        vus.add(cle);
        resultat.push({ niveau: indice, nom, dossier: indice < morceaux.length - 1 });
      });
    }
    return resultat;
  }, [racine, chemins]);
  return (
    <ul className="max-h-80 overflow-auto px-3 py-2 font-mono text-xs leading-relaxed">
      {lignes.map((ligne, i) => (
        <li key={i} style={{ paddingLeft: `${ligne.niveau * 1.1}rem` }} className={ligne.dossier ? "font-semibold text-accent" : "text-texte"}>
          {ligne.dossier ? "▸ " : ""}
          {ligne.nom}
        </li>
      ))}
    </ul>
  );
}

function TransmissionMoa({ projetId, etat, surChangement }: { projetId: number; etat: EtatDCE; surChangement: () => void }) {
  const prets = etat.dossiers.filter((d) => !d.entreprise && d.statut === "PRET");
  const [dossierId, setDossierId] = useState<number | null>(null);
  const dossier = prets.find((d) => d.id === dossierId) ?? prets[0];
  const [destinataires, setDestinataires] = useState("");
  const [objet, setObjet] = useState("");
  const [message, setMessage] = useState("");
  const [resultat, setResultat] = useState<{ ok: boolean; texte: string } | null>(null);
  const [envoi, setEnvoi] = useState(false);

  useEffect(() => {
    if (!dossier) return;
    api<{ moa: { objet: string; message: string } }>(`/projets/${projetId}/dce/messages?indice=${encodeURIComponent(dossier.indice)}`)
      .then((m) => {
        setObjet(m.moa.objet);
        setMessage(m.moa.message);
      })
      .catch(() => undefined);
  }, [projetId, dossier?.indice, dossier]);

  async function transmettre(evenement: FormEvent) {
    evenement.preventDefault();
    if (!dossier) return;
    setEnvoi(true);
    setResultat(null);
    try {
      const envoiCree = await api<EnvoiDCE>(`/projets/${projetId}/dce/envois/moa`, {
        method: "POST",
        body: JSON.stringify({ dossier_id: dossier.id, destinataires, objet, message, mode: "EMAIL" }),
      });
      setResultat(
        envoiCree.statut === "ENVOYE"
          ? { ok: true, texte: `DCE envoyé à ${envoiCree.destinataires}${envoiCree.piece_jointe ? " (dossier joint)" : ""}.` }
          : { ok: envoiCree.statut === "A_ENVOYER", texte: envoiCree.erreur || "Message préparé : envoyez-le depuis votre messagerie (voir les envois ci-dessous)." },
      );
      surChangement();
    } catch (probleme) {
      setResultat({ ok: false, texte: probleme instanceof Error ? probleme.message : "Envoi impossible." });
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <Section numero={4} titre="Transmission au maître d'ouvrage">
      {!dossier ? (
        <p className="text-sm text-attenue">Générez d'abord le DCE (étape 3).</p>
      ) : (
        <form onSubmit={transmettre} className="flex flex-col gap-3">
          {!etat.email_actif && (
            <p className="rounded-lg bg-info/10 px-3 py-2 text-sm text-info">
              Messagerie non configurée : l'application prépare le message, vous l'envoyez depuis votre messagerie avec le DCE téléchargé.
            </p>
          )}
          <div className="flex flex-wrap gap-3">
            <Champ id="moa-dossier" libelle="DCE à transmettre">
              <select id="moa-dossier" value={dossier.id} onChange={(e) => setDossierId(Number(e.target.value))} className={CLASSE_CHAMP}>
                {prets.map((d) => (
                  <option key={d.id} value={d.id}>
                    Indice {d.indice} du {formaterDate(d.cree_le)} ({formaterTaille(d.taille)})
                  </option>
                ))}
              </select>
            </Champ>
            <Champ id="moa-destinataires" libelle="E-mail du maître d'ouvrage" large>
              <input id="moa-destinataires" required value={destinataires} onChange={(e) => setDestinataires(e.target.value)} placeholder="prenom.nom@collectivite.fr" className={CLASSE_CHAMP} />
            </Champ>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="moa-objet" className="text-xs font-semibold text-attenue">
              Objet
            </label>
            <input id="moa-objet" required value={objet} onChange={(e) => setObjet(e.target.value)} className={CLASSE_CHAMP} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="moa-message" className="text-xs font-semibold text-attenue">
              Message
            </label>
            <textarea id="moa-message" rows={9} required value={message} onChange={(e) => setMessage(e.target.value)} className={`${CLASSE_CHAMP} py-2.5`} />
          </div>
          {etat.email_actif && dossier.taille > etat.piece_jointe_max_mo * 1048576 && (
            <p className="text-sm text-accent">
              Le dossier ({formaterTaille(dossier.taille)}) dépasse {etat.piece_jointe_max_mo} Mo : il ne sera pas joint. Transmettez-le par FranceTransfert ou un service équivalent.
            </p>
          )}
          <div className="flex flex-wrap items-center justify-end gap-3">
            {resultat && (
              <span role={resultat.ok ? "status" : "alert"} className={resultat.ok ? "text-succes" : "text-danger"}>
                {resultat.texte}
              </span>
            )}
            <button type="submit" disabled={envoi} className="flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4.5 font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-50">
              <Send aria-hidden="true" className="size-4" />
              {etat.email_actif ? "Envoyer au maître d'ouvrage" : "Préparer le message"}
            </button>
          </div>
        </form>
      )}
    </Section>
  );
}

function Entreprises({ projetId, lots, etat, surChangement }: { projetId: number; lots: LotProjetCourt[]; etat: EtatDCE; surChangement: () => void }) {
  const public_ = etat.type_marche === "PUBLIC";
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const [objet, setObjet] = useState("");
  const [message, setMessage] = useState("");
  const [indice, setIndice] = useState(etat.indice || "A");
  const [avecWord, setAvecWord] = useState(false);
  const [resultat, setResultat] = useState<{ ok: boolean; texte: string } | null>(null);
  const [envoi, setEnvoi] = useState(false);

  useEffect(() => {
    api<{ entreprise: { objet: string; message: string } }>(`/projets/${projetId}/dce/messages`)
      .then((m) => {
        setObjet(m.entreprise.objet);
        setMessage(m.entreprise.message);
      })
      .catch(() => undefined);
  }, [projetId]);

  const entreprises = useMemo(() => {
    const parId = new Map<number, { id: number; nom: string; email: string; lots: string[]; aConsulter: boolean }>();
    for (const c of etat.consultations) {
      const lot = lots.find((l) => l.id === c.lot_id);
      const fiche = parId.get(c.entreprise_id) ?? { id: c.entreprise_id, nom: c.entreprise, email: c.email, lots: [], aConsulter: false };
      fiche.lots.push(lot ? lot.code : "?");
      fiche.aConsulter ||= c.statut === "A_CONSULTER";
      parId.set(c.entreprise_id, fiche);
    }
    return [...parId.values()].sort((a, b) => a.nom.localeCompare(b.nom));
  }, [etat.consultations, lots]);

  async function envoyer(evenement: FormEvent) {
    evenement.preventDefault();
    if (selection.size === 0) return;
    setEnvoi(true);
    setResultat(null);
    try {
      const envois = await api<EnvoiDCE[]>(`/projets/${projetId}/dce/envois/entreprises`, {
        method: "POST",
        body: JSON.stringify({ entreprise_ids: [...selection], objet, message, indice, avec_word: avecWord, mode: "EMAIL" }),
      });
      setResultat({
        ok: true,
        texte: etat.email_actif
          ? `${pluriel(envois.length, "envoi")} en préparation : suivez-les ci-dessous.`
          : `${pluriel(envois.length, "message")} en préparation : vous les enverrez depuis votre messagerie (ci-dessous).`,
      });
      setSelection(new Set());
      surChangement();
    } catch (probleme) {
      setResultat({ ok: false, texte: probleme instanceof Error ? probleme.message : "Envoi impossible." });
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <Section numero={public_ ? 5 : 4} titre={public_ ? "Inviter des entreprises (facultatif)" : "Entreprises consultées"}>
      <p className="text-sm text-attenue">
        {public_
          ? "Les entreprises invitées reçoivent le lien du profil d'acheteur : en marché public, le DCE et les offres passent par la plateforme."
          : "Choisissez les entreprises de l'annuaire pour chaque lot, puis envoyez-leur leur dossier."}
      </p>
      <ul className="flex flex-col gap-3">
        {lots.map((lot) => (
          <ConsultationsLot key={lot.id} projetId={projetId} lot={lot} consultations={etat.consultations.filter((c) => c.lot_id === lot.id)} surChangement={surChangement} />
        ))}
      </ul>

      {entreprises.length > 0 && (
        <form onSubmit={envoyer} className="flex flex-col gap-3 border-t border-bordure pt-4">
          <h3 className="font-semibold">{public_ ? "Envoyer l'invitation" : "Envoyer le DCE"}</h3>
          <fieldset className="flex min-w-0 flex-col gap-1.5">
            <legend className="mb-1 text-xs font-semibold text-attenue">Destinataires</legend>
            {entreprises.map((e) => (
              <label key={e.id} className="flex min-h-10 min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 text-sm">
                <input
                  type="checkbox"
                  checked={selection.has(e.id)}
                  onChange={(ev) => {
                    const suivante = new Set(selection);
                    if (ev.target.checked) suivante.add(e.id);
                    else suivante.delete(e.id);
                    setSelection(suivante);
                  }}
                  className="size-4 accent-[var(--color-accent)]"
                />
                <span className="font-semibold">{e.nom}</span>
                <span className="min-w-0 break-all text-attenue">
                  lot{e.lots.length > 1 ? "s" : ""} {e.lots.join(", ")} · {e.email || <span className="text-danger">pas d'e-mail dans l'annuaire</span>}
                </span>
                {!e.aConsulter && <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-attenue">déjà consultée</span>}
              </label>
            ))}
          </fieldset>
          {!public_ && (
            <div className="flex flex-wrap items-end gap-3">
              <Champ id="entreprises-indice" libelle="Indice du DCE">
                <input id="entreprises-indice" value={indice} maxLength={10} onChange={(e) => setIndice(e.target.value.toUpperCase())} className={CLASSE_CHAMP} />
              </Champ>
              <label className="flex min-h-11 flex-[2_1_260px] items-center gap-2 text-sm">
                <input type="checkbox" checked={avecWord} onChange={(e) => setAvecWord(e.target.checked)} className="size-4 accent-[var(--color-accent)]" />
                Joindre aussi les versions Word des pièces écrites
              </label>
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <label htmlFor="entreprises-objet" className="text-xs font-semibold text-attenue">
              Objet
            </label>
            <input id="entreprises-objet" required value={objet} onChange={(e) => setObjet(e.target.value)} className={CLASSE_CHAMP} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="entreprises-message" className="text-xs font-semibold text-attenue">
              Message ({"[entreprise]"} et {"[lots]"} sont remplacés pour chaque destinataire{public_ ? "" : " ; il sert aussi de lettre de consultation dans le dossier"})
            </label>
            <textarea id="entreprises-message" rows={10} required value={message} onChange={(e) => setMessage(e.target.value)} className={`${CLASSE_CHAMP} py-2.5`} />
          </div>
          <div className="flex flex-wrap items-center justify-end gap-3">
            {resultat && (
              <span role={resultat.ok ? "status" : "alert"} className={resultat.ok ? "text-succes" : "text-danger"}>
                {resultat.texte}
              </span>
            )}
            <button
              type="submit"
              disabled={envoi || selection.size === 0}
              className="flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4.5 font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-50"
            >
              <Send aria-hidden="true" className="size-4" />
              {etat.email_actif ? `Envoyer à ${pluriel(selection.size, "entreprise")}` : `Préparer pour ${pluriel(selection.size, "entreprise")}`}
            </button>
          </div>
        </form>
      )}
    </Section>
  );
}

function ConsultationsLot({ projetId, lot, consultations, surChangement }: { projetId: number; lot: LotProjetCourt; consultations: ConsultationDCE[]; surChangement: () => void }) {
  const [ouvert, setOuvert] = useState(false);
  const [suggestions, setSuggestions] = useState<{ id: number; raison_sociale: string; ville: string; email: string }[] | null>(null);
  const [choix, setChoix] = useState<Set<number>>(new Set());
  const [erreur, setErreur] = useState<string | null>(null);

  async function ouvrir() {
    const suivant = !ouvert;
    setOuvert(suivant);
    setChoix(new Set());
    if (suivant) setSuggestions(await api<typeof suggestions>(`/projets/${projetId}/dce/suggestions?lot_id=${lot.id}`).catch(() => []));
  }

  async function ajouter() {
    setErreur(null);
    try {
      await api(`/projets/${projetId}/dce/consultations`, { method: "POST", body: JSON.stringify({ lot_id: lot.id, entreprise_ids: [...choix] }) });
      setOuvert(false);
      surChangement();
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Ajout impossible.");
    }
  }

  async function changerStatut(c: ConsultationDCE, statut: StatutConsultation) {
    await api(`/dce/consultations/${c.id}`, { method: "PATCH", body: JSON.stringify({ statut }) }).catch(() => undefined);
    surChangement();
  }

  async function retirer(c: ConsultationDCE) {
    try {
      await api(`/dce/consultations/${c.id}`, { method: "DELETE" });
      surChangement();
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Retrait impossible.");
    }
  }

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-bordure p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">
          Lot {lot.code} – {lot.intitule}
        </h3>
        <button
          type="button"
          onClick={() => void ouvrir()}
          aria-expanded={ouvert}
          aria-label={`Ajouter des entreprises au lot ${lot.code}`}
          className="flex min-h-10 items-center gap-1.5 rounded-lg border border-bordure-forte px-3 text-sm hover:bg-surface-2"
        >
          <UserPlus aria-hidden="true" className="size-4" />
          Ajouter des entreprises
        </button>
      </div>
      {consultations.length === 0 && !ouvert && <p className="text-sm text-attenue">Aucune entreprise pour ce lot.</p>}
      {consultations.length > 0 && (
        <ul className="flex flex-col gap-1">
          {consultations.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <Link to={`/entreprises/${c.entreprise_id}`} className="min-w-0 flex-[1_1_200px] font-semibold text-texte">
                {c.entreprise}
              </Link>
              <label className="sr-only" htmlFor={`statut-${c.id}`}>
                Statut de {c.entreprise}
              </label>
              <select
                id={`statut-${c.id}`}
                value={c.statut}
                onChange={(e) => void changerStatut(c, e.target.value as StatutConsultation)}
                className="h-10 rounded-lg border border-bordure-forte bg-fond px-2 text-sm"
              >
                {Object.entries(STATUTS_CONSULTATION).map(([code, libelle]) => (
                  <option key={code} value={code}>
                    {libelle}
                  </option>
                ))}
              </select>
              {c.statut === "A_CONSULTER" && (
                <button
                  type="button"
                  onClick={() => void retirer(c)}
                  aria-label={`Retirer ${c.entreprise} du lot ${lot.code}`}
                  className="grid size-10 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger"
                >
                  <Trash2 aria-hidden="true" className="size-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {ouvert && (
        <div className="flex flex-col gap-2 rounded-lg bg-fond/40 p-3">
          {suggestions === null && <p className="text-sm text-attenue">Recherche dans l'annuaire…</p>}
          {suggestions?.length === 0 && (
            <p className="text-sm text-attenue">
              Aucune autre entreprise de l'annuaire pour ce lot.{" "}
              <Link to="/entreprises/nouvelle" className="text-accent">
                Ajouter une entreprise
              </Link>
            </p>
          )}
          {suggestions?.map((s) => (
            <label key={s.id} className="flex min-h-10 min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 text-sm">
              <input
                type="checkbox"
                checked={choix.has(s.id)}
                onChange={(e) => {
                  const suivant = new Set(choix);
                  if (e.target.checked) suivant.add(s.id);
                  else suivant.delete(s.id);
                  setChoix(suivant);
                }}
                className="size-4 accent-[var(--color-accent)]"
              />
              <span className="font-semibold">{s.raison_sociale}</span>
              <span className="min-w-0 break-all text-attenue">{[s.ville, s.email].filter(Boolean).join(" · ")}</span>
            </label>
          ))}
          {suggestions && suggestions.length > 0 && (
            <button type="button" onClick={() => void ajouter()} disabled={choix.size === 0} className="self-end min-h-10 rounded-lg bg-accent px-4 text-sm font-bold text-sur-accent disabled:opacity-50">
              Ajouter {choix.size > 0 ? pluriel(choix.size, "entreprise") : ""}
            </button>
          )}
        </div>
      )}
      {erreur && (
        <p role="alert" className="text-sm text-danger">
          {erreur}
        </p>
      )}
    </li>
  );
}

function Envois({ etat, surChangement }: { etat: EtatDCE; surChangement: () => void }) {
  if (etat.envois.length === 0) return null;
  async function marquer(envoi: EnvoiDCE) {
    await api(`/dce/envois/${envoi.id}/envoye`, { method: "POST" }).catch(() => undefined);
    surChangement();
  }
  return (
    <section aria-labelledby="titre-envois" className="flex flex-col gap-3 rounded-xl border border-bordure bg-surface p-5">
      <h2 id="titre-envois" className="font-titre text-lg font-semibold">
        Suivi des envois
      </h2>
      <ul className="flex flex-col divide-y divide-bordure">
        {etat.envois.map((e) => (
          <li key={e.id} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5">
            <span className="min-w-0 flex-[1_1_260px]">
              <span className="font-semibold">{e.type_envoi === "MOA" ? "Maître d'ouvrage" : e.entreprise}</span>
              <span className="block break-all text-xs text-attenue">
                {e.destinataires} · {formaterDate(e.envoye_le ?? e.cree_le)}
                {e.piece_jointe ? " · dossier joint" : ""}
              </span>
              {e.erreur && <span className="block text-xs text-accent">{e.erreur}</span>}
            </span>
            <span
              className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                e.statut === "ENVOYE" ? "bg-succes/12 text-succes" : e.statut === "ERREUR" ? "bg-danger/12 text-danger" : "bg-accent/12 text-accent"
              }`}
            >
              {e.statut_libelle}
            </span>
            {(e.statut === "A_ENVOYER" || e.statut === "ERREUR") && (
              <>
                {e.dossier_id && (
                  <a href={`/api/dce/dossiers/${e.dossier_id}/telecharger`} className="flex min-h-10 items-center gap-1.5 rounded-lg border border-bordure-forte px-3 text-sm text-texte no-underline hover:bg-surface-2">
                    <Download aria-hidden="true" className="size-4" />
                    Dossier
                  </a>
                )}
                <a href={lienMail(e)} className="flex min-h-10 items-center gap-1.5 rounded-lg border border-bordure-forte px-3 text-sm text-texte no-underline hover:bg-surface-2">
                  <Mail aria-hidden="true" className="size-4" />
                  Ouvrir dans ma messagerie
                </a>
                <button type="button" onClick={() => void marquer(e)} className="min-h-10 rounded-lg px-3 text-sm font-semibold text-accent hover:bg-accent/10">
                  Marquer comme envoyé
                </button>
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
