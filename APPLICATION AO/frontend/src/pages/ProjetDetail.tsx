import { ArrowRight, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api } from "../api/client";
import type { Lot, Police, Projet } from "../api/types";
import EnTetePage from "../components/EnTetePage";
import { CLASSE_CHAMP, Champ } from "../components/Filtres";
import ConsultationFormulaire from "../components/pieces/ConsultationFormulaire";
import PiecesAdministratives from "../components/pieces/PiecesAdministratives";
import { formaterEuros, pluriel } from "../lib/format";
import { useRequete } from "../lib/useRequete";

type Formulaire = Omit<Projet, "id" | "lots">;

export default function ProjetDetail() {
  const { projetId } = useParams();
  const naviguer = useNavigate();
  const projet = useRequete<Projet>(`/projets/${projetId}`);
  const lots = useRequete<Lot[]>("/referentiel/lots");
  const [erreur, setErreur] = useState<string | null>(null);
  const [lotAjoute, setLotAjoute] = useState("");

  if (projet.erreur) {
    return (
      <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-danger">
        {projet.erreur}
      </p>
    );
  }
  if (!projet.donnees) return <p className="text-attenue">Chargement…</p>;
  const p = projet.donnees;
  const codesPresents = new Set(p.lots.map((l) => l.code));
  const lotsDisponibles = (lots.donnees ?? []).filter((l) => !codesPresents.has(l.code));
  const totalProjet = p.lots.reduce((somme, l) => somme + l.total_base, 0);

  async function ajouterLot() {
    if (!lotAjoute) return;
    setErreur(null);
    try {
      await api(`/projets/${p.id}/lots`, { method: "POST", body: JSON.stringify({ lot_id: Number(lotAjoute) }) });
      setLotAjoute("");
      projet.recharger();
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Ajout impossible.");
    }
  }

  async function supprimerLot(id: number, libelle: string) {
    if (!window.confirm(`Supprimer le lot ${libelle} et tout son contenu (CCTP et DPGF) ?`)) return;
    await api(`/lots-projet/${id}`, { method: "DELETE" });
    projet.recharger();
  }

  async function supprimerProjet() {
    if (!window.confirm(`Supprimer définitivement le projet « ${p.nom} » et tous ses lots ?`)) return;
    await api(`/projets/${p.id}`, { method: "DELETE" });
    naviguer("/projets");
  }

  return (
    <>
      <nav aria-label="Fil d'Ariane" className="text-sm text-attenue">
        <Link to="/projets" className="text-attenue hover:text-texte">
          Projets
        </Link>{" "}
        / <span className="text-texte">{p.nom}</span>
      </nav>
      <EnTetePage
        surtitre={[p.numero, p.type_marche === "PUBLIC" ? "Marché public" : "Marché privé", p.procedure].filter(Boolean).join(" · ")}
        titre={p.nom}
        sousTitre={p.maitre_ouvrage ? `Maître d'ouvrage : ${p.maitre_ouvrage}` : undefined}
      />

      <section aria-labelledby="titre-lots" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="titre-lots" className="font-titre text-lg font-semibold">
            Lots · estimation {formaterEuros(totalProjet)} HT (solutions de base)
          </h2>
          <div className="flex flex-wrap items-end gap-2">
            <Champ id="ajout-lot" libelle="Ajouter un lot">
              <select id="ajout-lot" value={lotAjoute} onChange={(e) => setLotAjoute(e.target.value)} className={CLASSE_CHAMP}>
                <option value="">Choisir…</option>
                {lotsDisponibles.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.code} – {l.intitule}
                  </option>
                ))}
              </select>
            </Champ>
            <button type="button" onClick={() => void ajouterLot()} disabled={!lotAjoute} className="min-h-11 rounded-lg border border-bordure-forte px-4 font-semibold hover:bg-surface-2 disabled:opacity-50">
              Ajouter
            </button>
          </div>
        </div>
        {erreur && (
          <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
            {erreur}
          </p>
        )}
        {p.lots.length === 0 ? (
          <p className="rounded-xl border border-bordure bg-surface px-5 py-6 text-attenue">Ajoutez un premier lot pour commencer la rédaction.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {p.lots.map((lot) => (
              <li key={lot.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-bordure bg-surface px-4 py-3">
                <span className="w-10 font-titre text-lg font-semibold text-accent">{lot.code}</span>
                <div className="flex min-w-0 flex-[1_1_220px] flex-col">
                  <span className="font-semibold">{lot.intitule}</span>
                  <span className="text-xs text-attenue">
                    {pluriel(lot.nb_articles, "article")} · {pluriel(lot.nb_ouvrages, "ouvrage")} · {formaterEuros(lot.total_base)} HT
                  </span>
                </div>
                <Link
                  to={`/projets/${p.id}/lots/${lot.id}`}
                  className="flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4 font-bold text-sur-accent no-underline hover:bg-accent-clair"
                >
                  Rédiger CCTP et DPGF
                  <ArrowRight aria-hidden="true" className="size-4" />
                </Link>
                <button
                  type="button"
                  onClick={() => void supprimerLot(lot.id, `${lot.code} – ${lot.intitule}`)}
                  aria-label={`Supprimer le lot ${lot.code}`}
                  className="grid size-11 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger"
                >
                  <Trash2 aria-hidden="true" className="size-4.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <PiecesAdministratives projetId={p.id} typeMarche={p.type_marche} lots={p.lots} />

      <ConsultationFormulaire projetId={p.id} />

      <FormulaireProjet projet={p} surEnregistre={projet.recharger} />

      <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-danger/30 px-5 py-4">
        <p className="text-attenue">Supprimer le projet efface ses lots, ses CCTP et ses DPGF. La bibliothèque n'est pas touchée.</p>
        <button type="button" onClick={() => void supprimerProjet()} className="min-h-11 rounded-lg border border-danger/50 px-4 font-semibold text-danger hover:bg-danger/10">
          Supprimer le projet
        </button>
      </section>
    </>
  );
}

function FormulaireProjet({ projet, surEnregistre }: { projet: Projet; surEnregistre: () => void }) {
  const [valeurs, setValeurs] = useState<Formulaire>(projet);
  const [message, setMessage] = useState<{ ok: boolean; texte: string } | null>(null);
  useEffect(() => setValeurs(projet), [projet]);

  const champ = <K extends keyof Formulaire>(cle: K, valeur: Formulaire[K]) => setValeurs((v) => ({ ...v, [cle]: valeur }));

  async function enregistrer(evenement: FormEvent) {
    evenement.preventDefault();
    setMessage(null);
    try {
      const { lots: _lots, id: _id, ...donnees } = { ...valeurs, lots: [], id: 0 };
      await api(`/projets/${projet.id}`, {
        method: "PATCH",
        body: JSON.stringify({ ...donnees, date_document: donnees.date_document || null, taux_tva: String(donnees.taux_tva).replace(",", ".") }),
      });
      setMessage({ ok: true, texte: "Informations enregistrées." });
      surEnregistre();
    } catch (probleme) {
      setMessage({ ok: false, texte: probleme instanceof Error ? probleme.message : "Enregistrement impossible." });
    }
  }

  const texte = (cle: keyof Formulaire, libelle: string, large = false, multiligne = false) => (
    <Champ id={`projet-${cle}`} libelle={libelle} large={large}>
      {multiligne ? (
        <textarea id={`projet-${cle}`} rows={2} value={String(valeurs[cle] ?? "")} onChange={(e) => champ(cle, e.target.value as never)} className={`${CLASSE_CHAMP} py-2`} />
      ) : (
        <input id={`projet-${cle}`} value={String(valeurs[cle] ?? "")} onChange={(e) => champ(cle, e.target.value as never)} className={CLASSE_CHAMP} />
      )}
    </Champ>
  );

  return (
    <form onSubmit={enregistrer} className="flex flex-col gap-4 rounded-xl border border-bordure bg-surface p-5" aria-labelledby="titre-infos">
      <div className="flex flex-col gap-1">
        <h2 id="titre-infos" className="font-titre text-lg font-semibold">
          Informations et mise en page
        </h2>
        <p className="text-attenue">Ces informations remplissent les pages de garde ; la mise en page s'applique aux exports Word, PDF et Excel.</p>
      </div>
      <div className="flex flex-wrap gap-3">
        {texte("nom", "Nom de l'opération", true)}
        {texte("numero", "N° d'affaire")}
        {texte("maitre_ouvrage", "Maître d'ouvrage", true)}
        {texte("maitre_oeuvre", "Maîtrise d'œuvre", true)}
        {texte("adresse_operation", "Adresse de l'opération", true, true)}
        {texte("adresse_maitre_ouvrage", "Adresse du maître d'ouvrage", true, true)}
        <Champ id="projet-type_marche" libelle="Marché">
          <select id="projet-type_marche" value={valeurs.type_marche} onChange={(e) => champ("type_marche", e.target.value as "PUBLIC" | "PRIVE")} className={CLASSE_CHAMP}>
            <option value="PUBLIC">Public</option>
            <option value="PRIVE">Privé</option>
          </select>
        </Champ>
        {texte("procedure", "Procédure", true)}
        {texte("phase", "Phase")}
        {texte("indice", "Indice")}
        <Champ id="projet-date" libelle="Date des documents">
          <input id="projet-date" type="date" value={valeurs.date_document ?? ""} onChange={(e) => champ("date_document", e.target.value || null)} className={CLASSE_CHAMP} />
        </Champ>
        <Champ id="projet-tva" libelle="TVA (%)">
          <input id="projet-tva" inputMode="decimal" value={String(valeurs.taux_tva)} onChange={(e) => champ("taux_tva", e.target.value)} className={CLASSE_CHAMP} />
        </Champ>
      </div>
      <div className="flex flex-wrap gap-3 border-t border-bordure pt-4">
        <Champ id="projet-police" libelle="Police des documents">
          <select id="projet-police" value={valeurs.police} onChange={(e) => champ("police", e.target.value as Police)} className={CLASSE_CHAMP}>
            {["Arial", "Calibri", "Times New Roman"].map((police) => (
              <option key={police} value={police}>
                {police}
              </option>
            ))}
          </select>
        </Champ>
        <Champ id="projet-taille" libelle="Taille du texte">
          <select id="projet-taille" value={valeurs.taille_police} onChange={(e) => champ("taille_police", Number(e.target.value))} className={CLASSE_CHAMP}>
            {[9, 10, 11, 12].map((taille) => (
              <option key={taille} value={taille}>
                {taille} pt
              </option>
            ))}
          </select>
        </Champ>
        <Champ id="projet-couleur-titres" libelle="Couleur des titres et bandeaux">
          <input id="projet-couleur-titres" type="color" value={valeurs.couleur_titres} onChange={(e) => champ("couleur_titres", e.target.value)} className="h-11 w-full cursor-pointer rounded-lg border border-bordure-forte bg-fond px-1" />
        </Champ>
        <Champ id="projet-couleur-tableaux" libelle="Fond des en-têtes de tableaux">
          <input id="projet-couleur-tableaux" type="color" value={valeurs.couleur_tableaux} onChange={(e) => champ("couleur_tableaux", e.target.value)} className="h-11 w-full cursor-pointer rounded-lg border border-bordure-forte bg-fond px-1" />
        </Champ>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-3">
        {message && (
          <span role="status" className={message.ok ? "text-succes" : "text-danger"}>
            {message.texte}
          </span>
        )}
        <button type="submit" className="min-h-11 rounded-lg bg-accent px-4.5 font-bold text-sur-accent hover:bg-accent-clair">
          Enregistrer
        </button>
      </div>
    </form>
  );
}
