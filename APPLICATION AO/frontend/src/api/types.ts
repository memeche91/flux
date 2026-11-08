export type TypeDocument = "CCAP" | "AE" | "RC" | "CCTP" | "DPGF";
export type StatutAnalyse = "EN_ATTENTE" | "ANALYSE" | "NON_PRIS_EN_CHARGE" | "ERREUR";
export type TypeMarche = "" | "PUBLIC" | "PRIVE";

export interface Utilisateur {
  id: number;
  identifiant: string;
  nom_complet: string;
  role: "ADMIN" | "MOE" | "ENTREPRISE";
  role_libelle: string;
  est_administrateur: boolean;
}

export interface Lot {
  id: number;
  code: string;
  intitule: string;
}

export interface DocumentReference {
  id: number;
  type_document: TypeDocument;
  type_document_libelle: string;
  lot: Lot | null;
  nom_original: string;
  taille: number;
  operation: string;
  annee: number | null;
  type_marche: TypeMarche;
  type_marche_libelle: string;
  statut_analyse: StatutAnalyse;
  statut_analyse_libelle: string;
  message_analyse: string;
  ajoute_le: string;
  ajoute_par: string | null;
}

export interface Statistiques {
  total: number;
  par_type: Record<TypeDocument, number>;
  par_lot: Record<"CCTP" | "DPGF", Record<string, number>>;
}

export interface DescriptionType {
  code: TypeDocument;
  libelle: string;
  pluriel: string;
  parLot: boolean;
  description: string;
}

/** Ordre et libellés des pièces, tels qu'affichés dans l'application. */
export const TYPES_DOCUMENT: DescriptionType[] = [
  {
    code: "CCAP",
    libelle: "CCAP",
    pluriel: "CCAP",
    parLot: false,
    description: "Cahiers des clauses administratives particulières",
  },
  {
    code: "AE",
    libelle: "Acte d'engagement",
    pluriel: "Actes d'engagement",
    parLot: false,
    description: "Actes d'engagement et formulaires ATTRI1",
  },
  {
    code: "RC",
    libelle: "Règlement de consultation",
    pluriel: "Règlements de consultation",
    parLot: false,
    description: "Règlements de consultation",
  },
  {
    code: "CCTP",
    libelle: "CCTP",
    pluriel: "CCTP",
    parLot: true,
    description: "Cahiers des clauses techniques particulières, classés par lot",
  },
  {
    code: "DPGF",
    libelle: "DPGF",
    pluriel: "DPGF",
    parLot: true,
    description: "Décompositions du prix global et forfaitaire, classées par lot",
  },
];

export const FORMATS_ACCEPTES = ".pdf,.docx,.doc,.odt,.rtf,.xlsx,.xlsm,.xls,.ods,.csv";
