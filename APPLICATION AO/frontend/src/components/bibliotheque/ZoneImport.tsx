import { CheckCircle2, CircleAlert, FileUp, LoaderCircle } from "lucide-react";
import { useId, useRef, useState, type DragEvent } from "react";

import { televerser } from "../../api/client";
import { FORMATS_ACCEPTES, type DescriptionType, type Lot, type TypeMarche } from "../../api/types";
import { formaterTaille } from "../../lib/format";

interface Proprietes {
  type: DescriptionType;
  lots: Lot[];
  lotSelectionne: number | null;
  surDocumentAjoute: () => void;
}

type Etat = "attente" | "envoi" | "ok" | "erreur";

interface ElementFile {
  cle: number;
  nom: string;
  taille: number;
  destination: string;
  etat: Etat;
  progression: number;
  message?: string;
}

const champ = "min-h-11 rounded-lg border border-bordure-forte bg-fond px-3 text-texte";

export default function ZoneImport({ type, lots, lotSelectionne, surDocumentAjoute }: Proprietes) {
  const identifiant = useId();
  const compteur = useRef(0);
  const [operation, setOperation] = useState("");
  const [annee, setAnnee] = useState("");
  const [typeMarche, setTypeMarche] = useState<TypeMarche>("");
  const [survol, setSurvol] = useState(false);
  const [file, setFile] = useState<ElementFile[]>([]);

  // Le lot suit l'onglet et le lot choisis dans la liste, sauf si l'utilisateur
  // le change dans le menu : ce choix ne vaut que pour la sélection en cours.
  const selection = `${type.code}:${lotSelectionne ?? ""}`;
  const [lotManuel, setLotManuel] = useState<{ selection: string; lot: number | null } | null>(null);
  const lotChoisi = lotManuel?.selection === selection ? lotManuel.lot : lotSelectionne;
  const [alerteBrute, setAlerteBrute] = useState<{ selection: string; texte: string } | null>(null);
  const alerte = alerteBrute?.selection === selection ? alerteBrute.texte : null;
  const setAlerte = (texte: string | null) => setAlerteBrute(texte ? { selection, texte } : null);

  const mettreAJour = (cle: number, changement: Partial<ElementFile>) =>
    setFile((elements) => elements.map((e) => (e.cle === cle ? { ...e, ...changement } : e)));

  async function envoyer(fichiers: File[]) {
    if (fichiers.length === 0) return;
    if (type.parLot && lotChoisi === null) {
      setAlerte("Choisissez d'abord le lot auquel appartiennent ces documents.");
      return;
    }
    setAlerte(null);

    // Les informations sont figées au moment du dépôt.
    const lot = lots.find((l) => l.id === lotChoisi);
    const destination = lot ? `${type.libelle} · lot ${lot.code}` : type.libelle;
    const contexte = { type: type.code, lot: lotChoisi, operation: operation.trim(), annee, typeMarche };
    const nouveaux = fichiers.map((fichier) => ({
      fichier,
      element: {
        cle: ++compteur.current,
        nom: fichier.name,
        taille: fichier.size,
        destination,
        etat: "attente" as Etat,
        progression: 0,
      },
    }));
    setFile((elements) => [...nouveaux.map((n) => n.element), ...elements]);

    for (const { fichier, element } of nouveaux) {
      mettreAJour(element.cle, { etat: "envoi" });
      const donnees = new FormData();
      donnees.append("fichier", fichier);
      donnees.append("type_document", contexte.type);
      if (type.parLot && contexte.lot !== null) donnees.append("lot_id", String(contexte.lot));
      if (contexte.operation) donnees.append("operation", contexte.operation);
      if (contexte.annee) donnees.append("annee", contexte.annee);
      if (contexte.typeMarche) donnees.append("type_marche", contexte.typeMarche);
      try {
        await televerser("/bibliotheque/documents", donnees, (p) => mettreAJour(element.cle, { progression: p }));
        mettreAJour(element.cle, { etat: "ok", progression: 1 });
        surDocumentAjoute();
      } catch (probleme) {
        mettreAJour(element.cle, {
          etat: "erreur",
          message: probleme instanceof Error ? probleme.message : "Erreur inconnue",
        });
      }
    }
  }

  function deposer(evenement: DragEvent<HTMLLabelElement>) {
    evenement.preventDefault();
    setSurvol(false);
    void envoyer(Array.from(evenement.dataTransfer.files));
  }

  const termines = file.filter((e) => e.etat === "ok").length;
  const erreurs = file.filter((e) => e.etat === "erreur").length;
  const enCours = file.some((e) => e.etat === "attente" || e.etat === "envoi");

  return (
    <section
      aria-labelledby={`${identifiant}-titre`}
      className="flex flex-col gap-4 rounded-xl border border-bordure bg-surface p-5"
    >
      <div className="flex flex-col gap-1">
        <h2 id={`${identifiant}-titre`} className="font-titre text-lg font-semibold">
          Ajouter des {type.pluriel === type.libelle ? type.libelle : type.pluriel.toLowerCase()}
        </h2>
        <p className="text-attenue">Aucune limite de nombre : déposez autant de fichiers que nécessaire.</p>
      </div>

      <div className="flex flex-wrap gap-3">
        {type.parLot && (
          <div className="flex min-w-0 flex-[2_1_240px] flex-col gap-1.5">
            <label htmlFor={`${identifiant}-lot`} className="text-xs font-semibold text-attenue">
              Lot <span className="text-accent">(obligatoire)</span>
            </label>
            <select
              id={`${identifiant}-lot`}
              value={lotChoisi ?? ""}
              onChange={(e) => setLotManuel({ selection, lot: e.target.value ? Number(e.target.value) : null })}
              className={champ}
            >
              <option value="">Choisir un lot…</option>
              {lots.map((lot) => (
                <option key={lot.id} value={lot.id}>
                  {lot.code} – {lot.intitule}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="flex min-w-0 flex-[2_1_220px] flex-col gap-1.5">
          <label htmlFor={`${identifiant}-operation`} className="text-xs font-semibold text-attenue">
            Opération d'origine
          </label>
          <input
            id={`${identifiant}-operation`}
            value={operation}
            onChange={(e) => setOperation(e.target.value)}
            placeholder="Ex. Collège Pasteur – restructuration"
            className={champ}
          />
        </div>
        <div className="flex min-w-0 flex-[1_1_110px] flex-col gap-1.5">
          <label htmlFor={`${identifiant}-annee`} className="text-xs font-semibold text-attenue">
            Année
          </label>
          <input
            id={`${identifiant}-annee`}
            inputMode="numeric"
            maxLength={4}
            value={annee}
            onChange={(e) => setAnnee(e.target.value.replace(/\D/g, ""))}
            placeholder="2024"
            className={champ}
          />
        </div>
        <div className="flex min-w-0 flex-[1_1_150px] flex-col gap-1.5">
          <label htmlFor={`${identifiant}-marche`} className="text-xs font-semibold text-attenue">
            Marché
          </label>
          <select
            id={`${identifiant}-marche`}
            value={typeMarche}
            onChange={(e) => setTypeMarche(e.target.value as TypeMarche)}
            className={champ}
          >
            <option value="">Non précisé</option>
            <option value="PUBLIC">Public</option>
            <option value="PRIVE">Privé</option>
          </select>
        </div>
      </div>

      <label
        htmlFor={`${identifiant}-fichiers`}
        onDragOver={(e) => {
          e.preventDefault();
          setSurvol(true);
        }}
        onDragLeave={() => setSurvol(false)}
        onDrop={deposer}
        className={`relative flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent ${
          survol ? "border-accent bg-accent/10" : "border-bordure-forte hover:border-attenue hover:bg-surface-2/50"
        }`}
      >
        <FileUp aria-hidden="true" className="size-8 text-accent" />
        <span className="font-semibold">Glissez vos fichiers ici ou cliquez pour parcourir</span>
        <span className="text-xs text-attenue">PDF, Word, Excel, OpenDocument, CSV · plusieurs fichiers à la fois</span>
        <input
          id={`${identifiant}-fichiers`}
          type="file"
          multiple
          accept={FORMATS_ACCEPTES}
          className="sr-only"
          onChange={(e) => {
            void envoyer(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
      </label>

      {alerte && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {alerte}
        </p>
      )}

      {file.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-attenue" aria-live="polite">
              {termines} ajouté{termines > 1 ? "s" : ""}
              {erreurs > 0 && ` · ${erreurs} en erreur`}
              {enCours && " · envoi en cours…"}
            </p>
            {!enCours && (
              <button
                type="button"
                onClick={() => setFile([])}
                className="min-h-11 rounded-lg px-3 text-attenue hover:bg-surface-2 hover:text-texte"
              >
                Effacer la liste
              </button>
            )}
          </div>
          <ul className="flex max-h-72 flex-col gap-1.5 overflow-y-auto">
            {file.map((element) => (
              <li key={element.cle} className="flex items-center gap-3 rounded-lg bg-fond px-3 py-2">
                <IconeEtat etat={element.etat} />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span className="truncate font-medium" title={element.nom}>
                      {element.nom}
                    </span>
                    <span className="shrink-0 text-xs text-attenue">
                      {element.destination} · {formaterTaille(element.taille)}
                    </span>
                  </div>
                  {element.etat === "envoi" && (
                    <div aria-hidden="true" className="h-1.5 rounded-full bg-bordure">
                      <div
                        className="h-1.5 rounded-full bg-accent transition-[width]"
                        style={{ width: `${Math.round(element.progression * 100)}%` }}
                      />
                    </div>
                  )}
                  {element.message && <span className="text-xs text-danger">{element.message}</span>}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function IconeEtat({ etat }: { etat: Etat }) {
  if (etat === "ok") return <CheckCircle2 aria-label="Ajouté" className="size-5 shrink-0 text-succes" />;
  if (etat === "erreur") return <CircleAlert aria-label="Erreur" className="size-5 shrink-0 text-danger" />;
  return (
    <LoaderCircle
      aria-label={etat === "envoi" ? "Envoi en cours" : "En attente"}
      className={`size-5 shrink-0 text-accent ${etat === "envoi" ? "animate-spin" : "opacity-50"}`}
    />
  );
}
