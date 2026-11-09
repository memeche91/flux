/** Dépôt de plusieurs documents en une fois : indice et n° de plan lus dans le nom des fichiers,
 * fichiers sources (DWG…) rattachés au PDF de même nom, nouvel indice proposé quand le document
 * existe déjà. Les courriels de l'envoi sont regroupés. */
import { CheckCircle2, Loader2, Paperclip, Trash2, Upload, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from "react";

import { CLASSE_CHAMP, Champ } from "../components/Filtres";
import { formaterTaille } from "../lib/format";
import type { ClientGed } from "./client";
import {
  analyserNomFichier,
  CLASSE_BOUTON,
  CLASSE_BOUTON_PRINCIPAL,
  identifiantDepot,
  indicePlusHaut,
  indiceSuivant,
  messageErreur,
  normaliserIndice,
  regrouperSources,
} from "./outils";
import type { Diffusion, DocumentGed, DroitsGed, Referentiels, ZoneGed } from "./types";

interface Ligne {
  cle: number;
  fichier: File;
  sources: File[];
  /** 0 = nouveau document ; sinon, document dont on dépose un nouvel indice. */
  documentId: number;
  /** Cible choisie à la main : elle n'est plus recalculée quand le classement change. */
  cibleManuelle: boolean;
  titre: string;
  referenceEmetteur: string;
  indice: string;
  objet: string;
  etat: "attente" | "envoi" | "fait" | "erreur";
  progression: number;
  message: string;
}

const LIBELLES_ZONES: Record<ZoneGed, string> = { COMMUN: "Commun à tous", LOT: "Lot", MOE: "Maîtrise d'œuvre (réservé)" };
const cleComparaison = (texte: string) =>
  texte
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/[^a-z0-9]/gi, "")
    .toLowerCase();

interface Proprietes {
  client: ClientGed;
  droits: DroitsGed;
  referentiels: Referentiels;
  documents: DocumentGed[];
  zoneInitiale?: ZoneGed;
  lotInitial?: number;
  surDepose: (document: DocumentGed) => void;
  surFermer: () => void;
}

export default function Depot({ client, droits, referentiels, documents, zoneInitiale, lotInitial, surDepose, surFermer }: Proprietes) {
  const zones = droits.zones_depot;
  const [zone, setZone] = useState<ZoneGed>(zoneInitiale && zones.includes(zoneInitiale) ? zoneInitiale : zones.includes("LOT") ? "LOT" : zones[0]);
  const [lotId, setLotId] = useState<number | "">(
    lotInitial && droits.lots_depot.some((l) => l.id === lotInitial) ? lotInitial : droits.lots_depot.length === 1 ? droits.lots_depot[0].id : "",
  );
  // Catégories proposées dans la zone, ou permises ailleurs que dans leur zone habituelle (CSPS : DIUO dans le Commun).
  const categoriesZone = referentiels.categories.filter(
    (c) => droits.categories_depot.includes(c.code) && (zone === "MOE" || c.zone === zone || !zones.includes(c.zone as ZoneGed)),
  );
  const [categorie, setCategorie] = useState("");
  const categorieChoisie = categoriesZone.find((c) => c.code === categorie);
  const [diffusion, setDiffusion] = useState<Diffusion | "">("");
  const [lignes, setLignes] = useState<Ligne[]>([]);
  const [envoi, setEnvoi] = useState(false);
  const [survol, setSurvol] = useState(false);
  const compteur = useRef(0);
  const choixFichiers = useRef<HTMLInputElement>(null);
  const pdfExige = !droits.choix_diffusion && Boolean(categorieChoisie?.visa);

  // Documents du même classement auxquels un nouvel indice peut être ajouté.
  const existants = useMemo(
    () =>
      documents.filter(
        (d) => d.peut_ajouter_indice && !d.annule && d.zone === zone && (zone !== "LOT" || d.lot?.id === lotId) && (!categorie || d.categorie === categorie),
      ),
    [documents, zone, lotId, categorie],
  );

  const rapprocher = useCallback(
    (referenceEmetteur: string, titre: string): DocumentGed | undefined => {
      const ref = cleComparaison(referenceEmetteur);
      const tit = cleComparaison(titre);
      return existants.find(
        (d) =>
          (ref && cleComparaison(d.reference_emetteur) === ref) || (ref && cleComparaison(d.reference) === ref) || (tit && cleComparaison(d.titre) === tit),
      );
    },
    [existants],
  );

  // Classement changé (lot, catégorie choisis après l'ajout des fichiers) : le document existant
  // est recherché de nouveau ; un choix fait à la main est gardé s'il est encore de ce classement.
  useEffect(() => {
    setLignes((actuelles) =>
      actuelles.map((l) => {
        if (l.etat === "fait" || l.etat === "envoi") return l;
        if (l.cibleManuelle && (!l.documentId || existants.some((d) => d.id === l.documentId))) return l;
        const documentId = rapprocher(l.referenceEmetteur, l.titre)?.id ?? 0;
        return documentId === l.documentId && !l.cibleManuelle ? l : { ...l, documentId, cibleManuelle: false };
      }),
    );
  }, [existants, rapprocher]);

  function choisirCategorie(code: string) {
    setCategorie(code);
    const choisie = referentiels.categories.find((c) => c.code === code);
    setDiffusion(!code ? "" : choisie?.visa ? "VISA" : code === "PLA" ? "BPE" : "INFO");
  }

  function ajouterFichiers(fichiers: File[]) {
    if (!fichiers.length) return;
    const nouvelles = regrouperSources(fichiers).map(({ principal, sources }) => {
      const analyse = analyserNomFichier(principal.name);
      const existant = rapprocher(analyse.referenceEmetteur, analyse.titre);
      compteur.current += 1;
      return {
        cle: compteur.current,
        fichier: principal,
        sources,
        documentId: existant?.id ?? 0,
        cibleManuelle: false,
        titre: analyse.titre,
        referenceEmetteur: analyse.referenceEmetteur,
        indice: analyse.indice,
        objet: "",
        etat: "attente" as const,
        progression: 0,
        message: "",
      };
    });
    setLignes((actuelles) => [...actuelles.filter((l) => l.etat !== "fait"), ...nouvelles]);
  }

  const maj = (cle: number, champs: Partial<Ligne>) => setLignes((actuelles) => actuelles.map((l) => (l.cle === cle ? { ...l, ...champs } : l)));

  function surDepot(evenement: DragEvent) {
    evenement.preventDefault();
    setSurvol(false);
    ajouterFichiers(Array.from(evenement.dataTransfer.files));
  }

  async function envoyer(evenement: FormEvent) {
    evenement.preventDefault();
    if (!categorie || (zone === "LOT" && !lotId)) return;
    const identifiant = identifiantDepot();
    setEnvoi(true);
    for (const ligne of lignes) {
      if (ligne.etat === "fait") continue;
      maj(ligne.cle, { etat: "envoi", progression: 0, message: "" });
      const donnees = new FormData();
      donnees.append("fichier", ligne.fichier);
      for (const source of ligne.sources) donnees.append("sources", source);
      donnees.append("indice", normaliserIndice(ligne.indice));
      donnees.append("objet", ligne.objet.trim());
      donnees.append("depot", identifiant);
      if (diffusion) donnees.append("diffusion", diffusion);
      try {
        let document: DocumentGed;
        if (ligne.documentId) {
          document = await client.ajouterIndice(ligne.documentId, donnees, (f) => maj(ligne.cle, { progression: f }));
        } else {
          donnees.append("zone", zone);
          if (zone === "LOT") donnees.append("lot_id", String(lotId));
          donnees.append("categorie", categorie);
          donnees.append("titre", ligne.titre.trim());
          donnees.append("reference_emetteur", ligne.referenceEmetteur.trim());
          document = await client.deposer(donnees, (f) => maj(ligne.cle, { progression: f }));
        }
        surDepose(document);
        maj(ligne.cle, { etat: "fait", progression: 1, message: `${document.reference} indice ${document.versions[0]?.indice ?? ""}` });
      } catch (p) {
        maj(ligne.cle, { etat: "erreur", message: messageErreur(p, "Dépôt impossible.") });
      }
    }
    setEnvoi(false);
  }

  const aEnvoyer = lignes.filter((l) => l.etat !== "fait");
  const termine = lignes.length > 0 && aEnvoyer.length === 0;

  return (
    <form onSubmit={envoyer} className="flex flex-col gap-4 rounded-xl border border-accent/40 bg-surface p-5" aria-labelledby="titre-depot">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2 id="titre-depot" className="font-titre text-lg font-semibold">
            Déposer des documents
          </h2>
          <p className="text-sm text-attenue">
            Indice et n° de plan sont lus dans le nom des fichiers (« EXE-08-003_C.pdf », « Façade ind B.pdf ») ; un DWG de même nom que le PDF lui est joint
            comme fichier source.
          </p>
        </div>
        <button
          type="button"
          onClick={surFermer}
          disabled={envoi}
          className="grid size-10 shrink-0 place-items-center rounded-lg text-attenue hover:bg-surface-2"
          aria-label="Fermer le dépôt"
        >
          <X aria-hidden="true" className="size-5" />
        </button>
      </div>

      <div className="flex flex-wrap gap-3">
        {zones.length > 1 && (
          <Champ id="depot-zone" libelle="Classement">
            <select
              id="depot-zone"
              value={zone}
              onChange={(e) => {
                setZone(e.target.value as ZoneGed);
                choisirCategorie("");
              }}
              className={CLASSE_CHAMP}
            >
              {zones.map((z) => (
                <option key={z} value={z}>
                  {LIBELLES_ZONES[z]}
                </option>
              ))}
            </select>
          </Champ>
        )}
        {zone === "LOT" && (
          <Champ id="depot-lot" libelle="Lot" large>
            <select id="depot-lot" value={lotId} onChange={(e) => setLotId(e.target.value ? Number(e.target.value) : "")} required className={CLASSE_CHAMP}>
              {droits.lots_depot.length > 1 && <option value="">Choisir…</option>}
              {droits.lots_depot.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.code} – {l.intitule}
                </option>
              ))}
            </select>
          </Champ>
        )}
        <Champ id="depot-categorie" libelle="Catégorie" large>
          <select id="depot-categorie" value={categorie} onChange={(e) => choisirCategorie(e.target.value)} required className={CLASSE_CHAMP}>
            <option value="">Choisir…</option>
            {categoriesZone.map((c) => (
              <option key={c.code} value={c.code}>
                {c.libelle}
                {c.visa && !droits.choix_diffusion ? " (soumis au visa)" : ""}
              </option>
            ))}
          </select>
        </Champ>
        {droits.choix_diffusion && (
          <Champ id="depot-diffusion" libelle="Diffusion">
            <select
              id="depot-diffusion"
              value={diffusion}
              onChange={(e) => setDiffusion(e.target.value as Diffusion | "")}
              disabled={!categorie}
              className={CLASSE_CHAMP}
            >
              {!categorie && <option value="">Selon la catégorie</option>}
              {referentiels.diffusions.map((x) => (
                <option key={x.code} value={x.code}>
                  {x.libelle}
                </option>
              ))}
            </select>
          </Champ>
        )}
      </div>
      {pdfExige && (
        <p className="text-sm text-attention">Documents soumis au visa : déposez le PDF ; le DWG ou le fichier modifiable de même nom lui sera joint.</p>
      )}

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setSurvol(true);
        }}
        onDragLeave={() => setSurvol(false)}
        onDrop={surDepot}
        className={`flex flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-center ${survol ? "border-accent bg-accent/10" : "border-bordure-forte"}`}
      >
        <Upload aria-hidden="true" className="size-6 text-attenue" />
        <p className="text-attenue">Glissez les fichiers ici, ou</p>
        <button type="button" onClick={() => choixFichiers.current?.click()} className={CLASSE_BOUTON}>
          Choisir des fichiers
        </button>
        <input
          ref={choixFichiers}
          type="file"
          multiple
          className="sr-only"
          aria-label="Fichiers à déposer"
          onChange={(e) => {
            ajouterFichiers(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
        <p className="text-xs text-attenue">{referentiels.taille_max_mo} Mo maximum par fichier.</p>
      </div>

      {lignes.length > 0 && (
        <ul className="flex flex-col gap-2">
          {lignes.map((ligne) => {
            const existant = documents.find((d) => d.id === ligne.documentId);
            const suggestion = existant ? indiceSuivant(indicePlusHaut(existant.versions.map((v) => v.indice))) : "A";
            const pasPdf = pdfExige && !ligne.fichier.name.toLowerCase().endsWith(".pdf");
            const fige = ligne.etat === "fait" || ligne.etat === "envoi";
            return (
              <li
                key={ligne.cle}
                className={`flex flex-col gap-2 rounded-lg border px-3 py-3 ${ligne.etat === "erreur" || pasPdf ? "border-danger/50" : ligne.etat === "fait" ? "border-succes/40" : "border-bordure-forte"} bg-fond`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  {ligne.etat === "fait" ? (
                    <CheckCircle2 aria-hidden="true" className="size-4 text-succes" />
                  ) : ligne.etat === "envoi" ? (
                    <Loader2 aria-hidden="true" className="size-4 animate-spin text-accent" />
                  ) : null}
                  <span className="min-w-0 flex-1 truncate font-semibold" title={ligne.fichier.name}>
                    {ligne.fichier.name} <span className="font-normal text-attenue">({formaterTaille(ligne.fichier.size)})</span>
                  </span>
                  {!fige && (
                    <button
                      type="button"
                      onClick={() => setLignes((l) => l.filter((x) => x.cle !== ligne.cle))}
                      className="grid size-9 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger"
                      aria-label={`Retirer ${ligne.fichier.name}`}
                    >
                      <Trash2 aria-hidden="true" className="size-4" />
                    </button>
                  )}
                </div>
                {ligne.sources.length > 0 && (
                  <p className="flex flex-wrap items-center gap-1.5 text-xs text-attenue">
                    <Paperclip aria-hidden="true" className="size-3.5" />
                    Fichiers sources joints : {ligne.sources.map((s) => s.name).join(", ")}
                  </p>
                )}
                {!fige && (
                  <div className="flex flex-wrap gap-3">
                    <Champ id={`depot-action-${ligne.cle}`} libelle="Dépôt" large>
                      <select
                        id={`depot-action-${ligne.cle}`}
                        value={ligne.documentId}
                        onChange={(e) => maj(ligne.cle, { documentId: Number(e.target.value), cibleManuelle: true })}
                        className={CLASSE_CHAMP}
                      >
                        <option value={0}>Nouveau document</option>
                        {existants.map((d) => (
                          <option key={d.id} value={d.id}>
                            Nouvel indice de {d.reference} – {d.titre} (actuel : {d.versions[0]?.indice})
                          </option>
                        ))}
                      </select>
                    </Champ>
                    {!ligne.documentId && (
                      <>
                        <Champ id={`depot-titre-${ligne.cle}`} libelle="Titre" large>
                          <input
                            id={`depot-titre-${ligne.cle}`}
                            value={ligne.titre}
                            onChange={(e) => maj(ligne.cle, { titre: e.target.value })}
                            maxLength={255}
                            required
                            className={CLASSE_CHAMP}
                          />
                        </Champ>
                        <Champ id={`depot-emetteur-${ligne.cle}`} libelle="N° de plan (cartouche)">
                          <input
                            id={`depot-emetteur-${ligne.cle}`}
                            value={ligne.referenceEmetteur}
                            onChange={(e) => maj(ligne.cle, { referenceEmetteur: e.target.value })}
                            maxLength={80}
                            className={CLASSE_CHAMP}
                          />
                        </Champ>
                      </>
                    )}
                    <Champ id={`depot-indice-${ligne.cle}`} libelle="Indice">
                      <input
                        id={`depot-indice-${ligne.cle}`}
                        value={ligne.indice}
                        onChange={(e) => maj(ligne.cle, { indice: e.target.value })}
                        placeholder={suggestion}
                        maxLength={8}
                        className={CLASSE_CHAMP}
                      />
                    </Champ>
                    {ligne.documentId > 0 && (
                      <Champ id={`depot-objet-${ligne.cle}`} libelle="Objet de la modification" large>
                        <input
                          id={`depot-objet-${ligne.cle}`}
                          value={ligne.objet}
                          onChange={(e) => maj(ligne.cle, { objet: e.target.value })}
                          maxLength={500}
                          className={CLASSE_CHAMP}
                        />
                      </Champ>
                    )}
                  </div>
                )}
                {ligne.etat === "envoi" && (
                  <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
                    <div className="h-full bg-accent" style={{ width: `${Math.round(ligne.progression * 100)}%` }} />
                  </div>
                )}
                {pasPdf && !fige && <p className="text-sm text-danger">Ce document doit être déposé en PDF.</p>}
                {ligne.message && (
                  <p role={ligne.etat === "erreur" ? "alert" : "status"} className={`text-sm ${ligne.etat === "erreur" ? "text-danger" : "text-succes"}`}>
                    {ligne.etat === "fait" ? `Déposé : ${ligne.message}` : ligne.message}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex flex-wrap items-center justify-end gap-3">
        {termine && <span className="text-succes">Tous les documents sont déposés ; un récépissé vous est envoyé par courriel.</span>}
        <button type="button" onClick={surFermer} disabled={envoi} className={CLASSE_BOUTON}>
          {termine ? "Fermer" : "Annuler"}
        </button>
        <button
          type="submit"
          disabled={
            envoi ||
            aEnvoyer.length === 0 ||
            !categorie ||
            (zone === "LOT" && !lotId) ||
            aEnvoyer.some((l) => pdfExige && !l.fichier.name.toLowerCase().endsWith(".pdf"))
          }
          className={CLASSE_BOUTON_PRINCIPAL}
        >
          <Upload aria-hidden="true" className="size-4" />
          {envoi ? "Dépôt en cours…" : aEnvoyer.length > 1 ? `Déposer les ${aEnvoyer.length} documents` : "Déposer"}
        </button>
      </div>
    </form>
  );
}
