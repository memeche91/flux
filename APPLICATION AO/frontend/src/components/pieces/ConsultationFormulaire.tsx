import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { api } from "../../api/client";
import type { Consultation } from "../../api/types";
import { CLASSE_CHAMP, Champ } from "../Filtres";

/** « 2027-01-11T11:00:00Z » → valeur d'un champ date et heure local (« 2027-01-11T12:00 »). */
function versSaisieLocale(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const decalage = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - decalage).toISOString().slice(0, 16);
}

export default function ConsultationFormulaire({ projetId, surEnregistre }: { projetId: number; surEnregistre?: () => void }) {
  const [valeurs, setValeurs] = useState<Consultation | null>(null);
  const [dateLimite, setDateLimite] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; texte: string } | null>(null);

  useEffect(() => {
    api<Consultation>(`/projets/${projetId}/consultation`).then((c) => {
      setValeurs(c);
      setDateLimite(versSaisieLocale(c.date_limite_offres));
    });
  }, [projetId]);

  if (!valeurs) return null;
  const champ = <K extends keyof Consultation>(cle: K, valeur: Consultation[K]) => setValeurs((v) => (v ? { ...v, [cle]: valeur } : v));
  const somme = valeurs.criteres.reduce((total, c) => total + (Number(c.ponderation) || 0), 0);

  async function enregistrer(evenement: FormEvent) {
    evenement.preventDefault();
    if (!valeurs) return;
    setMessage(null);
    try {
      const resultat = await api<Consultation>(`/projets/${projetId}/consultation`, {
        method: "PUT",
        body: JSON.stringify({
          ...valeurs,
          date_limite_offres: dateLimite ? `${dateLimite}:00` : null,
          taux_retenue_garantie: String(valeurs.taux_retenue_garantie).replace(",", "."),
          taux_avance: String(valeurs.taux_avance).replace(",", "."),
          criteres: valeurs.criteres.map((c) => ({ libelle: c.libelle.trim(), ponderation: Number(c.ponderation) || 0 })),
        }),
      });
      setValeurs(resultat);
      setMessage({ ok: true, texte: "Paramètres de la consultation enregistrés." });
      surEnregistre?.();
    } catch (probleme) {
      setMessage({ ok: false, texte: probleme instanceof Error ? probleme.message : "Enregistrement impossible." });
    }
  }

  const texte = (cle: keyof Consultation, libelle: string, indication = "", large = false) => (
    <Champ id={`consultation-${cle}`} libelle={libelle} large={large}>
      <input
        id={`consultation-${cle}`}
        value={String(valeurs[cle] ?? "")}
        placeholder={indication}
        onChange={(e) => champ(cle, e.target.value as never)}
        className={CLASSE_CHAMP}
      />
    </Champ>
  );

  return (
    <form onSubmit={enregistrer} aria-labelledby="titre-consultation" className="flex flex-col gap-4 rounded-xl border border-bordure bg-surface p-5">
      <div className="flex flex-col gap-1">
        <h2 id="titre-consultation" className="font-titre text-lg font-semibold">
          Paramètres de la consultation
        </h2>
        <p className="text-attenue">Ils remplissent automatiquement le règlement de consultation, le CCAP et les actes d'engagement.</p>
      </div>

      <div className="flex flex-wrap gap-3">
        <Champ id="consultation-date" libelle="Date et heure limites de remise des offres">
          <input id="consultation-date" type="datetime-local" value={dateLimite} onChange={(e) => setDateLimite(e.target.value)} className={CLASSE_CHAMP} />
        </Champ>
        <Champ id="consultation-validite" libelle="Validité des offres (jours)">
          <input
            id="consultation-validite"
            inputMode="numeric"
            value={valeurs.duree_validite_offres}
            onChange={(e) => champ("duree_validite_offres", Number(e.target.value.replace(/\D/g, "")) || 0)}
            className={CLASSE_CHAMP}
          />
        </Champ>
        {texte("delai_execution", "Délai d'exécution", "Ex. 10 mois, préparation incluse", true)}
        {texte("date_debut_travaux", "Démarrage prévisionnel", "Ex. mars 2027")}
        <Champ id="consultation-visite" libelle="Visite du site">
          <select id="consultation-visite" value={valeurs.visite} onChange={(e) => champ("visite", e.target.value as Consultation["visite"])} className={CLASSE_CHAMP}>
            <option value="FACULTATIVE">Facultative</option>
            <option value="OBLIGATOIRE">Obligatoire</option>
            <option value="SANS_OBJET">Pas de visite</option>
          </select>
        </Champ>
        {valeurs.visite !== "SANS_OBJET" && texte("modalites_visite", "Modalités de la visite", "Ex. sur rendez-vous auprès de…", true)}
        <Champ id="consultation-variantes" libelle="Variantes des candidats">
          <select
            id="consultation-variantes"
            value={valeurs.variantes_autorisees ? "oui" : "non"}
            onChange={(e) => champ("variantes_autorisees", e.target.value === "oui")}
            className={CLASSE_CHAMP}
          >
            <option value="non">Non autorisées</option>
            <option value="oui">Autorisées</option>
          </select>
        </Champ>
      </div>

      <div className="flex flex-wrap gap-3 border-t border-bordure pt-4">
        <Champ id="consultation-prix" libelle="Forme des prix">
          <select id="consultation-prix" value={valeurs.forme_prix} onChange={(e) => champ("forme_prix", e.target.value as Consultation["forme_prix"])} className={CLASSE_CHAMP}>
            <option value="FERME_ACTUALISABLE">Fermes et actualisables</option>
            <option value="REVISABLE">Révisables</option>
          </select>
        </Champ>
        {texte("index_reference", "Index de référence", "BT01")}
        {texte("taux_retenue_garantie", "Retenue de garantie (%)")}
        {texte("taux_avance", "Avance (%)")}
        {texte("penalites_retard", "Pénalités de retard", "", true)}
        {texte("profil_acheteur", "Profil d'acheteur (plateforme)", "Ex. https://…", true)}
        {texte("contact", "Contact pour les questions", "Nom, courriel", true)}
      </div>

      <fieldset className="flex flex-col gap-2 border-t border-bordure pt-4">
        <legend className="mb-1 flex flex-wrap items-center gap-2 font-semibold">
          Critères de jugement des offres
          <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${somme === 100 ? "bg-succes/12 text-succes" : "bg-danger/12 text-danger"}`}>
            Total {somme} %
          </span>
        </legend>
        <p className="text-xs text-attenue">
          Depuis le 21 août 2026, au moins un critère doit prendre en compte les caractéristiques environnementales de l'offre (marchés publics).
        </p>
        {valeurs.criteres.map((critere, indice) => (
          <div key={indice} className="flex flex-wrap items-end gap-2">
            <Champ id={`critere-${indice}`} libelle={`Critère ${indice + 1}`} large>
              <input
                id={`critere-${indice}`}
                value={critere.libelle}
                onChange={(e) => champ("criteres", valeurs.criteres.map((c, i) => (i === indice ? { ...c, libelle: e.target.value } : c)))}
                className={CLASSE_CHAMP}
              />
            </Champ>
            <Champ id={`ponderation-${indice}`} libelle="Pondération (%)">
              <input
                id={`ponderation-${indice}`}
                inputMode="numeric"
                value={critere.ponderation}
                onChange={(e) =>
                  champ("criteres", valeurs.criteres.map((c, i) => (i === indice ? { ...c, ponderation: Number(e.target.value.replace(/\D/g, "")) || 0 } : c)))
                }
                className={CLASSE_CHAMP}
              />
            </Champ>
            <button
              type="button"
              onClick={() => champ("criteres", valeurs.criteres.filter((_, i) => i !== indice))}
              aria-label={`Retirer le critère ${critere.libelle || indice + 1}`}
              className="grid size-11 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger"
            >
              <Trash2 aria-hidden="true" className="size-4" />
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => champ("criteres", [...valeurs.criteres, { libelle: "", ponderation: 0 }])}
          className="flex min-h-10 items-center gap-1.5 self-start rounded-lg border border-bordure-forte px-3 text-sm hover:bg-surface-2"
        >
          <Plus aria-hidden="true" className="size-4" />
          Ajouter un critère
        </button>
      </fieldset>

      <div className="flex flex-wrap items-center justify-end gap-3">
        {message && (
          <span role={message.ok ? "status" : "alert"} className={message.ok ? "text-succes" : "text-danger"}>
            {message.texte}
          </span>
        )}
        <button type="submit" className="min-h-11 rounded-lg bg-accent px-4.5 font-bold text-sur-accent hover:bg-accent-clair">
          Enregistrer la consultation
        </button>
      </div>
    </form>
  );
}
