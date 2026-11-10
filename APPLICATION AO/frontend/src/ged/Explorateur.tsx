/** Explorateur des documents du chantier : classement par zone, lot et catégorie, indices,
 * visas et avis. Commun au cabinet et au portail des intervenants (droits fournis par le serveur). */
import { AlertTriangle, ChevronDown, ChevronRight, Clock, Download, Eye, FileSpreadsheet, Lock, RefreshCw, Upload } from "lucide-react";
import { memo, useCallback, useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { CLASSE_CHAMP, Champ, ChampRecherche } from "../components/Filtres";
import { formaterNombre } from "../lib/format";
import type { ClientGed } from "./client";
import Depot from "./Depot";
import FicheDocument from "./FicheDocument";
import { CLASSE_BOUTON, CLASSE_BOUTON_PRINCIPAL, derniere, formaterJour, messageErreur, STYLE_STATUT } from "./outils";
import type { DocumentGed, DroitsGed, Referentiels } from "./types";

type Vue = "tous" | "a_viser" | "retard" | "avis" | "en_attente" | "a_reprendre" | "a_lire" | "COMMUN" | "MOE" | `lot:${number}`;

/** Rendu progressif : monter 2 000 lignes d'un coup fige l'écran plusieurs secondes sur un PC
 * modeste ou une tablette de chantier. La liste est affichée par tranches de cette taille. */
const TRANCHE = 200;

const COLLATION = new Intl.Collator("fr", { numeric: true });

const sansAccents = (texte: string) =>
  texte
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();

/** Texte de recherche d'un document, calculé une fois par version de l'objet (un document modifié
 * est un nouvel objet). */
const textesRecherche = new WeakMap<DocumentGed, string>();
function texteRecherche(d: DocumentGed): string {
  let texte = textesRecherche.get(d);
  if (texte === undefined) {
    texte = sansAccents(`${d.reference} ${d.reference_emetteur} ${d.titre} ${d.categorie_libelle} ${d.auteur}`);
    textesRecherche.set(d, texte);
  }
  return texte;
}

interface Proprietes {
  client: ClientGed;
  droits: DroitsGed;
  referentiels: Referentiels;
  /** Document à ouvrir (lien direct d'un courriel). */
  documentOuvert: number | null;
  surOuvrir: (id: number | null) => void;
  /** Le cabinet est prévenu des changements (statistiques de l'espace). */
  surChangement?: () => void;
}

export default function Explorateur({ client, droits, referentiels, documentOuvert, surOuvrir, surChangement }: Proprietes) {
  const [documents, setDocuments] = useState<DocumentGed[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [vue, setVue] = useState<Vue>("tous");
  const [recherche, setRecherche] = useState("");
  const [categorie, setCategorie] = useState("");
  const [annules, setAnnules] = useState(false);
  const [depot, setDepot] = useState(false);
  const [chargement, setChargement] = useState(false);
  // La saisie reste fluide : le filtrage suit la frappe avec un temps de retard si besoin.
  const rechercheDifferee = useDeferredValue(recherche);

  // Nombre de documents affichés, remis à une tranche à chaque changement de classement ou de recherche
  // (ajustement pendant le rendu, sans passage intermédiaire par l'ancienne limite).
  const cleAffichage = `${vue}|${rechercheDifferee}|${categorie}|${annules}`;
  const [limite, setLimite] = useState(TRANCHE);
  const [cleLimite, setCleLimite] = useState(cleAffichage);
  if (cleLimite !== cleAffichage) {
    setCleLimite(cleAffichage);
    setLimite(TRANCHE);
  }

  // Fonction de bascule stable : les lignes mémoïsées ne sont pas redessinées à chaque rendu de la liste.
  const surOuvrirActuel = useRef(surOuvrir);
  useLayoutEffect(() => {
    surOuvrirActuel.current = surOuvrir;
  });

  const charger = useCallback(() => {
    setChargement(true);
    client
      .lister()
      .then((liste) => {
        setDocuments(liste);
        setErreur(null);
      })
      .catch((p: unknown) => setErreur(messageErreur(p, "Documents indisponibles.")))
      .finally(() => setChargement(false));
  }, [client]);

  useEffect(charger, [charger]);

  const majDocument = useCallback(
    (document: DocumentGed) => {
      setDocuments((liste) => {
        if (!liste) return [document];
        return liste.some((d) => d.id === document.id) ? liste.map((d) => (d.id === document.id ? document : d)) : [document, ...liste];
      });
      surChangement?.();
    },
    [surChangement],
  );

  const ordreCategories = useMemo(() => new Map(referentiels.categories.map((c, i) => [c.code, i])), [referentiels.categories]);
  const lotsParId = useMemo(() => new Map(droits.lots.map((l) => [l.id, l])), [droits.lots]);

  const compteurs = useMemo(() => {
    const liste = (documents ?? []).filter((d) => !d.annule);
    const dernieres = liste.map((d) => [d, derniere(d)] as const);
    return {
      a_viser: dernieres.filter(([, v]) => droits.peut_viser && v?.visa === "EN_ATTENTE").length,
      retard: dernieres.filter(([, v]) => droits.peut_viser && v?.visa === "EN_ATTENTE" && v.visa_en_retard).length,
      avis: liste.filter((d) => d.versions.some((v) => v.peut_donner_avis)).length,
      en_attente: dernieres.filter(([d, v]) => !droits.cabinet && d.peut_ajouter_indice && v?.visa === "EN_ATTENTE").length,
      a_reprendre: dernieres.filter(([d, v]) => !droits.cabinet && d.peut_ajouter_indice && v?.nouvel_indice_attendu).length,
      a_lire: liste.filter((d) => d.versions.some((v) => v.peut_accuser_lecture && !v.lu_le)).length,
    };
  }, [documents, droits]);

  // Lien direct (courriel, journal) : le document est affiché même s'il n'est pas dans la vue en
  // cours. Un document ouvert d'un clic dans la liste garde la vue choisie.
  const ouvertParClic = useRef<number | null>(null);
  const lienTraite = useRef<number | null>(null);
  const basculer = useCallback((id: number, ouvert: boolean) => {
    ouvertParClic.current = ouvert ? null : id;
    surOuvrirActuel.current(ouvertParClic.current);
  }, []);
  useEffect(() => {
    if (documentOuvert === null) {
      lienTraite.current = null;
      return;
    }
    if (!documents || lienTraite.current === documentOuvert) return;
    const cible = documents.find((d) => d.id === documentOuvert);
    if (!cible) return;
    lienTraite.current = documentOuvert;
    if (ouvertParClic.current === documentOuvert) return;
    setVue("tous");
    setRecherche("");
    setCategorie("");
    const minuterie = window.setTimeout(
      () => document.getElementById(`document-${documentOuvert}`)?.scrollIntoView({ block: "start", behavior: "smooth" }),
      50,
    );
    return () => window.clearTimeout(minuterie);
  }, [documentOuvert, documents]);

  const visibles = useMemo(() => {
    const terme = sansAccents(rechercheDifferee.trim());
    return (documents ?? [])
      .filter((d) => {
        // Le document ouvert reste affiché (après un visa, il quitte la vue « À viser »).
        if (d.id === documentOuvert) return true;
        const v = derniere(d);
        if (d.annule && !annules) return false;
        if (categorie && d.categorie !== categorie) return false;
        if (terme && !texteRecherche(d).includes(terme)) return false;
        switch (vue) {
          case "tous":
            return true;
          case "a_viser":
            return v?.visa === "EN_ATTENTE";
          case "retard":
            return v?.visa === "EN_ATTENTE" && v.visa_en_retard;
          case "avis":
            return d.versions.some((x) => x.peut_donner_avis);
          case "en_attente":
            return d.peut_ajouter_indice && v?.visa === "EN_ATTENTE";
          case "a_reprendre":
            return d.peut_ajouter_indice && Boolean(v?.nouvel_indice_attendu);
          case "a_lire":
            return d.versions.some((x) => x.peut_accuser_lecture && !x.lu_le);
          case "COMMUN":
          case "MOE":
            return d.zone === vue;
          default:
            return d.zone === "LOT" && `lot:${d.lot?.id}` === vue;
        }
      })
      .sort((a, b) => {
        if (vue === "a_viser" || vue === "retard") {
          return (derniere(a)?.echeance_visa ?? "9999").localeCompare(derniere(b)?.echeance_visa ?? "9999");
        }
        // Commun, puis les lots dans l'ordre de leur code, puis la maîtrise d'œuvre (ordre du menu). Le rang
        // de zone est comparé à part : en tri numérique, « 2 » passerait avant « 101 » (lot 01).
        const rangZone = (d: DocumentGed) => (d.zone === "COMMUN" ? 0 : d.zone === "LOT" ? 1 : 2);
        return (
          rangZone(a) - rangZone(b) ||
          COLLATION.compare(a.lot?.code ?? "", b.lot?.code ?? "") ||
          (ordreCategories.get(a.categorie) ?? 99) - (ordreCategories.get(b.categorie) ?? 99) ||
          COLLATION.compare(a.reference, b.reference)
        );
      });
  }, [documents, vue, rechercheDifferee, categorie, annules, ordreCategories, documentOuvert]);

  // Documents montés : la tranche en cours, plus le document ouvert s'il est plus loin dans la liste
  // (lien direct d'un courriel ou du journal) : il est alors affiché à la suite de la tranche.
  const affiches = useMemo(() => {
    if (visibles.length <= limite) return visibles;
    const tranche = visibles.slice(0, limite);
    if (documentOuvert !== null && !tranche.some((d) => d.id === documentOuvert)) {
      const ouvert = visibles.find((d) => d.id === documentOuvert);
      if (ouvert) tranche.push(ouvert);
    }
    return tranche;
  }, [visibles, limite, documentOuvert]);
  const restants = visibles.length - affiches.length;

  // Intertitres : par zone et lot dans « Tous », par catégorie dans un lot.
  const groupes = useMemo(() => {
    const resultat: { base: string; cle: string; titre: string; documents: DocumentGed[] }[] = [];
    const parCategorie = vue === "COMMUN" || vue === "MOE" || vue.startsWith("lot:");
    const vus = new Map<string, number>();
    for (const d of affiches) {
      let cle = "";
      let titre = "";
      if (vue === "tous") {
        cle = d.zone === "LOT" ? `lot:${d.lot?.id}` : d.zone;
        titre = d.zone === "COMMUN" ? "Commun à tous" : d.zone === "MOE" ? "Maîtrise d'œuvre (réservé)" : `Lot ${d.lot?.code} – ${d.lot?.intitule}`;
      } else if (parCategorie) {
        cle = d.categorie;
        titre = d.categorie_libelle;
      }
      const dernier = resultat[resultat.length - 1];
      if (dernier && dernier.base === cle) {
        dernier.documents.push(d);
      } else {
        // Clé React unique, même si un intertitre revient plus bas.
        const occurrences = vus.get(cle) ?? 0;
        vus.set(cle, occurrences + 1);
        resultat.push({ base: cle, cle: occurrences ? `${cle}#${occurrences}` : cle, titre, documents: [d] });
      }
    }
    return resultat;
  }, [affiches, vue]);

  const entreesVues: { vue: Vue; libelle: string; nombre?: number; alerte?: boolean }[] = [
    ...(compteurs.a_viser || vue === "a_viser" ? [{ vue: "a_viser" as Vue, libelle: "À viser", nombre: compteurs.a_viser }] : []),
    ...(compteurs.retard || vue === "retard" ? [{ vue: "retard" as Vue, libelle: "Visas en retard", nombre: compteurs.retard, alerte: true }] : []),
    ...(compteurs.avis || vue === "avis" ? [{ vue: "avis" as Vue, libelle: "Avis à donner", nombre: compteurs.avis }] : []),
    ...(compteurs.a_reprendre || vue === "a_reprendre"
      ? [{ vue: "a_reprendre" as Vue, libelle: "À reprendre (nouvel indice)", nombre: compteurs.a_reprendre, alerte: true }]
      : []),
    ...(compteurs.en_attente || vue === "en_attente" ? [{ vue: "en_attente" as Vue, libelle: "En attente de visa", nombre: compteurs.en_attente }] : []),
    ...(compteurs.a_lire || vue === "a_lire" ? [{ vue: "a_lire" as Vue, libelle: "À lire (accusé demandé)", nombre: compteurs.a_lire, alerte: true }] : []),
  ];
  // Nombres par zone et catégories présentes : un seul passage sur la liste.
  const repartition = useMemo(() => {
    const parZone = new Map<string, number>();
    const categories = new Set<string>();
    let tous = 0;
    for (const d of documents ?? []) {
      categories.add(d.categorie);
      if (d.annule) continue;
      tous += 1;
      const cle = d.zone === "LOT" ? `lot:${d.lot?.id}` : d.zone;
      parZone.set(cle, (parZone.get(cle) ?? 0) + 1);
    }
    return { tous, parZone, categories };
  }, [documents]);
  const entreesZones: { vue: Vue; libelle: string; nombre: number; mien?: boolean }[] = [
    { vue: "COMMUN", libelle: "Commun à tous", nombre: repartition.parZone.get("COMMUN") ?? 0 },
    ...droits.lots.map((l) => ({
      vue: `lot:${l.id}` as Vue,
      libelle: `${l.code} – ${l.intitule}`,
      nombre: repartition.parZone.get(`lot:${l.id}`) ?? 0,
      mien: droits.mes_lots.some((m) => m.id === l.id),
    })),
    ...(droits.zones_visibles.includes("MOE")
      ? [{ vue: "MOE" as Vue, libelle: "Maîtrise d'œuvre (réservé)", nombre: repartition.parZone.get("MOE") ?? 0 }]
      : []),
  ];
  const categoriesPresentes = referentiels.categories.filter((c) => repartition.categories.has(c.code));
  const lotVue = vue.startsWith("lot:") ? lotsParId.get(Number(vue.slice(4))) : undefined;
  // Pas de bouton « Déposer » sans catégorie permise (CT, OPC après la réception).
  const peutDeposer = droits.zones_depot.length > 0 && droits.categories_depot.length > 0;

  return (
    <div className="flex flex-col gap-4">
      {depot && (
        <Depot
          client={client}
          droits={droits}
          referentiels={referentiels}
          documents={documents ?? []}
          zoneInitiale={vue === "COMMUN" || vue === "MOE" ? vue : lotVue ? "LOT" : undefined}
          lotInitial={lotVue?.id}
          surDepose={majDocument}
          surFermer={() => setDepot(false)}
        />
      )}

      <div className="grid gap-5 lg:grid-cols-[250px_minmax(0,1fr)]">
        <nav aria-label="Classement des documents" className="flex flex-col gap-4">
          {peutDeposer && !depot && (
            <button type="button" onClick={() => setDepot(true)} className={`${CLASSE_BOUTON_PRINCIPAL} justify-center`}>
              <Upload aria-hidden="true" className="size-4" />
              Déposer des documents
            </button>
          )}
          {entreesVues.length > 0 && (
            <ul className="flex flex-col gap-1 rounded-xl border border-attention/30 bg-attention/5 p-2">
              {entreesVues.map((e) => (
                <li key={e.vue}>
                  <BoutonVue actif={vue === e.vue} surClic={() => setVue(e.vue)} libelle={e.libelle} nombre={e.nombre} alerte={e.alerte} />
                </li>
              ))}
            </ul>
          )}
          <ul className="flex flex-col gap-1 rounded-xl border border-bordure bg-surface p-2">
            <li>
              <BoutonVue actif={vue === "tous"} surClic={() => setVue("tous")} libelle="Tous les documents" nombre={repartition.tous} />
            </li>
            {entreesZones.map((e) => (
              <li key={e.vue}>
                <BoutonVue actif={vue === e.vue} surClic={() => setVue(e.vue)} libelle={e.libelle} nombre={e.nombre} mien={e.mien} />
              </li>
            ))}
          </ul>
          <a href={client.urlRegistre()} className={`${CLASSE_BOUTON} justify-center`}>
            <FileSpreadsheet aria-hidden="true" className="size-4" />
            Registre des documents (Excel)
          </a>
        </nav>

        <section aria-label="Documents" className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <ChampRecherche
              id="ged-recherche"
              libelle="Rechercher"
              valeur={recherche}
              surChangement={setRecherche}
              indication="Référence, n° de plan, titre…"
            />
            <Champ id="ged-categorie" libelle="Catégorie">
              <select id="ged-categorie" value={categorie} onChange={(e) => setCategorie(e.target.value)} className={CLASSE_CHAMP}>
                <option value="">Toutes</option>
                {categoriesPresentes.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.libelle}
                  </option>
                ))}
              </select>
            </Champ>
            <label className="flex min-h-11 items-center gap-2 text-attenue">
              <input type="checkbox" checked={annules} onChange={(e) => setAnnules(e.target.checked)} className="size-4 accent-accent" />
              Documents annulés
            </label>
            <button type="button" onClick={charger} disabled={chargement} className={CLASSE_BOUTON} aria-label="Actualiser la liste">
              <RefreshCw aria-hidden="true" className={`size-4 ${chargement ? "animate-spin" : ""}`} />
            </button>
          </div>

          {erreur && (
            <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
              {erreur}
            </p>
          )}
          {!documents ? (
            <p className="text-attenue">Chargement des documents…</p>
          ) : visibles.length === 0 ? (
            <p className="rounded-xl border border-bordure bg-surface px-5 py-6 text-attenue">
              {documents.length === 0
                ? peutDeposer
                  ? "Aucun document pour l'instant : déposez le premier."
                  : "Aucun document pour l'instant. Vous serez prévenu par courriel dès qu'un document sera déposé."
                : "Aucun document ne correspond à ce classement ou à cette recherche."}
            </p>
          ) : (
            <>
              {groupes.map((groupe) => (
                <div key={groupe.cle || "liste"} className="flex flex-col gap-2">
                  {groupe.titre && <h3 className="mt-2 font-titre text-base font-semibold text-attenue">{groupe.titre}</h3>}
                  <ul className="flex flex-col gap-2">
                    {groupe.documents.map((d) => (
                      <LigneDocument
                        key={d.id}
                        document={d}
                        ouvert={documentOuvert === d.id}
                        surBascule={basculer}
                        client={client}
                        droits={droits}
                        referentiels={referentiels}
                        surMaj={majDocument}
                      />
                    ))}
                  </ul>
                </div>
              ))}
              {restants > 0 && (
                <div className="flex flex-wrap items-center gap-3 rounded-xl border border-bordure bg-surface px-4 py-3">
                  <p role="status" className="min-w-0 flex-[1_1_260px] text-sm text-attenue">
                    {formaterNombre(affiches.length)} documents affichés sur {formaterNombre(visibles.length)}. La recherche et le classement portent sur tous
                    les documents.
                  </p>
                  <button type="button" onClick={() => setLimite((l) => l + TRANCHE)} className={CLASSE_BOUTON}>
                    <ChevronDown aria-hidden="true" className="size-4" />
                    Afficher {restants > TRANCHE ? `les ${formaterNombre(TRANCHE)} suivants` : restants > 1 ? `les ${restants} derniers` : "le dernier"}
                  </button>
                  <button type="button" onClick={() => setLimite(Number.POSITIVE_INFINITY)} className={CLASSE_BOUTON}>
                    Tout afficher ({formaterNombre(visibles.length)})
                  </button>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function BoutonVue({
  actif,
  surClic,
  libelle,
  nombre,
  alerte,
  mien,
}: {
  actif: boolean;
  surClic: () => void;
  libelle: string;
  nombre?: number;
  alerte?: boolean;
  mien?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={surClic}
      aria-current={actif ? "true" : undefined}
      className={`flex min-h-10 w-full items-center justify-between gap-2 rounded-lg px-3 text-left ${actif ? "bg-surface-2 font-semibold text-white" : "text-attenue hover:bg-surface-2 hover:text-texte"}`}
    >
      <span className="min-w-0 truncate">
        {libelle}
        {mien && <span className="ml-1.5 text-xs text-accent">(mon lot)</span>}
      </span>
      {nombre !== undefined && <span className={`text-xs tabular-nums ${alerte ? "font-bold text-danger" : ""}`}>{nombre}</span>}
    </button>
  );
}

interface ProprietesLigne {
  document: DocumentGed;
  ouvert: boolean;
  /** Fonction stable (commune à toutes les lignes) : ouvre ou referme la fiche du document. */
  surBascule: (id: number, ouvert: boolean) => void;
  client: ClientGed;
  droits: DroitsGed;
  referentiels: Referentiels;
  surMaj: (document: DocumentGed) => void;
}

/** Ligne mémoïsée : seules les lignes dont le document ou l'état d'ouverture change sont redessinées
 * (les autres propriétés sont stables). */
const LigneDocument = memo(function LigneDocument({ document: d, ouvert, surBascule, client, droits, referentiels, surMaj }: ProprietesLigne) {
  const v = derniere(d);
  const enVigueur = d.versions.find((x) => x.statut === "EN_VIGUEUR");
  const aLire = d.versions.some((x) => x.peut_accuser_lecture && !x.lu_le);
  const Chevron = ouvert ? ChevronDown : ChevronRight;
  return (
    <li id={`document-${d.id}`} className={`scroll-mt-4 rounded-xl border bg-surface ${ouvert ? "border-accent/50" : "border-bordure"}`}>
      <div className="flex items-center gap-1 pr-2">
        <button
          type="button"
          onClick={() => surBascule(d.id, ouvert)}
          aria-expanded={ouvert}
          className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 text-left"
        >
          <Chevron aria-hidden="true" className="size-4 shrink-0 text-attenue" />
          <span className="flex w-40 shrink-0 flex-col">
            <span className="font-mono text-sm font-semibold text-accent">{d.reference}</span>
            {d.reference_emetteur && <span className="truncate text-xs text-attenue">{d.reference_emetteur}</span>}
          </span>
          <span className="flex min-w-0 flex-[1_1_240px] flex-col">
            <span className={`font-semibold ${d.annule ? "text-attenue line-through" : ""}`}>
              {d.confidentielle && <Lock aria-label="Document confidentiel" className="mr-1.5 inline size-3.5 text-attenue" />}
              {d.titre}
            </span>
            <span className="text-xs text-attenue">
              {d.categorie_libelle}
              {d.lot ? ` · lot ${d.lot.code}` : ""} · {d.auteur}
            </span>
          </span>
          <span className="flex flex-wrap items-center gap-1.5">
            {d.annule ? (
              <span className="rounded-full border border-danger/40 bg-danger/10 px-2.5 py-0.5 text-xs font-semibold text-danger">Annulé</span>
            ) : enVigueur ? (
              <span className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${STYLE_STATUT.EN_VIGUEUR}`}>À utiliser : ind. {enVigueur.indice}</span>
            ) : (
              <span className="rounded-full border border-bordure-forte px-2.5 py-0.5 text-xs text-attenue">Aucun indice à utiliser</span>
            )}
            {!d.annule && v && v.statut !== "EN_VIGUEUR" && v.statut !== "REMPLACEE" && (
              <span className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${STYLE_STATUT[v.statut]}`}>
                Ind. {v.indice} {v.statut === "REFUSEE" ? "refusé" : "en examen"}
              </span>
            )}
            {!d.annule && v?.visa === "EN_ATTENTE" && v.echeance_visa && (
              <span className={`inline-flex items-center gap-1 text-xs ${v.visa_en_retard ? "font-bold text-danger" : "text-attenue"}`}>
                {v.visa_en_retard ? <AlertTriangle aria-hidden="true" className="size-3.5" /> : <Clock aria-hidden="true" className="size-3.5" />}
                {v.visa_en_retard ? `visa en retard (${formaterJour(v.echeance_visa)})` : `visa avant le ${formaterJour(v.echeance_visa)}`}
              </span>
            )}
            {!d.annule && v?.nouvel_indice_attendu && d.peut_ajouter_indice && !droits.cabinet && (
              <span className="rounded-full border border-attention/50 bg-attention/10 px-2.5 py-0.5 text-xs font-semibold text-attention">
                Nouvel indice attendu
              </span>
            )}
            {aLire && (
              <span className="inline-flex items-center gap-1 rounded-full border border-attention/50 bg-attention/10 px-2.5 py-0.5 text-xs font-semibold text-attention">
                <Eye aria-hidden="true" className="size-3.5" />À lire
              </span>
            )}
          </span>
        </button>
        {enVigueur && !enVigueur.fichier_archive && !ouvert && !d.annule && (
          <a
            href={client.urlVersion(enVigueur.id, "fichier")}
            target="_blank"
            rel="noopener"
            className="grid size-10 shrink-0 place-items-center rounded-lg text-attenue hover:bg-surface-2 hover:text-texte"
            aria-label={`Ouvrir l'indice ${enVigueur.indice} à utiliser de ${d.reference}`}
            title={enVigueur.nom_telechargement}
          >
            <Download aria-hidden="true" className="size-4" />
          </a>
        )}
      </div>
      {ouvert && <FicheDocument document={d} client={client} droits={droits} referentiels={referentiels} surMaj={surMaj} />}
    </li>
  );
});
