import { Plus, Star, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";

import { api } from "../api/client";
import type { ContactEntreprise, EntrepriseDetail, Lot } from "../api/types";
import EnTetePage from "../components/EnTetePage";
import { CLASSE_CHAMP, Champ } from "../components/Filtres";
import { formaterDate } from "../lib/format";
import { useAvertirSortie } from "../lib/useAvertirSortie";
import { useRequete } from "../lib/useRequete";

type Formulaire = Omit<EntrepriseDetail, "id" | "lots" | "historique"> & { lot_ids: number[] };

const VIDE: Formulaire = {
  raison_sociale: "", siret: "", adresse: "", code_postal: "", ville: "", telephone: "", email: "", site_web: "",
  lot_ids: [], specialites: "", qualifications: "", zone_intervention: "", assureur_decennale: "", echeance_assurance: null,
  notes: "", actif: true, contacts: [],
};

function versFormulaire(e: EntrepriseDetail): Formulaire {
  const { id: _id, lots, historique: _historique, ...reste } = e;
  return { ...reste, lot_ids: lots.map((l) => l.id) };
}

export default function EntrepriseFiche() {
  const { entrepriseId } = useParams();
  const nouvelle = !entrepriseId;
  const naviguer = useNavigate();
  const lots = useRequete<Lot[]>("/referentiel/lots");
  const [detail, setDetail] = useState<EntrepriseDetail | null>(null);
  const [valeurs, setValeurs] = useState<Formulaire | null>(nouvelle ? VIDE : null);
  const [original, setOriginal] = useState<string>(JSON.stringify(VIDE));
  const location = useLocation();
  const [message, setMessage] = useState<{ ok: boolean; texte: string } | null>(
    (location.state as { message?: string } | null)?.message ? { ok: true, texte: (location.state as { message: string }).message } : null,
  );
  const [envoi, setEnvoi] = useState(false);

  useEffect(() => {
    if (nouvelle) return;
    api<EntrepriseDetail>(`/entreprises/${entrepriseId}`)
      .then((e) => {
        setDetail(e);
        setValeurs(versFormulaire(e));
        setOriginal(JSON.stringify(versFormulaire(e)));
      })
      .catch((p: unknown) => setMessage({ ok: false, texte: p instanceof Error ? p.message : "Entreprise introuvable." }));
  }, [entrepriseId, nouvelle]);

  const modifie = valeurs !== null && JSON.stringify(valeurs) !== original;
  useAvertirSortie(modifie && !envoi);

  if (!valeurs) {
    return message ? (
      <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-danger">
        {message.texte}
      </p>
    ) : (
      <p className="text-attenue">Chargement…</p>
    );
  }

  const champ = <K extends keyof Formulaire>(cle: K, valeur: Formulaire[K]) => setValeurs((v) => (v ? { ...v, [cle]: valeur } : v));
  const contact = (indice: number, changement: Partial<ContactEntreprise>) =>
    champ("contacts", valeurs.contacts.map((c, i) => (i === indice ? { ...c, ...changement } : changement.principal ? { ...c, principal: false } : c)));

  async function enregistrer(evenement: FormEvent) {
    evenement.preventDefault();
    if (!valeurs) return;
    // Une ligne de contact entièrement vide est ignorée ; une ligne remplie sans nom est signalée.
    const remplis = valeurs.contacts.filter((c) => [c.nom, c.fonction, c.email, c.telephone].some((v) => v.trim()));
    const sansNom = remplis.findIndex((c) => !c.nom.trim());
    if (sansNom >= 0) {
      setMessage({ ok: false, texte: `Indiquez le nom du contact n° ${valeurs.contacts.indexOf(remplis[sansNom]) + 1} (ou videz sa ligne).` });
      return;
    }
    setEnvoi(true);
    setMessage(null);
    try {
      const corps = JSON.stringify({ ...valeurs, contacts: remplis });
      const resultat = nouvelle
        ? await api<EntrepriseDetail>("/entreprises", { method: "POST", body: corps })
        : await api<EntrepriseDetail>(`/entreprises/${entrepriseId}`, { method: "PUT", body: corps });
      setDetail(resultat);
      setValeurs(versFormulaire(resultat));
      setOriginal(JSON.stringify(versFormulaire(resultat)));
      if (nouvelle) {
        naviguer(`/entreprises/${resultat.id}`, { replace: true, state: { message: "Entreprise ajoutée à l'annuaire." } });
        return;
      }
      setMessage({ ok: true, texte: "Fiche enregistrée." });
    } catch (probleme) {
      setMessage({ ok: false, texte: probleme instanceof Error ? probleme.message : "Enregistrement impossible." });
    } finally {
      setEnvoi(false);
    }
  }

  async function supprimer() {
    if (!detail || !window.confirm(`Supprimer « ${detail.raison_sociale} » de l'annuaire ?`)) return;
    try {
      await api(`/entreprises/${detail.id}`, { method: "DELETE" });
      setOriginal(JSON.stringify(valeurs));
      naviguer("/entreprises");
    } catch (probleme) {
      setMessage({ ok: false, texte: probleme instanceof Error ? probleme.message : "Suppression impossible." });
    }
  }

  const texte = (cle: keyof Formulaire, libelle: string, options: { type?: string; large?: boolean; indication?: string; autoComplete?: string } = {}) => (
    <Champ id={`entreprise-${cle}`} libelle={libelle} large={options.large}>
      <input
        id={`entreprise-${cle}`}
        type={options.type ?? "text"}
        value={String(valeurs[cle] ?? "")}
        placeholder={options.indication}
        autoComplete={options.autoComplete ?? "off"}
        onChange={(e) => champ(cle, (options.type === "date" ? e.target.value || null : e.target.value) as never)}
        className={CLASSE_CHAMP}
      />
    </Champ>
  );

  return (
    <>
      <nav aria-label="Fil d'Ariane" className="text-sm text-attenue">
        <Link to="/entreprises" className="text-attenue hover:text-texte">
          Entreprises
        </Link>{" "}
        / <span className="text-texte">{nouvelle ? "Nouvelle entreprise" : detail?.raison_sociale}</span>
      </nav>
      <EnTetePage surtitre="Annuaire des entreprises" titre={nouvelle ? "Nouvelle entreprise" : (detail?.raison_sociale ?? "")} />

      <form onSubmit={enregistrer} className="flex flex-col gap-4">
        <section aria-labelledby="titre-coordonnees" className="flex flex-col gap-3 rounded-xl border border-bordure bg-surface p-5">
          <h2 id="titre-coordonnees" className="font-titre text-lg font-semibold">
            Coordonnées
          </h2>
          <div className="flex flex-wrap gap-3">
            <Champ id="entreprise-raison_sociale" libelle="Raison sociale *" large>
              <input id="entreprise-raison_sociale" required value={valeurs.raison_sociale} onChange={(e) => champ("raison_sociale", e.target.value)} className={CLASSE_CHAMP} />
            </Champ>
            {texte("siret", "SIRET", { indication: "14 chiffres" })}
            {texte("adresse", "Adresse", { large: true, autoComplete: "street-address" })}
            {texte("code_postal", "Code postal", { autoComplete: "postal-code" })}
            {texte("ville", "Ville", { autoComplete: "address-level2" })}
            {texte("telephone", "Téléphone", { type: "tel" })}
            {texte("email", "E-mail (envoi du DCE)", { type: "email", large: true })}
            {texte("site_web", "Site internet")}
          </div>
        </section>

        <section aria-labelledby="titre-specialites" className="flex flex-col gap-3 rounded-xl border border-bordure bg-surface p-5">
          <h2 id="titre-specialites" className="font-titre text-lg font-semibold">
            Spécialités
          </h2>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-xs font-semibold text-attenue">Lots sur lesquels l'entreprise est consultée</legend>
            <div className="flex flex-wrap gap-1.5">
              {(lots.donnees ?? []).map((lot) => {
                const coche = valeurs.lot_ids.includes(lot.id);
                return (
                  <label
                    key={lot.id}
                    className={`flex min-h-10 cursor-pointer items-center gap-2 rounded-lg border px-2.5 text-sm focus-within:ring-2 focus-within:ring-accent ${coche ? "border-accent/60 bg-accent/12 text-accent" : "border-bordure-forte text-attenue hover:bg-surface-2"}`}
                  >
                    <input
                      type="checkbox"
                      checked={coche}
                      onChange={(e) => champ("lot_ids", e.target.checked ? [...valeurs.lot_ids, lot.id] : valeurs.lot_ids.filter((id) => id !== lot.id))}
                      className="sr-only"
                    />
                    <span className="font-semibold">{lot.code}</span> {lot.intitule}
                  </label>
                );
              })}
            </div>
          </fieldset>
          <div className="flex flex-wrap gap-3">
            {texte("specialites", "Savoir-faire", { large: true, indication: "Ex. menuiserie aluminium, murs-rideaux" })}
            {texte("qualifications", "Qualifications", { large: true, indication: "Ex. Qualibat 3512, RGE" })}
            {texte("zone_intervention", "Zone d'intervention", { indication: "Ex. 74, 73, 01" })}
            {texte("assureur_decennale", "Assureur décennale")}
            {texte("echeance_assurance", "Attestation valable jusqu'au", { type: "date" })}
          </div>
        </section>

        <section aria-labelledby="titre-contacts" className="flex flex-col gap-3 rounded-xl border border-bordure bg-surface p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="titre-contacts" className="font-titre text-lg font-semibold">
              Contacts
            </h2>
            <button
              type="button"
              onClick={() => champ("contacts", [...valeurs.contacts, { nom: "", fonction: "", email: "", telephone: "", principal: valeurs.contacts.length === 0 }])}
              className="flex min-h-10 items-center gap-1.5 rounded-lg border border-bordure-forte px-3 text-sm hover:bg-surface-2"
            >
              <Plus aria-hidden="true" className="size-4" />
              Ajouter un contact
            </button>
          </div>
          {valeurs.contacts.length === 0 && <p className="text-sm text-attenue">Aucun contact.</p>}
          {valeurs.contacts.map((c, indice) => (
            <div key={indice} className="flex flex-wrap items-end gap-2 border-t border-bordure pt-3 first-of-type:border-0 first-of-type:pt-0">
              <Champ id={`contact-nom-${indice}`} libelle="Nom">
                <input id={`contact-nom-${indice}`} value={c.nom} onChange={(e) => contact(indice, { nom: e.target.value })} className={CLASSE_CHAMP} />
              </Champ>
              <Champ id={`contact-fonction-${indice}`} libelle="Fonction">
                <input id={`contact-fonction-${indice}`} value={c.fonction} onChange={(e) => contact(indice, { fonction: e.target.value })} className={CLASSE_CHAMP} />
              </Champ>
              <Champ id={`contact-email-${indice}`} libelle="E-mail">
                <input id={`contact-email-${indice}`} type="email" value={c.email} onChange={(e) => contact(indice, { email: e.target.value })} className={CLASSE_CHAMP} />
              </Champ>
              <Champ id={`contact-telephone-${indice}`} libelle="Téléphone">
                <input id={`contact-telephone-${indice}`} type="tel" value={c.telephone} onChange={(e) => contact(indice, { telephone: e.target.value })} className={CLASSE_CHAMP} />
              </Champ>
              <button
                type="button"
                onClick={() => contact(indice, { principal: true })}
                aria-pressed={c.principal}
                aria-label={`Contact principal : ${c.nom || `contact ${indice + 1}`}`}
                title="Contact principal"
                className={`grid size-11 place-items-center rounded-lg ${c.principal ? "text-accent" : "text-attenue hover:bg-surface-2"}`}
              >
                <Star aria-hidden="true" className={`size-4.5 ${c.principal ? "fill-current" : ""}`} />
              </button>
              <button
                type="button"
                onClick={() => champ("contacts", valeurs.contacts.filter((_, i) => i !== indice))}
                aria-label={`Retirer le contact ${c.nom || indice + 1}`}
                className="grid size-11 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger"
              >
                <Trash2 aria-hidden="true" className="size-4" />
              </button>
            </div>
          ))}
        </section>

        <section aria-labelledby="titre-notes" className="flex flex-col gap-3 rounded-xl border border-bordure bg-surface p-5">
          <h2 id="titre-notes" className="font-titre text-lg font-semibold">
            Notes internes
          </h2>
          <label htmlFor="entreprise-notes" className="sr-only">
            Notes internes
          </label>
          <textarea id="entreprise-notes" rows={3} value={valeurs.notes} onChange={(e) => champ("notes", e.target.value)} className={`${CLASSE_CHAMP} py-2.5`} />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={valeurs.actif} onChange={(e) => champ("actif", e.target.checked)} className="size-4 accent-[var(--color-accent)]" />
            Entreprise active (proposée lors des consultations)
          </label>
        </section>

        <div className="flex flex-wrap items-center justify-end gap-3">
          {message && (
            <span role={message.ok ? "status" : "alert"} className={message.ok ? "text-succes" : "text-danger"}>
              {message.texte}
            </span>
          )}
          {!nouvelle && (
            <button type="button" onClick={() => void supprimer()} className="min-h-11 rounded-lg border border-danger/50 px-4 text-danger hover:bg-danger/10">
              Supprimer
            </button>
          )}
          <button type="submit" disabled={envoi || !valeurs.raison_sociale.trim()} className="min-h-11 rounded-lg bg-accent px-4.5 font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-50">
            {envoi ? "Enregistrement…" : nouvelle ? "Ajouter à l'annuaire" : "Enregistrer"}
          </button>
        </div>
      </form>

      {detail && (
        <section aria-labelledby="titre-historique" className="flex flex-col gap-3 rounded-xl border border-bordure bg-surface p-5">
          <h2 id="titre-historique" className="font-titre text-lg font-semibold">
            Historique des consultations
          </h2>
          {detail.historique.length === 0 ? (
            <p className="text-sm text-attenue">Pas encore consultée par le cabinet.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-bordure">
              {detail.historique.map((h, i) => (
                <li key={i} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span className="min-w-0">
                    <Link to={`/projets/${h.projet_id}/dce`} className="font-semibold text-texte">
                      {h.projet}
                    </Link>
                    <span className="block text-xs text-attenue">{h.lot}</span>
                  </span>
                  <span className="text-sm text-attenue">
                    {h.statut_libelle}
                    {h.date ? ` · ${formaterDate(h.date)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </>
  );
}
