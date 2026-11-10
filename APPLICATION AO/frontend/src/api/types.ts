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

// --- Projets et pièces écrites (étape 1.2) ---

export type GenrePoste = "CHAPITRE" | "ARTICLE" | "OUVRAGE";
export type GenreOption = "PSE" | "VARIANTE";
export type Police = "Arial" | "Calibri" | "Times New Roman";

export interface ProjetResume {
  id: number;
  nom: string;
  numero: string;
  maitre_ouvrage: string;
  type_marche: "PUBLIC" | "PRIVE";
  phase: string;
  modifie_le: string;
  nb_lots: number;
}

export interface LotResume {
  id: number;
  code: string;
  intitule: string;
  nb_articles: number;
  nb_ouvrages: number;
  total_base: number;
}

export interface Projet {
  id: number;
  nom: string;
  numero: string;
  maitre_ouvrage: string;
  adresse_maitre_ouvrage: string;
  adresse_operation: string;
  maitre_oeuvre: string;
  type_marche: "PUBLIC" | "PRIVE";
  procedure: string;
  phase: string;
  indice: string;
  date_document: string | null;
  taux_tva: number | string;
  police: Police;
  taille_police: number;
  couleur_titres: string;
  couleur_tableaux: string;
  lots: LotResume[];
}

export interface OptionLot {
  id: number;
  genre: GenreOption;
  numero: number;
  libelle: string;
  nom_court: string;
  total: number;
}

export interface Poste {
  id: number;
  genre: GenrePoste;
  numero: string;
  titre: string;
  description: string;
  unite: string;
  quantite: number | null;
  prix_unitaire: number | null;
  montant: number | null;
  option_id: number | null;
  article_source_id: number | null;
}

export interface LotDetail {
  id: number;
  code: string;
  intitule: string;
  lot_id: number | null;
  projet: { id: number; nom: string; taux_tva: number };
  options: OptionLot[];
  postes: Poste[];
  total_base: number;
}

// --- Pièces administratives (étape 1.3) ---

export type TypePiece = "CCAP" | "RC" | "AE";
export type GenreClause = "CHAPITRE" | "ARTICLE";

export interface Critere {
  libelle: string;
  ponderation: number;
}

export interface Consultation {
  date_limite_offres: string | null;
  duree_validite_offres: number;
  delai_execution: string;
  date_debut_travaux: string;
  visite: "SANS_OBJET" | "FACULTATIVE" | "OBLIGATOIRE";
  modalites_visite: string;
  variantes_autorisees: boolean;
  forme_prix: "FERME_ACTUALISABLE" | "REVISABLE";
  index_reference: string;
  taux_retenue_garantie: number | string;
  taux_avance: number | string;
  penalites_retard: string;
  profil_acheteur: string;
  contact: string;
  criteres: Critere[];
}

export interface LotCourt {
  id: number;
  code: string;
  intitule: string;
}

export interface PieceResume {
  id: number;
  type_piece: TypePiece;
  titre: string;
  origine: string;
  lot: LotCourt | null;
  nb_clauses: number;
  modifie_le: string;
}

export interface Clause {
  id: number;
  genre: GenreClause;
  numero: string;
  titre: string;
  contenu: string;
  article_source_id: number | null;
}

export interface PieceDetail {
  id: number;
  type_piece: TypePiece;
  titre: string;
  origine: string;
  lot: LotCourt | null;
  projet: { id: number; nom: string; type_marche: "PUBLIC" | "PRIVE" };
  clauses: Clause[];
}

export interface Modele {
  id: string;
  nom: string;
  type_piece: TypePiece;
  marche: "PUBLIC" | "PRIVE";
  origine: "BASE" | "CABINET";
  nb_clauses: number;
}

export interface ChampPiece {
  cle: string;
  libelle: string;
  apercu: string;
  renseigne: boolean;
  bloc: boolean;
}

export const NOMS_PIECES: Record<TypePiece, string> = {
  CCAP: "CCAP",
  RC: "Règlement de consultation",
  AE: "Acte d'engagement",
};

// --- Assistant IA local (étape 1.4) ---

export interface SourceAssistant {
  numero: number;
  type: "ARTICLE" | "PRIX" | "MODELE";
  titre: string;
  detail: string;
  lien: string;
}

export interface MessageAssistant {
  id: number;
  role: "user" | "assistant";
  texte: string;
  sources: SourceAssistant[];
  interrompu: boolean;
  cree_le: string;
}

export interface ConversationResume {
  id: number;
  titre: string;
  projet: { id: number; nom: string } | null;
  modifie_le: string;
}

export interface ConversationDetail extends ConversationResume {
  messages: MessageAssistant[];
}

export interface EtatAssistant {
  moteur: {
    joignable: boolean;
    version: string | null;
    modele: string;
    modele_installe: boolean;
    embedding: string;
    embedding_installe: boolean;
  };
  voix: {
    transcription: string;
    transcription_installee: boolean;
    synthese: string;
    synthese_installee: boolean;
  };
  index: {
    passages: number;
    a_jour: number;
    en_cours: boolean;
    total: number;
    faits: number;
    message: string;
    fin: string | null;
  };
}

export type EvenementAssistant =
  | { type: "etape"; texte: string }
  | { type: "sources"; sources: SourceAssistant[] }
  | { type: "texte"; texte: string }
  | { type: "fin"; message_id: number | null }
  | { type: "erreur"; message: string };

// --- Annuaire des entreprises et DCE (étape 2) ---

export interface ContactEntreprise {
  id?: number | null;
  nom: string;
  fonction: string;
  email: string;
  telephone: string;
  principal: boolean;
}

export interface EntrepriseResume {
  id: number;
  raison_sociale: string;
  ville: string;
  code_postal: string;
  telephone: string;
  email: string;
  lots: Lot[];
  specialites: string;
  actif: boolean;
  contact_principal: string;
  nb_consultations: number;
  assurance_echue: boolean;
}

export interface ConsultationHistorique {
  projet_id: number;
  projet: string;
  lot: string;
  statut: StatutConsultation;
  statut_libelle: string;
  date: string | null;
}

export interface EntrepriseDetail {
  id: number;
  raison_sociale: string;
  siret: string;
  adresse: string;
  code_postal: string;
  ville: string;
  telephone: string;
  email: string;
  site_web: string;
  lots: Lot[];
  specialites: string;
  qualifications: string;
  zone_intervention: string;
  assureur_decennale: string;
  echeance_assurance: string | null;
  notes: string;
  actif: boolean;
  contacts: ContactEntreprise[];
  historique: ConsultationHistorique[];
}

export interface BilanImportEntreprises {
  creees: number;
  mises_a_jour: number;
  ignorees: string[];
  colonnes: Record<string, string>;
}

export type StatutConsultation = "A_CONSULTER" | "CONSULTEE" | "REPONDU" | "EXCUSEE" | "RETENUE" | "NON_RETENUE";

export const STATUTS_CONSULTATION: Record<StatutConsultation, string> = {
  A_CONSULTER: "À consulter",
  CONSULTEE: "Consultée",
  REPONDU: "A remis une offre",
  EXCUSEE: "S'est excusée",
  RETENUE: "Retenue",
  NON_RETENUE: "Non retenue",
};

export type CategoriePieceJointe = "PLANS" | "ETUDES" | "DIAGNOSTICS" | "SPS" | "AUTRES";

export const CATEGORIES_PIECES_JOINTES: Record<CategoriePieceJointe, string> = {
  PLANS: "Plans",
  ETUDES: "Études et rapports",
  DIAGNOSTICS: "Diagnostics",
  SPS: "Sécurité et santé (PGC)",
  AUTRES: "Autres documents",
};

export interface PointControle {
  niveau: "OK" | "ALERTE" | "MANQUE";
  texte: string;
  lien: string;
}

export interface PieceJointeDCE {
  id: number;
  categorie: CategoriePieceJointe;
  categorie_libelle: string;
  lot_id: number | null;
  lot: string | null;
  titre: string;
  nom_original: string;
  taille: number;
}

export interface DossierDCE {
  id: number;
  indice: string;
  entreprise: string | null;
  lots: string[];
  avec_word: boolean;
  statut: "EN_COURS" | "PRET" | "ERREUR";
  message: string;
  taille: number;
  nb_fichiers: number;
  contenu: { chemin: string; taille: number; designation: string }[];
  cree_le: string;
}

export interface ConsultationDCE {
  id: number;
  lot_id: number;
  entreprise_id: number;
  entreprise: string;
  email: string;
  statut: StatutConsultation;
  statut_libelle: string;
  consultee_le: string | null;
  commentaire: string;
}

export interface EnvoiDCE {
  id: number;
  type_envoi: "MOA" | "ENTREPRISE";
  entreprise: string | null;
  destinataires: string;
  objet: string;
  message: string;
  mode: "EMAIL" | "MANUEL";
  statut: "PREPARATION" | "A_ENVOYER" | "ENVOYE" | "ERREUR";
  statut_libelle: string;
  erreur: string;
  piece_jointe: boolean;
  dossier_id: number | null;
  envoye_le: string | null;
  cree_le: string;
}

export interface EtatDCE {
  type_marche: "PUBLIC" | "PRIVE";
  indice: string;
  email_actif: boolean;
  piece_jointe_max_mo: number;
  controle: PointControle[];
  pieces_jointes: PieceJointeDCE[];
  dossiers: DossierDCE[];
  consultations: ConsultationDCE[];
  envois: EnvoiDCE[];
}

// --- Étape 3 : analyse des offres -------------------------------------------

export type StatutLectureOffre = "EN_COURS" | "LUE" | "A_VERIFIER" | "NON_LUE" | "MANUELLE";
export type MethodePrix = "PROPORTIONNELLE" | "LINEAIRE";
export type JustificationPrix = "" | "DEMANDEE" | "ACCEPTEE" | "REJETEE";

export const JUSTIFICATIONS_PRIX: Record<JustificationPrix, string> = {
  "": "Pas encore de demande de précisions",
  DEMANDEE: "Précisions demandées à l'entreprise",
  ACCEPTEE: "Justifications jugées satisfaisantes",
  REJETEE: "Justifications insuffisantes : offre rejetée",
};

export interface NoteCritere {
  note: number | null;
  commentaire: string;
}

export interface OffreAnalyse {
  id: number;
  entreprise_id: number;
  entreprise: string;
  nom: string;
  variante: boolean;
  libelle_variante: string;
  recue_le: string;
  hors_delai: boolean;
  nom_original: string;
  a_un_fichier: boolean;
  statut_lecture: StatutLectureOffre;
  statut_libelle: string;
  message_lecture: string;
  montant_base: number | null;
  montant_base_calcule: number | null;
  montant_base_declare: number | null;
  montants_options: Record<string, number | null>;
  delai_propose: string;
  commentaire: string;
  ecartee: boolean;
  motif_ecart: string;
  notes: Record<string, NoteCritere>;
  justification_prix: JustificationPrix;
  motif_justification: string;
  prix: number | null;
  incomplete: boolean;
  anormalement_basse: boolean;
  ecart_estimation: number | null;
  ecart_moyenne: number | null;
  notes_calculees: Record<string, number | null>;
  total: number | null;
  rang: number | null;
  notation_complete: boolean;
  motif_non_classee: string;
  variante_sans_base: boolean;
}

export interface CritereAnalyse {
  libelle: string;
  ponderation: number;
  prix: boolean;
}

export interface LotAnalyse {
  id: number;
  code: string;
  intitule: string;
  options: {
    id: number;
    nom: string;
    libelle: string;
    genre: "PSE" | "VARIANTE";
  }[];
  estimation_base: number | null;
  estimation_options: Record<string, number | null>;
  variantes_autorisees: boolean;
  date_limite: string | null;
  analyse: {
    methode_prix: MethodePrix;
    bareme: number;
    seuil_anormal: number;
    options_retenues: number[];
    attributaire_id: number | null;
    observations: string;
    validee_le: string | null;
    proposee_id: number | null;
    choix_perime: boolean;
  };
  criteres: CritereAnalyse[];
  offres: OffreAnalyse[];
  consultees_sans_offre: {
    entreprise_id: number;
    entreprise: string;
    statut: StatutConsultation;
  }[];
}

export interface EtatOffres {
  type_marche: "PUBLIC" | "PRIVE";
  taux_tva: number;
  lots: LotAnalyse[];
}

export interface PrixOuvrageOffre {
  pu: number | null;
  montant: number | null;
  quantite: number | null;
}

export interface LigneComparatif {
  poste_id: number;
  numero: string;
  designation: string;
  unite: string;
  quantite: number | null;
  estimation_pu: number | null;
  estimation: number | null;
  offres: Record<string, PrixOuvrageOffre | null>;
  minimum: number | null;
  maximum: number | null;
}

export interface ComparatifLot {
  sections: {
    titre: string;
    option_id: number | null;
    estimation: number | null;
    chapitres: { numero: string; titre: string; lignes: LigneComparatif[] }[];
  }[];
  hors_dpgf: Record<string, { numero: string; designation: string; montant: number | null }[]>;
}

// --- Sauvegardes (GET /api/sauvegardes/etat, POST /api/sauvegardes) ---

export type StatutSauvegarde = "EN_COURS" | "REUSSIE" | "ECHEC";

/** Dernière sauvegarde lancée, quel que soit son résultat. */
export interface DerniereSauvegarde {
  debut: string;
  fin: string | null;
  statut: StatutSauvegarde;
  statut_libelle: string;
  /** Taille en octets de la copie de la base (0 tant que la copie n’est pas faite). */
  taille: number;
  /** Copie de la base vérifiée par une restauration d’essai. */
  verifiee: boolean;
  message: string;
}

export interface SauvegardeReussie {
  fin: string | null;
  /** Taille en octets de la copie de la base. */
  taille: number;
  verifiee: boolean;
}

export interface EtatSauvegardes {
  derniere: DerniereSauvegarde | null;
  derniere_reussie: SauvegardeReussie | null;
  en_cours: boolean;
  /** Dossier des sauvegardes tel qu’affiché (\\SERVEUR\DAplomb\sauvegardes, ou donnees\sauvegardes). */
  destination: string;
  /** Fichiers de l’application sur le serveur de l’agence (STOCKAGE_SERVEUR=1). */
  stockage_serveur: boolean;
  /** Vide si tout va bien ; sinon message(s) à afficher. */
  alerte: string;
  /** Heure de la sauvegarde de chaque nuit, ex. « 2 h 30 ». */
  heure: string;
}
