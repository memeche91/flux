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
  nb_articles: number;
  nb_lignes_prix: number;
}

export interface Statistiques {
  total: number;
  par_type: Record<TypeDocument, number>;
  par_lot: Record<"CCTP" | "DPGF", Record<string, number>>;
  articles: number;
  lignes_prix: number;
  lignes_chiffrees: number;
}

export type Categorie = "GENERALITES" | "OUVRAGE" | "CLAUSE";

export interface DocumentSource {
  id: number;
  nom_original: string;
  type_document: TypeDocument;
  operation: string;
  annee: number | null;
}

export interface Article {
  id: number;
  numero: string;
  titre: string;
  chemin: string;
  niveau: number;
  contenu: string;
  categorie: Categorie;
  categorie_libelle: string;
  references_normatives: string[];
  lot: Lot | null;
  document: DocumentSource;
}

export interface PageArticles {
  total: number;
  resultats: Article[];
}

export interface ReferenceCitee {
  reference: string;
  nombre: number;
}

export interface LignePrix {
  id: number;
  numero: string;
  chapitre: string;
  designation: string;
  unite: string;
  unite_normalisee: string;
  quantite: number | null;
  prix_unitaire: number | null;
  montant: number | null;
  lot: Lot | null;
  document: DocumentSource;
}

export interface StatistiqueUnite {
  unite: string;
  nombre: number;
  minimum: number;
  mediane: number;
  maximum: number;
}

export interface PagePrix {
  total: number;
  unites: string[];
  statistiques: StatistiqueUnite[];
  resultats: LignePrix[];
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
