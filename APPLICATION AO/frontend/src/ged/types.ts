/** Données de la GED de chantier (communes au cabinet et au portail des intervenants). */

export type ZoneGed = "COMMUN" | "LOT" | "MOE";
export type StatutVersion = "EN_VIGUEUR" | "EN_EXAMEN" | "REFUSEE" | "REMPLACEE";
export type StatutVisa = "" | "EN_ATTENTE" | "VSO" | "VAO" | "REF" | "HM" | "REMPLACE";
export type Diffusion = "VISA" | "INFO" | "BPE";
export type StatutEspace = "OUVERT" | "RECEPTION" | "CLOS";
export type Frequence = "IMMEDIATE" | "QUOTIDIENNE" | "AUCUNE";
export type ProfilIntervenant = "ENTREPRISE" | "MOE_EXTERNE" | "MAITRE_OUVRAGE" | "CT" | "CSPS" | "OPC";

export interface LotCourt {
  id: number;
  code: string;
  intitule: string;
}

export interface AvisGed {
  id: number;
  role: string;
  role_libelle: string;
  avis: string;
  avis_libelle: string;
  observations: string;
  fichier: boolean;
  auteur: string;
  date: string;
}

export interface VersionGed {
  id: number;
  indice: string;
  date_indice: string | null;
  nom_original: string;
  taille: number;
  empreinte: string;
  objet: string;
  deposee_par: string;
  deposee_le: string;
  diffusion: Diffusion;
  diffusion_libelle: string;
  statut: StatutVersion;
  statut_libelle: string;
  visa: StatutVisa;
  visa_libelle: string;
  visa_commentaire: string;
  visa_fichier: boolean;
  fiche_visa: boolean;
  vise_par: string;
  vise_le: string | null;
  echeance_visa: string | null;
  visa_en_retard: boolean;
  jours_restants: number | null;
  nouvel_indice_attendu: boolean;
  nom_telechargement: string;
  indice_force: string;
  fichier_archive: boolean;
  sources: { id: number; nom_original: string; taille: number }[];
  avis: AvisGed[];
  peut_donner_avis: boolean;
  lecture_requise: boolean;
  accuses: { intervenant: string; lu_par: string; lu_le: string }[];
  lu_le: string | null;
  peut_accuser_lecture: boolean;
}

export interface DocumentGed {
  id: number;
  zone: ZoneGed;
  lot: LotCourt | null;
  categorie: string;
  categorie_libelle: string;
  confidentielle: boolean;
  reference: string;
  reference_emetteur: string;
  titre: string;
  auteur: string;
  cree_le: string;
  annule: boolean;
  motif_annulation: string;
  indice_en_vigueur: string | null;
  versions: VersionGed[];
  peut_ajouter_indice: boolean;
}

export interface DroitsGed {
  zones_visibles: ZoneGed[];
  lots: LotCourt[];
  mes_lots: LotCourt[];
  zones_depot: ZoneGed[];
  categories_depot: string[];
  lots_depot: LotCourt[];
  peut_viser: boolean;
  peut_donner_avis: boolean;
  choix_diffusion: boolean;
  cabinet: boolean;
  statut_espace: StatutEspace;
}

export interface CategorieGed {
  code: string;
  libelle: string;
  zone: "COMMUN" | "LOT";
  visa: boolean;
  confidentielle: boolean;
}

export interface Referentiels {
  categories: CategorieGed[];
  visas: { code: string; libelle: string }[];
  avis: { code: string; libelle: string }[];
  diffusions: { code: Diffusion; libelle: string }[];
  taille_max_mo: number;
}

export interface EvenementGed {
  id: number;
  type: string;
  type_libelle: string;
  date: string;
  acteur: string;
  description: string;
  document_id: number | null;
  adresse_ip?: string;
  notifie_le?: string | null;
}

export interface PageJournal {
  total: number;
  resultats: EvenementGed[];
}

export interface AccesGed {
  id: number;
  nom: string;
  email: string;
  frequence: Frequence;
  frequence_libelle: string;
  code_fin: string;
  code_genere_le: string;
  actif: boolean;
  dernier_acces: string | null;
}

export interface IntervenantGed {
  id: number;
  nom: string;
  profil: ProfilIntervenant;
  profil_libelle: string;
  entreprise_id: number | null;
  lots: LotCourt[];
  actif: boolean;
  acces: AccesGed[];
  sous_traitant_de: number | null;
  voit_confidentielles: boolean;
}

export interface EspaceGed {
  id: number;
  statut: StatutEspace;
  statut_libelle: string;
  ouvert_le: string;
  notifications: boolean;
  emails_moe: string[];
  message_accueil: string;
  delai_visa_jours: number;
  lecture_inter_lots: boolean;
  date_reception: string | null;
  intervenants: IntervenantGed[];
  lots_sans_entreprise: LotCourt[];
  droits: DroitsGed;
  statistiques: { documents: number; en_attente_visa: number; visas_en_retard: number; notifications_en_echec: number };
}

export interface SuggestionIntervenant {
  entreprise_id: number;
  nom: string;
  lots: LotCourt[];
  personnes: { nom: string; email: string }[];
}

export interface EtatGed extends Referentiels {
  projet: { id: number; nom: string; type_marche: string; maitre_ouvrage: string };
  espace: EspaceGed | null;
  suggestions: SuggestionIntervenant[];
  email_actif: boolean;
  url_publique: string;
}

export interface Invitation {
  acces_id: number;
  intervenant: string;
  nom: string;
  code: string;
  objet: string;
  message: string;
  lien: string;
  destinataire: string;
  envoye?: boolean;
  erreur_envoi?: string;
}

export interface EspacePortail extends Referentiels {
  projet: { nom: string; maitre_ouvrage: string; maitre_oeuvre: string; adresse_operation: string };
  intervenant: { nom: string; profil: ProfilIntervenant; profil_libelle: string; lots: LotCourt[] };
  personne: { nom: string; email: string; frequence: Frequence };
  statut_espace: StatutEspace;
  statut_libelle: string;
  message_accueil: string;
  delai_visa_jours: number;
  droits: DroitsGed;
  frequences: { code: Frequence; libelle: string }[];
}

export type StatutArchive = "EN_COURS" | "VERIFIEE" | "ERREUR";

export interface ArchiveProjet {
  id: number;
  projet_id: number | null;
  nom_projet: string;
  statut: StatutArchive;
  statut_libelle: string;
  message: string;
  nom_fichier: string;
  taille: number;
  empreinte: string;
  nb_fichiers: number;
  cree_le: string;
  terminee_le: string | null;
  telechargee_le: string | null;
  copie_confirmee_le: string | null;
  purge_prevue_le: string | null;
  fichiers_purges_le: string | null;
  octets_liberes: number;
  date_reception: string | null;
  conserver_jusqu_au: string | null;
  fichier_present: boolean;
  dossier: string;
}

export interface EtatArchives {
  archives: ArchiveProjet[];
  bilan: { octets: number; offres: number; prix_recus: number; entreprises: number; consultations: number; documents_ged: number; indices_ged: number };
  espace_libre: number | null;
  delai_purge_jours: number;
  est_administrateur: boolean;
}

export const PROFILS: { code: ProfilIntervenant; libelle: string }[] = [
  { code: "ENTREPRISE", libelle: "Entreprise (ses lots)" },
  { code: "MOE_EXTERNE", libelle: "Maîtrise d'œuvre associée (BET, architecte)" },
  { code: "MAITRE_OUVRAGE", libelle: "Maître d'ouvrage (lecture)" },
  { code: "CT", libelle: "Contrôleur technique" },
  { code: "CSPS", libelle: "Coordonnateur SPS" },
  { code: "OPC", libelle: "OPC (ordonnancement, pilotage)" },
];

export const FREQUENCES: { code: Frequence; libelle: string }[] = [
  { code: "IMMEDIATE", libelle: "À chaque nouveauté" },
  { code: "QUOTIDIENNE", libelle: "Récapitulatif quotidien" },
  { code: "AUCUNE", libelle: "Aucun courriel" },
];
