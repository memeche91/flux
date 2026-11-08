import { ArrowRight } from "lucide-react";
import { Link } from "react-router";

import { TYPES_DOCUMENT, type Statistiques } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import EnTetePage from "../components/EnTetePage";
import { formaterNombre } from "../lib/format";
import { useRequete } from "../lib/useRequete";

const PARCOURS = [
  {
    numero: "1",
    titre: "Pièces écrites",
    detail: "Bibliothèque documentaire disponible · rédaction CCTP, DPGF, CCAP, RC, AE à venir",
    actif: true,
  },
  { numero: "2", titre: "DCE", detail: "Dossier .zip classé, annuaire des entreprises", actif: false },
  { numero: "3", titre: "Analyse des offres", detail: "Comparatif, notation pondérée, rapport ACT", actif: false },
  { numero: "4", titre: "GED chantier", detail: "Plans, visas, indices, archivage local", actif: false },
];

export default function TableauDeBord() {
  const { utilisateur } = useAuth();
  const { donnees: stats, erreur } = useRequete<Statistiques>("/bibliotheque/statistiques");

  return (
    <>
      <EnTetePage
        surtitre="Tableau de bord"
        titre={`Bonjour ${utilisateur?.nom_complet ?? ""}`}
        sousTitre="Vos anciens documents alimentent la bibliothèque : ils serviront à reproduire votre façon de rédiger."
        actions={
          <Link
            to="/bibliotheque?type=CCTP"
            className="flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4.5 font-bold text-sur-accent no-underline hover:bg-accent-clair"
          >
            Importer des documents
            <ArrowRight aria-hidden="true" className="size-4" />
          </Link>
        }
      />

      {erreur && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-danger">
          {erreur}
        </p>
      )}

      <section aria-labelledby="titre-bibliotheque" className="flex flex-col gap-3">
        <h2 id="titre-bibliotheque" className="font-titre text-lg font-semibold">
          Bibliothèque documentaire{stats ? ` · ${formaterNombre(stats.total)} documents` : ""}
        </h2>
        <div className="flex flex-wrap gap-3">
          {TYPES_DOCUMENT.map((type) => (
            <Link
              key={type.code}
              to={`/bibliotheque?type=${type.code}`}
              className="group flex min-w-0 flex-[1_1_180px] flex-col gap-1.5 rounded-xl border border-bordure bg-surface px-4.5 py-4 text-texte no-underline transition-colors hover:border-bordure-forte hover:bg-surface-2"
            >
              <span className="text-xs text-attenue">{type.libelle}</span>
              <span className="font-titre text-3xl font-semibold tabular-nums">
                {stats ? formaterNombre(stats.par_type[type.code]) : "—"}
              </span>
              <span className="text-xs text-attenue group-hover:text-texte">
                {type.parLot ? "Classés par lot" : "Pièces communes"}
              </span>
            </Link>
          ))}
        </div>
      </section>

      <div className="flex flex-wrap items-start gap-5">
        <section
          aria-labelledby="titre-parcours"
          className="flex min-w-0 flex-[1_1_340px] flex-col gap-4 rounded-xl border border-bordure bg-surface p-5"
        >
          <h2 id="titre-parcours" className="font-titre text-lg font-semibold">
            Parcours de l'application
          </h2>
          <ol className="flex flex-col">
            {PARCOURS.map((etape, indice) => (
              <li key={etape.numero} className="flex gap-3.5">
                <div className="flex flex-col items-center">
                  <span
                    className={`grid size-7 shrink-0 place-items-center rounded-full text-[13px] font-bold ${
                      etape.actif ? "bg-accent text-sur-accent" : "border-2 border-bordure-forte text-attenue"
                    }`}
                  >
                    {etape.numero}
                  </span>
                  {indice < PARCOURS.length - 1 && (
                    <span aria-hidden="true" className="min-h-4 w-0.5 flex-1 bg-bordure-forte" />
                  )}
                </div>
                <div className="flex flex-col pb-4">
                  <span className="font-semibold">{etape.titre}</span>
                  <span className="text-xs text-attenue">{etape.detail}</span>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section
          aria-labelledby="titre-demarrer"
          className="flex min-w-0 flex-[1_1_340px] flex-col gap-4 rounded-xl border border-bordure bg-surface p-5"
        >
          <h2 id="titre-demarrer" className="font-titre text-lg font-semibold">
            Pour bien démarrer
          </h2>
          <ol className="flex list-decimal flex-col gap-2.5 pl-5 marker:font-semibold marker:text-accent">
            <li>
              Importez vos anciens <strong>CCTP</strong> lot par lot (un document « tous corps d'état » va dans
              le lot <em>TCE</em>).
            </li>
            <li>
              Importez les <strong>DPGF</strong> correspondantes : elles fourniront vos prix de référence.
            </li>
            <li>
              Ajoutez vos <strong>CCAP</strong>, <strong>RC</strong> et <strong>actes d'engagement</strong> types.
            </li>
          </ol>
          <p className="text-xs text-attenue">
            Formats lus automatiquement : .docx, .xlsx, .pdf et .csv. Les .doc, .xls, .odt et .rtf sont conservés et
            seront convertis à l'étape suivante.
          </p>
        </section>
      </div>
    </>
  );
}
