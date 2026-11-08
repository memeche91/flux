import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { Article, DocumentReference, Lot, PageArticles } from "../../api/types";
import { origineDocument, pluriel } from "../../lib/format";
import { useRequete } from "../../lib/useRequete";
import { CLASSE_CHAMP, delaiSaisie } from "../Filtres";

interface Proprietes {
  lotReferenceId: number | null;
  surInsertion: (articleId: number) => Promise<void>;
  surReprise: (document: DocumentReference) => Promise<void>;
  occupe: boolean;
}

export default function PanneauBibliotheque({ lotReferenceId, surInsertion, surReprise, occupe }: Proprietes) {
  const [onglet, setOnglet] = useState<"articles" | "documents">("articles");

  return (
    <section aria-labelledby="titre-bibliotheque-lot" className="flex flex-col gap-3 rounded-xl border border-bordure bg-surface p-3">
      <h2 id="titre-bibliotheque-lot" className="px-1 font-titre text-base font-semibold">
        Ma bibliothèque
      </h2>
      <div role="tablist" aria-label="Source" className="flex gap-1 rounded-lg bg-fond p-1">
        {(
          [
            ["articles", "Insérer un article"],
            ["documents", "Reprendre un document"],
          ] as const
        ).map(([cle, libelle]) => (
          <button
            key={cle}
            role="tab"
            type="button"
            aria-selected={onglet === cle}
            onClick={() => setOnglet(cle)}
            className={`min-h-10 flex-1 rounded-md px-2 text-xs font-semibold ${onglet === cle ? "bg-surface-2 text-white" : "text-attenue hover:text-texte"}`}
          >
            {libelle}
          </button>
        ))}
      </div>
      {onglet === "articles" ? (
        <RechercheArticles lotReferenceId={lotReferenceId} surInsertion={surInsertion} occupe={occupe} />
      ) : (
        <DocumentsDuLot lotReferenceId={lotReferenceId} surReprise={surReprise} occupe={occupe} />
      )}
    </section>
  );
}

function RechercheArticles({ lotReferenceId, surInsertion, occupe }: { lotReferenceId: number | null; surInsertion: (id: number) => Promise<void>; occupe: boolean }) {
  const [recherche, setRecherche] = useState("");
  const [appliquee, setAppliquee] = useState("");
  const [tousLesLots, setTousLesLots] = useState(lotReferenceId == null);
  const [categorie, setCategorie] = useState("");
  const [page, setPage] = useState<PageArticles | null>(null);
  useEffect(() => delaiSaisie(() => setAppliquee(recherche.trim())), [recherche]);

  useEffect(() => {
    const filtres = new URLSearchParams({ type_document: "CCTP", page: "1" });
    if (!tousLesLots && lotReferenceId) filtres.set("lot_id", String(lotReferenceId));
    if (categorie) filtres.set("categorie", categorie);
    if (appliquee) filtres.set("recherche", appliquee);
    let actif = true;
    api<PageArticles>(`/articles?${filtres}`).then((r) => actif && setPage(r));
    return () => {
      actif = false;
    };
  }, [appliquee, tousLesLots, categorie, lotReferenceId]);

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="recherche-article-lot" className="sr-only">
        Rechercher un article
      </label>
      <input id="recherche-article-lot" type="search" value={recherche} onChange={(e) => setRecherche(e.target.value)} placeholder="Rechercher un article…" className={CLASSE_CHAMP} />
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="categorie-article-lot" className="sr-only">
          Catégorie
        </label>
        <select id="categorie-article-lot" value={categorie} onChange={(e) => setCategorie(e.target.value)} className={`${CLASSE_CHAMP} flex-1`}>
          <option value="">Toutes catégories</option>
          <option value="GENERALITES">Généralités</option>
          <option value="OUVRAGE">Ouvrages</option>
        </select>
        {lotReferenceId && (
          <label className="flex min-h-11 cursor-pointer items-center gap-2 text-xs">
            <input type="checkbox" checked={tousLesLots} onChange={(e) => setTousLesLots(e.target.checked)} className="size-4 accent-accent" />
            Tous les lots
          </label>
        )}
      </div>
      <p className="text-xs text-attenue" aria-live="polite">
        {page ? pluriel(page.total, "article") : "Chargement…"} · insertion après l'élément sélectionné
      </p>
      <ul className="flex max-h-[52vh] flex-col gap-1.5 overflow-y-auto">
        {(page?.resultats ?? []).map((article) => (
          <li key={article.id}>
            <CarteArticleLot article={article} surInsertion={surInsertion} occupe={occupe} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function CarteArticleLot({ article, surInsertion, occupe }: { article: Article; surInsertion: (id: number) => Promise<void>; occupe: boolean }) {
  return (
    <details className="group rounded-lg border border-bordure bg-fond/40">
      <summary className="flex cursor-pointer list-none flex-col gap-0.5 px-2.5 py-2 marker:hidden">
        <span className="text-sm font-semibold">
          {article.numero && <span className="mr-1.5 font-titre text-accent">{article.numero}</span>}
          {article.titre}
        </span>
        <span className="text-xs text-attenue">
          {article.categorie_libelle} · {origineDocument(article.document)}
        </span>
      </summary>
      <div className="flex flex-col gap-2 border-t border-bordure px-2.5 py-2">
        <p className="line-clamp-6 text-xs whitespace-pre-line text-attenue">{article.contenu}</p>
        <button
          type="button"
          disabled={occupe}
          onClick={() => void surInsertion(article.id)}
          className="min-h-10 self-start rounded-lg bg-accent px-3 text-sm font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-50"
        >
          Insérer dans le lot
        </button>
      </div>
    </details>
  );
}

function DocumentsDuLot({ lotReferenceId, surReprise, occupe }: { lotReferenceId: number | null; surReprise: (d: DocumentReference) => Promise<void>; occupe: boolean }) {
  const lots = useRequete<Lot[]>("/referentiel/lots");
  const codeTce = lots.donnees?.find((l) => l.code === "TCE")?.id;
  const [documents, setDocuments] = useState<DocumentReference[] | null>(null);

  useEffect(() => {
    if (!lots.donnees) return;
    const requetes = ["CCTP", "DPGF"].flatMap((type) =>
      [lotReferenceId, codeTce]
        .filter((id): id is number => id != null)
        .map((id) => api<DocumentReference[]>(`/bibliotheque/documents?type_document=${type}&lot_id=${id}`)),
    );
    if (requetes.length === 0) {
      setDocuments([]);
      return;
    }
    let actif = true;
    Promise.all(requetes).then((listes) => {
      if (actif) setDocuments(listes.flat().filter((d) => d.statut_analyse === "ANALYSE"));
    });
    return () => {
      actif = false;
    };
  }, [lots.donnees, lotReferenceId, codeTce]);

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-attenue">
        Reprenez d'un coup un ancien CCTP (articles) ou une ancienne DPGF (ouvrages chiffrés) de ce lot ; tout est ajouté à la fin du lot et reste modifiable.
      </p>
      {documents === null ? (
        <p className="text-attenue">Chargement…</p>
      ) : documents.length === 0 ? (
        <p className="text-attenue">Aucun CCTP ni DPGF analysé pour ce lot dans la bibliothèque.</p>
      ) : (
        <ul className="flex max-h-[52vh] flex-col gap-1.5 overflow-y-auto">
          {documents.map((document) => (
            <li key={document.id} className="flex flex-col gap-1.5 rounded-lg border border-bordure bg-fond/40 px-2.5 py-2">
              <span className="text-sm font-semibold">{document.nom_original}</span>
              <span className="text-xs text-attenue">
                {document.type_document} · {origineDocument(document)} ·{" "}
                {document.type_document === "DPGF" ? pluriel(document.nb_lignes_prix, "ligne") : pluriel(document.nb_articles, "article")}
              </span>
              <button
                type="button"
                disabled={occupe}
                onClick={() => void surReprise(document)}
                className="min-h-10 self-start rounded-lg border border-accent/60 px-3 text-sm font-semibold text-accent hover:bg-accent/10 disabled:opacity-50"
              >
                Reprendre ce document
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
