import { useId, useState, type FormEvent } from "react";

import { CLASSE_CHAMP } from "../Filtres";

/** Même règle que le serveur (referentiel/codes.py) : 10 caractères au plus. */
export const LONGUEUR_NUMERO_LOT = 10;
export const LONGUEUR_INTITULE_LOT = 255;

/** Même format que le serveur : lettres sans accent et chiffres seulement (03, 3a, 3bis, TCE). */
export function numeroLotValide(code: string): boolean {
  return /^[A-Za-z0-9]{1,10}$/.test(code.trim());
}

export const MESSAGE_NUMERO_INVALIDE = "Numéro invalide : lettres (sans accent) et chiffres seulement, sans espace ni signe (par exemple 03, 3a ou 3bis).";

/** « 8 », « 08 » et « 008 » désignent le même lot ; « 3A » et « 3a » aussi (comme le serveur). */
export function cleNumeroLot(code: string): string {
  const nettoye = code.trim().toLowerCase();
  return /^\d+$/.test(nettoye) ? String(Number(nettoye)).padStart(2, "0") : nettoye;
}

interface Proprietes {
  code: string;
  intitule: string;
  /** Numéro non modifiable (lot TCE de la liste proposée). */
  numeroVerrouille?: boolean;
  indication?: string;
  libelleBouton?: string;
  surEnregistrer: (code: string, intitule: string) => Promise<void>;
  surAnnuler: () => void;
}

/** Numéro et intitulé d'un lot, modifiés sur place (lot d'un projet, ou liste des lots proposés). */
export default function EditionLot({ code, intitule, numeroVerrouille = false, indication, libelleBouton = "Enregistrer", surEnregistrer, surAnnuler }: Proprietes) {
  const id = useId();
  const [numero, setNumero] = useState(code);
  const [titre, setTitre] = useState(intitule);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  async function enregistrer(evenement: FormEvent) {
    evenement.preventDefault();
    setErreur(null);
    // Numéro modifié vérifié tout de suite ; un numéro inchangé (même ancien) est accepté par le serveur.
    if (numero.trim() !== code && !numeroLotValide(numero)) {
      setErreur(MESSAGE_NUMERO_INVALIDE);
      return;
    }
    setEnvoi(true);
    try {
      await surEnregistrer(numero.trim(), titre.trim());
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Enregistrement impossible.");
      setEnvoi(false);
    }
  }

  return (
    <form
      onSubmit={enregistrer}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          surAnnuler();
        }
      }}
      className="flex min-w-0 flex-[1_1_100%] flex-col gap-2"
    >
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex w-28 flex-col gap-1.5">
          <label htmlFor={`${id}-numero`} className="text-xs font-semibold text-attenue">
            Numéro
          </label>
          <input
            id={`${id}-numero`}
            value={numero}
            onChange={(e) => setNumero(e.target.value)}
            maxLength={LONGUEUR_NUMERO_LOT}
            required
            disabled={numeroVerrouille}
            autoFocus={!numeroVerrouille}
            autoComplete="off"
            className={`${CLASSE_CHAMP} disabled:opacity-60`}
          />
        </div>
        <div className="flex min-w-0 flex-[1_1_240px] flex-col gap-1.5">
          <label htmlFor={`${id}-intitule`} className="text-xs font-semibold text-attenue">
            Intitulé
          </label>
          <input
            id={`${id}-intitule`}
            value={titre}
            onChange={(e) => setTitre(e.target.value)}
            maxLength={LONGUEUR_INTITULE_LOT}
            required
            autoFocus={numeroVerrouille}
            autoComplete="off"
            className={CLASSE_CHAMP}
          />
        </div>
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={envoi || !numero.trim() || !titre.trim()}
            className="min-h-11 rounded-lg bg-accent px-4 font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-50"
          >
            {envoi ? "Enregistrement…" : libelleBouton}
          </button>
          <button type="button" onClick={surAnnuler} className="min-h-11 rounded-lg border border-bordure-forte px-4 hover:bg-surface-2">
            Annuler
          </button>
        </div>
      </div>
      {indication && <p className="text-xs text-attenue">{indication}</p>}
      {erreur && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {erreur}
        </p>
      )}
    </form>
  );
}
