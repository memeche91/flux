/** Outils de la GED : indices, lecture des noms de fichiers, styles des états. */
import type { DocumentGed, StatutVersion, VersionGed } from "./types";

export const FORMAT_INDICE = /^(\d{1,3}|[A-Z]{1,3}\d?)$/;

export function normaliserIndice(indice: string): string {
  return indice
    .trim()
    .toUpperCase()
    .replace(/^(INDICE|IND)\.?\s*/, "")
    .replace(/\s/g, "");
}

/** Indice qui suit : A → B, Z → AA ; 0 → A ; 1 → 2 (mêmes règles que le serveur). */
export function indiceSuivant(indice: string | null | undefined): string {
  const propre = normaliserIndice(indice ?? "");
  if (!propre) return "A";
  if (/^\d+$/.test(propre)) return Number(propre) === 0 ? "A" : String(Number(propre) + 1);
  const lettres = propre.replace(/\d+$/, "").split("");
  for (let position = lettres.length - 1; position >= 0; position -= 1) {
    if (lettres[position] !== "Z") {
      lettres[position] = String.fromCharCode(lettres[position].charCodeAt(0) + 1);
      return lettres.join("");
    }
    lettres[position] = "A";
  }
  return `A${lettres.join("")}`;
}

/** Clé de tri des indices : 0 < 1 < A < A1 < B < Z < AA (mêmes règles que le serveur). */
function cleIndice(indice: string): [number, number, string, number] {
  const propre = normaliserIndice(indice);
  if (/^\d+$/.test(propre)) return [0, Number(propre), "", 0];
  const lettres = propre.replace(/\d+$/, "");
  return [1, lettres.length, lettres, Number(propre.slice(lettres.length) || 0)];
}

/** Plus haut indice d'un document (après un indice hors séquence, le suivant part de celui-ci). */
export function indicePlusHaut(indices: string[]): string | null {
  let haut: string | null = null;
  for (const indice of indices) {
    if (haut === null) {
      haut = indice;
      continue;
    }
    const a = cleIndice(indice);
    const b = cleIndice(haut);
    for (let i = 0; i < 4; i += 1) {
      if (a[i] !== b[i]) {
        if (a[i] > b[i]) haut = indice;
        break;
      }
    }
  }
  return haut;
}

export interface NomAnalyse {
  base: string;
  extension: string;
  titre: string;
  indice: string;
  referenceEmetteur: string;
}

/** « EXE-08-PLB-003_C.pdf », « Facade nord - ind B.pdf », « Note de calcul (B).pdf » :
 * indice, n° de l'émetteur (le code du cartouche) et titre proposés. */
export function analyserNomFichier(nom: string): NomAnalyse {
  const point = nom.lastIndexOf(".");
  const base = point > 0 ? nom.slice(0, point) : nom;
  const extension = point > 0 ? nom.slice(point + 1).toLowerCase() : "";
  let reste = base.trim();
  let indice = "";
  const motifs = [
    /[\s_-]+ind(?:ice)?\.?[\s_-]*([A-Z]{1,3}\d?|\d{1,3})$/i, // « - ind B », « _indice C », « ind.2 »
    /\s*\(([A-Z]{1,3}\d?|\d{1,3})\)$/i, // « (C) »
    /[_-]([A-Z]{1,2}\d?)$/, // « _C », « -B1 » (majuscules seulement)
  ];
  for (const motif of motifs) {
    const trouve = reste.match(motif);
    if (trouve) {
      indice = normaliserIndice(trouve[1]);
      reste = reste.slice(0, trouve.index).trim();
      break;
    }
  }
  if (!FORMAT_INDICE.test(indice)) indice = "";
  // Un code sans espace et avec des chiffres ressemble au n° du cartouche (« EXE-08-PLB-003 »).
  const referenceEmetteur = /^[A-Z0-9][A-Z0-9._-]{3,}$/i.test(reste) && /\d/.test(reste) ? reste : "";
  const titre = reste.replace(/[_]+/g, " ").replace(/\s+/g, " ").trim() || base;
  return { base, extension, titre, indice, referenceEmetteur };
}

/** Rattache les fichiers sources (DWG…) au PDF de même nom : « Plan RDC.pdf » + « Plan RDC.dwg ». */
export function regrouperSources(fichiers: File[]): { principal: File; sources: File[] }[] {
  const groupes: { principal: File; sources: File[] }[] = [];
  const pdfParBase = new Map<string, { principal: File; sources: File[] }>();
  for (const fichier of fichiers) {
    if (fichier.name.toLowerCase().endsWith(".pdf")) {
      const groupe = { principal: fichier, sources: [] as File[] };
      groupes.push(groupe);
      pdfParBase.set(analyserNomFichier(fichier.name).base.toLowerCase(), groupe);
    }
  }
  for (const fichier of fichiers) {
    if (fichier.name.toLowerCase().endsWith(".pdf")) continue;
    const groupe = pdfParBase.get(analyserNomFichier(fichier.name).base.toLowerCase());
    if (groupe) groupe.sources.push(fichier);
    else groupes.push({ principal: fichier, sources: [] });
  }
  return groupes;
}

export const STYLE_STATUT: Record<StatutVersion, string> = {
  EN_VIGUEUR: "border-succes/40 bg-succes/10 text-succes",
  EN_EXAMEN: "border-info/40 bg-info/10 text-info",
  REFUSEE: "border-danger/50 bg-danger/10 text-danger",
  REMPLACEE: "border-bordure-forte bg-surface-2 text-attenue",
};

export const STYLE_VISA: Record<string, string> = {
  VSO: "text-succes",
  VAO: "text-accent",
  REF: "text-danger",
  HM: "text-attenue",
  EN_ATTENTE: "text-info",
  REMPLACE: "text-attenue",
};

export function derniere(document: DocumentGed): VersionGed | undefined {
  return document.versions[0];
}

export function formaterDateHeure(iso: string): string {
  return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function formaterJour(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [annee, mois, jour] = iso.slice(0, 10).split("-");
  return `${jour}/${mois}/${annee}`;
}

export function aujourdhuiIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export const messageErreur = (probleme: unknown, defaut: string) => (probleme instanceof Error ? probleme.message : defaut);

/** Identifiant d'un envoi groupé : les courriels de plusieurs fichiers déposés ensemble sont regroupés. */
export function identifiantDepot(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(8)), (o) => o.toString(16).padStart(2, "0")).join("");
}

export const CLASSE_BOUTON =
  "inline-flex min-h-10 items-center gap-2 rounded-lg border border-bordure-forte px-3 text-sm font-semibold text-texte no-underline hover:bg-surface-2 disabled:opacity-50";
export const CLASSE_BOUTON_PRINCIPAL =
  "inline-flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4 font-bold text-sur-accent no-underline hover:bg-accent-clair disabled:opacity-50";
