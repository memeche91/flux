import { Check, Copy, Download, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";

import type { Article, Categorie, Lot, PageArticles, ReferenceCitee, TypeDocument } from "../api/types";
import EnTetePage from "../components/EnTetePage";
import { BoutonAfficherPlus, CLASSE_CHAMP, Champ, ChampRecherche, delaiSaisie } from "../components/Filtres";
import { formaterNombre, origineDocument, pluriel } from "../lib/format";
import { usePagination } from "../lib/usePagination";
import { useRequete } from "../lib/useRequete";

const TYPES: { code: TypeDocument; libelle: string; mot: string }[] = [
  { code: "CCTP", libelle: "CCTP", mot: "article" },
  { code: "CCAP", libelle: "CCAP", mot: "clause" },
  { code: "RC", libelle: "Règlement de consultation", mot: "clause" },
  { code: "AE", libelle: "Acte d'engagement", mot: "clause" },
];

const STYLE_CATEGORIE: Record<Categorie, string> = {
  GENERALITES: "bg-info/12 text-info",
  OUVRAGE: "bg-succes/12 text-succes",
  CLAUSE: "bg-surface-2 text-attenue",
};

export default function Articles() {
  const [parametres, setParametres] = useSearchParams();
  const type = TYPES.find((t) => t.code === parametres.get("type")) ?? TYPES[0];
  const lotId = parametres.get("lot") ?? "";
  const categorie = parametres.get("categorie") ?? "";
  const reference = parametres.get("reference") ?? "";
  const documentId = parametres.get("document") ?? "";

  const [recherche, setRecherche] = useState(parametres.get("q") ?? "");
  const [rechercheAppliquee, setRechercheAppliquee] = useState(recherche);
  useEffect(() => delaiSaisie(() => setRechercheAppliquee(recherche.trim())), [recherche]);

  const modifier = (cle: string, valeur: string) => {
    const suivants = new URLSearchParams(parametres);
    if (valeur) suivants.set(cle, valeur);
    else suivants.delete(cle);
    setParametres(suivants, { replace: true });
  };

  const filtres = new URLSearchParams({ type_document: type.code });
  if (type.code === "CCTP" && lotId) filtres.set("lot_id", lotId);
  if (type.code === "CCTP" && categorie) filtres.set("categorie", categorie);
  if (reference) filtres.set("reference", reference);
  if (documentId) filtres.set("document_id", documentId);
  if (rechercheAppliquee) filtres.set("recherche", rechercheAppliquee);

  const lots = useRequete<Lot[]>("/referentiel/lots");
  const references = useRequete<ReferenceCitee[]>(
    `/articles/references?type_document=${type.code}${type.code === "CCTP" && lotId ? `&lot_id=${lotId}` : ""}`,
  );
  const liste = usePagination<Article, PageArticles>(`/articles?${filtres}`);
  const documentFiltre = documentId ? liste.elements.find((a) => String(a.document.id) === documentId)?.document : undefined;

  return (
    <>
      <EnTetePage
        surtitre="Étape 1 · Pièces écrites"
        titre="Bibliothèque d'articles"
        sousTitre="Les articles et clauses découpés automatiquement dans vos documents. Ils serviront de base à la rédaction de vos prochaines pièces écrites."
      />

      <div role="tablist" aria-label="Type de document" className="flex flex-wrap gap-1 border-b border-bordure">
        {TYPES.map((t) => {
          const actif = t.code === type.code;
          return (
            <button
              key={t.code}
              role="tab"
              type="button"
              aria-selected={actif}
              onClick={() => setParametres({ type: t.code })}
              className={`-mb-px flex min-h-11 items-center border-b-2 px-4 font-semibold transition-colors ${
                actif ? "border-accent text-white" : "border-transparent text-attenue hover:text-texte"
              }`}
            >
              {t.libelle}
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-bordure bg-surface p-4">
        <ChampRecherche
          id="recherche-articles"
          libelle="Rechercher"
          valeur={recherche}
          surChangement={setRecherche}
          indication="Ex. châssis aluminium, pénalités, garantie…"
        />
        {type.code === "CCTP" && (
          <>
            <Champ id="filtre-lot-articles" libelle="Lot">
              <select id="filtre-lot-articles" value={lotId} onChange={(e) => modifier("lot", e.target.value)} className={CLASSE_CHAMP}>
                <option value="">Tous les lots</option>
                {(lots.donnees ?? []).map((lot) => (
                  <option key={lot.id} value={lot.id}>
                    {lot.code} – {lot.intitule}
                  </option>
                ))}
              </select>
            </Champ>
            <Champ id="filtre-categorie" libelle="Catégorie">
              <select id="filtre-categorie" value={categorie} onChange={(e) => modifier("categorie", e.target.value)} className={CLASSE_CHAMP}>
                <option value="">Toutes</option>
                <option value="GENERALITES">Généralités</option>
                <option value="OUVRAGE">Ouvrages</option>
              </select>
            </Champ>
          </>
        )}
        <Champ id="filtre-reference" libelle="Norme ou DTU cité">
          <select id="filtre-reference" value={reference} onChange={(e) => modifier("reference", e.target.value)} className={CLASSE_CHAMP}>
            <option value="">Toutes</option>
            {(references.donnees ?? []).map((r) => (
              <option key={r.reference} value={r.reference}>
                {r.reference} ({r.nombre})
              </option>
            ))}
          </select>
        </Champ>
      </div>

      {documentId && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-attenue">Document :</span>
          <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 py-1 pr-1 pl-3">
            {documentFiltre?.nom_original ?? `n° ${documentId}`}
            <button
              type="button"
              onClick={() => modifier("document", "")}
              aria-label="Retirer le filtre sur ce document"
              className="grid size-8 place-items-center rounded-full hover:bg-bordure-forte"
            >
              <X aria-hidden="true" className="size-4" />
            </button>
          </span>
        </div>
      )}

      {liste.erreur && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-danger">
          {liste.erreur}
        </p>
      )}

      <div className="flex flex-wrap items-start gap-5">
        <section aria-labelledby="titre-resultats-articles" className="flex min-w-0 flex-[999_1_560px] flex-col gap-3">
          <h2 id="titre-resultats-articles" className="font-titre text-lg font-semibold" aria-live="polite">
            {liste.donnees ? pluriel(liste.total, type.mot) : "Chargement…"}
          </h2>
          {liste.donnees && liste.total === 0 && (
            <p className="rounded-xl border border-bordure bg-surface px-5 py-6 text-attenue">
              Aucun résultat.{" "}
              {!rechercheAppliquee && !reference && !documentId && (
                <>
                  Importez des documents dans la{" "}
                  <Link to={`/bibliotheque?type=${type.code}`} className="text-accent">
                    bibliothèque documentaire
                  </Link>{" "}
                  : ils seront découpés automatiquement.
                </>
              )}
            </p>
          )}
          <ul className="flex flex-col gap-2">
            {liste.elements.map((article) => (
              <li key={article.id}>
                <CarteArticle article={article} surReference={(r) => modifier("reference", r)} />
              </li>
            ))}
          </ul>
          <BoutonAfficherPlus reste={liste.reste} chargement={liste.chargement} surClic={() => void liste.afficherPlus()} />
        </section>

        {(references.donnees?.length ?? 0) > 0 && (
          <aside
            aria-labelledby="titre-references"
            className="hidden min-w-0 flex-[1_1_280px] flex-col gap-2 rounded-xl border border-bordure bg-surface p-4 lg:flex"
          >
            <h2 id="titre-references" className="font-titre text-base font-semibold">
              Normes et DTU cités
            </h2>
            <p className="text-xs text-attenue">Relevés dans vos propres documents. Vérifiez la version en vigueur avant réutilisation.</p>
            <ul className="flex flex-col">
              {references.donnees!.slice(0, 20).map((r) => (
                <li key={r.reference}>
                  <button
                    type="button"
                    onClick={() => modifier("reference", reference === r.reference ? "" : r.reference)}
                    aria-pressed={reference === r.reference}
                    className={`flex min-h-11 w-full items-center justify-between gap-2 rounded-lg px-2.5 text-left ${
                      reference === r.reference ? "bg-surface-2 text-white" : "hover:bg-surface-2/60"
                    }`}
                  >
                    <span>{r.reference}</span>
                    <span className="text-xs text-attenue tabular-nums">{formaterNombre(r.nombre)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </aside>
        )}
      </div>
    </>
  );
}

function CarteArticle({ article, surReference }: { article: Article; surReference: (reference: string) => void }) {
  const [copie, setCopie] = useState(false);

  async function copier() {
    const texte = `${[article.numero, article.titre].filter(Boolean).join(" ")}\n${article.contenu}`;
    const reussi = await copierTexte(texte);
    if (reussi) {
      setCopie(true);
      window.setTimeout(() => setCopie(false), 2000);
    }
  }

  return (
    <details className="group rounded-xl border border-bordure bg-surface open:border-bordure-forte">
      <summary className="flex min-h-11 cursor-pointer list-none flex-col gap-1 px-4 py-3 marker:hidden hover:bg-surface-2/40">
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
          {article.numero && <span className="font-titre font-semibold text-accent">{article.numero}</span>}
          <span className="min-w-0 flex-1 font-semibold">{article.titre}</span>
          <span className="flex flex-wrap gap-1.5">
            {article.lot && (
              <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs font-semibold text-accent" title={article.lot.intitule}>
                Lot {article.lot.code}
              </span>
            )}
            <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STYLE_CATEGORIE[article.categorie]}`}>
              {article.categorie_libelle}
            </span>
          </span>
        </div>
        {article.chemin && <span className="text-xs text-attenue">{article.chemin}</span>}
        <span className="text-xs text-attenue">
          {origineDocument(article.document)} · {article.document.nom_original}
        </span>
        <span className="line-clamp-2 text-attenue group-open:hidden">{article.contenu}</span>
      </summary>

      <div className="flex flex-col gap-3 border-t border-bordure px-4 py-4">
        <p className="leading-relaxed whitespace-pre-line">{article.contenu}</p>
        {article.references_normatives.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-attenue">Références :</span>
            {article.references_normatives.map((reference) => (
              <button
                key={reference}
                type="button"
                onClick={() => surReference(reference)}
                className="min-h-8 rounded-full border border-bordure-forte px-2.5 text-xs hover:bg-surface-2"
              >
                {reference}
              </button>
            ))}
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void copier()}
            className="flex min-h-11 items-center gap-2 rounded-lg border border-bordure-forte px-3 hover:bg-surface-2"
          >
            {copie ? <Check aria-hidden="true" className="size-4 text-succes" /> : <Copy aria-hidden="true" className="size-4" />}
            {copie ? "Copié" : "Copier le texte"}
          </button>
          <a
            href={`/api/bibliotheque/documents/${article.document.id}/telecharger`}
            className="flex min-h-11 items-center gap-2 rounded-lg border border-bordure-forte px-3 text-texte no-underline hover:bg-surface-2"
          >
            <Download aria-hidden="true" className="size-4" />
            Document source
          </a>
        </div>
      </div>
    </details>
  );
}

/** Copie dans le presse-papiers, y compris hors HTTPS (accès par adresse IP locale). */
async function copierTexte(texte: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(texte);
      return true;
    }
  } catch {
    // On tente la méthode de secours ci-dessous.
  }
  const zone = document.createElement("textarea");
  zone.value = texte;
  zone.setAttribute("readonly", "");
  zone.style.position = "fixed";
  zone.style.opacity = "0";
  document.body.appendChild(zone);
  zone.select();
  const reussi = document.execCommand("copy");
  zone.remove();
  return reussi;
}
