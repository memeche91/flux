import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";

import { api } from "../api/client";
import type { DocumentReference, GenreOption, GenrePoste, LotDetail, Poste, Projet } from "../api/types";
import FormulairePoste, { nombreSaisi, type Brouillon } from "../components/lot/FormulairePoste";
import { Exports, OptionsLot } from "../components/lot/OptionsEtExports";
import PanneauBibliotheque from "../components/lot/PanneauBibliotheque";
import PlanLot from "../components/lot/PlanLot";
import { formaterEuros } from "../lib/format";
import { useAvertirSortie } from "../lib/useAvertirSortie";
import { useRequete } from "../lib/useRequete";

const TITRES_PAR_DEFAUT: Record<GenrePoste, string> = {
  CHAPITRE: "Nouveau chapitre",
  ARTICLE: "Nouvel article",
  OUVRAGE: "Nouvel ouvrage",
};

function versBrouillon(poste: Poste): Brouillon {
  const texte = (n: number | null) => (n == null ? "" : String(n).replace(".", ","));
  return {
    genre: poste.genre,
    titre: poste.titre,
    description: poste.description,
    unite: poste.unite,
    quantite: texte(poste.quantite),
    prix_unitaire: texte(poste.prix_unitaire),
    option_id: poste.option_id ? String(poste.option_id) : "",
  };
}

export default function LotEditeur() {
  const { projetId, lotId } = useParams();
  const projet = useRequete<Projet>(`/projets/${projetId}`);
  const [lot, setLot] = useState<LotDetail | null>(null);
  const [selection, setSelection] = useState<number | null>(null);
  const [brouillon, setBrouillon] = useState<Brouillon | null>(null);
  const [original, setOriginal] = useState<Brouillon | null>(null);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [versionEditeur, setVersionEditeur] = useState(0);

  const modifie = brouillon !== null && original !== null && JSON.stringify(brouillon) !== JSON.stringify(original);

  const appliquerSelection = useCallback((lotCourant: LotDetail, id: number | null) => {
    const poste = lotCourant.postes.find((p) => p.id === id) ?? null;
    setSelection(poste?.id ?? null);
    const suivant = poste ? versBrouillon(poste) : null;
    setBrouillon(suivant);
    setOriginal(suivant);
  }, []);

  useEffect(() => {
    api<LotDetail>(`/lots-projet/${lotId}`)
      .then((resultat) => {
        setLot(resultat);
        const premier = resultat.postes.find((p) => p.genre !== "CHAPITRE") ?? resultat.postes[0];
        appliquerSelection(resultat, premier?.id ?? null);
      })
      .catch((probleme: unknown) => setErreur(probleme instanceof Error ? probleme.message : "Lot introuvable."));
  }, [lotId, appliquerSelection]);

  // Alerte si l'on quitte la page avec des modifications non enregistrées.
  useAvertirSortie(modifie);

  async function enregistrer(): Promise<LotDetail | null> {
    if (!brouillon || selection == null || !lot) return lot;
    const quantite = nombreSaisi(brouillon.quantite);
    const prix = nombreSaisi(brouillon.prix_unitaire);
    if (brouillon.quantite.trim() && quantite == null) {
      setErreur("La quantité saisie n'est pas un nombre.");
      return null;
    }
    if (brouillon.prix_unitaire.trim() && prix == null) {
      setErreur("Le prix unitaire saisi n'est pas un nombre.");
      return null;
    }
    setOccupe(true);
    setErreur(null);
    try {
      const resultat = await api<LotDetail>(`/postes/${selection}`, {
        method: "PATCH",
        body: JSON.stringify({
          genre: brouillon.genre,
          titre: brouillon.titre.trim() || "Sans titre",
          description: brouillon.description,
          unite: brouillon.unite.trim(),
          quantite: brouillon.genre === "OUVRAGE" ? quantite : null,
          prix_unitaire: brouillon.genre === "OUVRAGE" ? prix : null,
          option_id: brouillon.genre === "OUVRAGE" && brouillon.option_id ? Number(brouillon.option_id) : null,
        }),
      });
      setLot(resultat);
      appliquerSelection(resultat, selection);
      setMessage("Enregistré.");
      return resultat;
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Enregistrement impossible.");
      return null;
    } finally {
      setOccupe(false);
    }
  }

  const enregistrerRef = useRef(enregistrer);
  enregistrerRef.current = enregistrer;
  useEffect(() => {
    const raccourci = (evenement: KeyboardEvent) => {
      if ((evenement.ctrlKey || evenement.metaKey) && evenement.key.toLowerCase() === "s") {
        evenement.preventDefault();
        void enregistrerRef.current();
      }
    };
    window.addEventListener("keydown", raccourci);
    return () => window.removeEventListener("keydown", raccourci);
  }, []);

  /** Enregistre d'abord les modifications en cours, puis exécute l'action sur la structure du lot. */
  async function executer(action: () => Promise<LotDetail>, choisir: (avant: LotDetail, apres: LotDetail) => number | null) {
    if (!lot) return;
    let avant = lot;
    if (modifie) {
      const sauvegarde = await enregistrer();
      if (!sauvegarde) return;
      avant = sauvegarde;
    }
    setOccupe(true);
    setErreur(null);
    setMessage(null);
    try {
      const apres = await action();
      setLot(apres);
      appliquerSelection(apres, choisir(avant, apres));
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Action impossible.");
    } finally {
      setOccupe(false);
    }
  }

  const nouveauPoste = (avant: LotDetail, apres: LotDetail) => {
    const anciens = new Set(avant.postes.map((p) => p.id));
    return apres.postes.find((p) => !anciens.has(p.id) && p.genre !== "CHAPITRE")?.id ?? apres.postes.find((p) => !anciens.has(p.id))?.id ?? selection;
  };

  function selectionner(id: number) {
    if (id === selection) return;
    if (modifie && !window.confirm("Abandonner les modifications non enregistrées de cet élément ?")) return;
    if (lot) appliquerSelection(lot, id);
    setMessage(null);
  }

  if (erreur && !lot) {
    return (
      <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-danger">
        {erreur}
      </p>
    );
  }
  if (!lot) return <p className="text-attenue">Chargement du lot…</p>;
  const posteSelectionne = lot.postes.find((p) => p.id === selection);
  const totalOptions = lot.options.reduce((somme, o) => somme + o.total, 0);

  return (
    <>
      <nav aria-label="Fil d'Ariane" className="text-sm text-attenue">
        <Link to="/projets" className="text-attenue hover:text-texte">
          Projets
        </Link>{" "}
        /{" "}
        <Link to={`/projets/${projetId}`} className="text-attenue hover:text-texte">
          {lot.projet.nom}
        </Link>{" "}
        / <span className="text-texte">Lot {lot.code}</span>
      </nav>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-xs font-semibold uppercase tracking-[0.08em] text-accent">CCTP et DPGF</span>
          <h1 className="font-titre text-3xl font-bold tracking-tight">
            Lot {lot.code} – {lot.intitule}
          </h1>
        </div>
        <p className="text-attenue">
          Solution de base <strong className="text-texte tabular-nums">{formaterEuros(lot.total_base)}</strong> HT
          {lot.options.length > 0 && (
            <>
              {" "}· PSE et variantes <strong className="text-texte tabular-nums">{formaterEuros(totalOptions)}</strong> HT
            </>
          )}
        </p>
      </div>

      {(erreur || message) && (
        <p role={erreur ? "alert" : "status"} className={`rounded-lg px-4 py-2.5 ${erreur ? "border border-danger/40 bg-danger/10 text-danger" : "bg-succes/10 text-succes"}`}>
          {erreur ?? message}
        </p>
      )}

      <div className="flex flex-wrap items-start gap-4">
        <div className="flex min-w-0 flex-[1_1_290px] flex-col gap-4">
          <PlanLot
            lot={lot}
            selection={selection}
            surSelection={selectionner}
            occupe={occupe}
            surAjout={(genre) =>
              void executer(
                () => api<LotDetail>(`/lots-projet/${lot.id}/postes`, { method: "POST", body: JSON.stringify({ genre, titre: TITRES_PAR_DEFAUT[genre], apres_id: selection }) }),
                nouveauPoste,
              )
            }
            surDeplacement={(sens) =>
              void executer(() => api<LotDetail>(`/postes/${selection}/deplacer`, { method: "POST", body: JSON.stringify({ sens }) }), () => selection)
            }
            surSuppression={() => {
              if (!posteSelectionne) return;
              const detail = posteSelectionne.genre === "CHAPITRE" ? " Son contenu rejoindra le chapitre précédent." : "";
              if (!window.confirm(`Supprimer « ${posteSelectionne.numero} ${posteSelectionne.titre} » ?${detail}`)) return;
              const indice = lot.postes.findIndex((p) => p.id === selection);
              const voisin = lot.postes[indice + 1]?.id ?? lot.postes[indice - 1]?.id ?? null;
              setBrouillon(original);
              void executer(() => api<LotDetail>(`/postes/${selection}`, { method: "DELETE" }), () => voisin);
            }}
          />
          <OptionsLot
            lot={lot}
            occupe={occupe}
            surAjout={(genre: GenreOption, libelle: string) =>
              executer(() => api<LotDetail>(`/lots-projet/${lot.id}/options`, { method: "POST", body: JSON.stringify({ genre, libelle }) }), () => selection)
            }
            surSuppression={async (id, nom) => {
              if (!window.confirm(`Supprimer ${nom} ? Ses ouvrages reviendront dans la solution de base.`)) return;
              await executer(() => api<LotDetail>(`/options/${id}`, { method: "DELETE" }), () => selection);
            }}
          />
        </div>

        <div className="flex min-w-0 flex-[999_1_520px] flex-col gap-4">
          {brouillon && posteSelectionne ? (
            <FormulairePoste
              identifiant={posteSelectionne.id}
              numero={posteSelectionne.numero}
              brouillon={brouillon}
              surChangement={(changement) => setBrouillon((b) => (b ? { ...b, ...changement } : b))}
              options={lot.options}
              police={projet.donnees?.police ?? "Arial"}
              taille={projet.donnees?.taille_police ?? 10}
              modifie={modifie}
              enregistrement={occupe}
              surEnregistrer={() => void enregistrer()}
              surAbandonner={() => {
                setBrouillon(original);
                setVersionEditeur((v) => v + 1);
              }}
              versionEditeur={versionEditeur}
            />
          ) : (
            <p className="rounded-xl border border-bordure bg-surface px-5 py-8 text-attenue">
              Sélectionnez un élément dans le plan, ajoutez-en un, ou reprenez un ancien CCTP depuis votre bibliothèque.
            </p>
          )}
        </div>

        <div className="flex min-w-0 flex-[1_1_290px] flex-col gap-4">
          <Exports lotId={lot.id} modifie={modifie} />
          <PanneauBibliotheque
            lotReferenceId={lot.lot_id}
            occupe={occupe}
            surInsertion={(articleId) =>
              executer(
                () => api<LotDetail>(`/lots-projet/${lot.id}/inserer-article`, { method: "POST", body: JSON.stringify({ article_id: articleId, apres_id: selection }) }),
                nouveauPoste,
              )
            }
            surReprise={async (document: DocumentReference) => {
              if (!window.confirm(`Ajouter le contenu de « ${document.nom_original} » à la fin du lot ?`)) return;
              let importes = 0;
              await executer(
                async () => {
                  const resultat = await api<{ importes: number; lot: LotDetail }>(`/lots-projet/${lot.id}/importer`, {
                    method: "POST",
                    body: JSON.stringify({ document_id: document.id }),
                  });
                  importes = resultat.importes;
                  return resultat.lot;
                },
                nouveauPoste,
              );
              if (importes) setMessage(`${importes} élément${importes > 1 ? "s" : ""} repris de « ${document.nom_original} ».`);
            }}
          />
        </div>
      </div>
    </>
  );
}
