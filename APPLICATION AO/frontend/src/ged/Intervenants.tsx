/** Intervenants du chantier et accès personnels (un code par personne). */
import { KeyRound, Plus, Send, Trash2, UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import { CLASSE_CHAMP, Champ } from "../components/Filtres";
import { CLASSE_BOUTON, CLASSE_BOUTON_PRINCIPAL, formaterDateHeure, messageErreur } from "./outils";
import {
  FREQUENCES,
  PROFILS,
  type AccesGed,
  type EtatGed,
  type EspaceGed,
  type Frequence,
  type IntervenantGed,
  type Invitation,
  type LotCourt,
  type ProfilIntervenant,
} from "./types";

interface Proprietes {
  etat: EtatGed & { espace: EspaceGed };
  surMaj: () => void;
  surInvitations: (invitations: Invitation[]) => void;
}

interface Personne {
  nom: string;
  email: string;
}

export default function Intervenants({ etat, surMaj, surInvitations }: Proprietes) {
  const espace = etat.espace;
  const lots = espace.droits.lots;
  const clos = espace.statut === "CLOS";
  const [ajout, setAjout] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  async function ajouterSuggestion(suggestion: EtatGed["suggestions"][number]) {
    if (envoi) return; // double clic : un seul intervenant créé
    setEnvoi(true);
    setErreur(null);
    try {
      const resultat = await api<{ invitations: Invitation[] }>(`/ged/espaces/${espace.id}/intervenants`, {
        method: "POST",
        body: JSON.stringify({
          entreprise_id: suggestion.entreprise_id,
          nom: suggestion.nom,
          profil: "ENTREPRISE",
          lot_ids: suggestion.lots.map((l) => l.id),
          personnes: suggestion.personnes,
        }),
      });
      surInvitations(resultat.invitations);
      surMaj();
    } catch (p) {
      setErreur(messageErreur(p, "Ajout impossible."));
    } finally {
      setEnvoi(false);
    }
  }

  const entreprises = espace.intervenants.filter((i) => i.profil === "ENTREPRISE");
  return (
    <div className="flex flex-col gap-4">
      {espace.lots_sans_entreprise.length > 0 && (
        <p className="rounded-lg border border-accent/40 bg-accent/10 px-4 py-3 text-sm">
          Lots sans entreprise active : {espace.lots_sans_entreprise.map((l) => `${l.code} – ${l.intitule}`).join(" ; ")}.
        </p>
      )}
      {etat.suggestions.length > 0 && !clos && (
        <section aria-labelledby="titre-suggestions" className="flex flex-col gap-2 rounded-xl border border-bordure bg-surface p-4">
          <h3 id="titre-suggestions" className="font-titre font-semibold">
            Entreprises retenues à l'analyse des offres
          </h3>
          <ul className="flex flex-col gap-2">
            {etat.suggestions.map((s) => (
              <li key={s.entreprise_id} className="flex flex-wrap items-center justify-between gap-3">
                <span>
                  <span className="font-semibold">{s.nom}</span>
                  <span className="text-sm text-attenue">
                    {" "}
                    · lots {s.lots.map((l) => l.code).join(", ")} · {s.personnes.length ? s.personnes.map((p) => p.email || p.nom).join(", ") : "aucun contact"}
                  </span>
                </span>
                <button type="button" onClick={() => void ajouterSuggestion(s)} disabled={envoi} className={CLASSE_BOUTON}>
                  <UserPlus aria-hidden="true" className="size-4" />
                  Donner accès
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {erreur && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {erreur}
        </p>
      )}
      {!clos &&
        (ajout ? (
          <FormulaireIntervenant
            espaceId={espace.id}
            lots={lots}
            entreprises={entreprises}
            surAjoute={(invitations) => {
              surInvitations(invitations);
              setAjout(false);
              surMaj();
            }}
            surFermer={() => setAjout(false)}
          />
        ) : (
          <button type="button" onClick={() => setAjout(true)} className={`${CLASSE_BOUTON_PRINCIPAL} self-start`}>
            <Plus aria-hidden="true" className="size-4" />
            Ajouter un intervenant
          </button>
        ))}
      <ul className="flex flex-col gap-3">
        {espace.intervenants.map((i) => (
          <CarteIntervenant
            key={i.id}
            intervenant={i}
            lots={lots}
            entreprises={entreprises}
            emailActif={etat.email_actif}
            clos={clos}
            surMaj={surMaj}
            surInvitations={surInvitations}
          />
        ))}
      </ul>
    </div>
  );
}

function ChoixLots({ lots, choisis, surChangement, id }: { lots: LotCourt[]; choisis: number[]; surChangement: (ids: number[]) => void; id: string }) {
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="text-xs font-semibold text-attenue">Lots</legend>
      <div className="flex flex-wrap gap-2">
        {lots.map((l) => (
          <label
            key={l.id}
            htmlFor={`${id}-${l.id}`}
            className={`flex min-h-10 cursor-pointer items-center gap-2 rounded-lg border px-3 text-sm ${choisis.includes(l.id) ? "border-accent bg-accent/10" : "border-bordure-forte"}`}
          >
            <input
              id={`${id}-${l.id}`}
              type="checkbox"
              checked={choisis.includes(l.id)}
              onChange={(e) => surChangement(e.target.checked ? [...choisis, l.id] : choisis.filter((x) => x !== l.id))}
              className="accent-accent"
            />
            {l.code} – {l.intitule}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function FormulaireIntervenant({
  espaceId,
  lots,
  entreprises,
  surAjoute,
  surFermer,
}: {
  espaceId: number;
  lots: LotCourt[];
  entreprises: IntervenantGed[];
  surAjoute: (invitations: Invitation[]) => void;
  surFermer: () => void;
}) {
  const [profil, setProfil] = useState<ProfilIntervenant>("ENTREPRISE");
  const [nom, setNom] = useState("");
  const [lotIds, setLotIds] = useState<number[]>([]);
  const [titulaire, setTitulaire] = useState<number | "">("");
  const [personnes, setPersonnes] = useState<Personne[]>([{ nom: "", email: "" }]);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  async function enregistrer(evenement: FormEvent) {
    evenement.preventDefault();
    if (envoi) return;
    setEnvoi(true);
    setErreur(null);
    try {
      const resultat = await api<{ invitations: Invitation[] }>(`/ged/espaces/${espaceId}/intervenants`, {
        method: "POST",
        body: JSON.stringify({
          nom,
          profil,
          // Champs masqués pour ce rôle : non envoyés.
          lot_ids: profil === "ENTREPRISE" || profil === "MOE_EXTERNE" ? lotIds : [],
          sous_traitant_de: profil === "ENTREPRISE" ? titulaire || null : null,
          personnes: personnes.filter((p) => p.nom.trim() || p.email.trim()).map((p) => ({ nom: p.nom.trim() || nom, email: p.email.trim() })),
        }),
      });
      surAjoute(resultat.invitations);
    } catch (p) {
      setErreur(messageErreur(p, "Ajout impossible."));
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <form onSubmit={enregistrer} className="flex flex-col gap-4 rounded-xl border border-accent/40 bg-surface p-5">
      <h3 className="font-titre font-semibold">Nouvel intervenant</h3>
      <div className="flex flex-wrap gap-3">
        <Champ id="intervenant-profil" libelle="Rôle" large>
          <select id="intervenant-profil" value={profil} onChange={(e) => setProfil(e.target.value as ProfilIntervenant)} className={CLASSE_CHAMP}>
            {PROFILS.map((p) => (
              <option key={p.code} value={p.code}>
                {p.libelle}
              </option>
            ))}
          </select>
        </Champ>
        <Champ id="intervenant-nom" libelle="Société ou organisme" large>
          <input id="intervenant-nom" value={nom} onChange={(e) => setNom(e.target.value)} required maxLength={255} className={CLASSE_CHAMP} />
        </Champ>
        {profil === "ENTREPRISE" && entreprises.length > 0 && (
          <Champ id="intervenant-titulaire" libelle="Sous-traitant de (DC4)" large>
            <select
              id="intervenant-titulaire"
              value={titulaire}
              onChange={(e) => setTitulaire(e.target.value ? Number(e.target.value) : "")}
              className={CLASSE_CHAMP}
            >
              <option value="">Titulaire du marché</option>
              {entreprises.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.nom}
                </option>
              ))}
            </select>
          </Champ>
        )}
      </div>
      {(profil === "ENTREPRISE" || profil === "MOE_EXTERNE") && <ChoixLots id="intervenant-lots" lots={lots} choisis={lotIds} surChangement={setLotIds} />}
      {profil === "ENTREPRISE" && titulaire && (
        <p className="text-sm text-attenue">Un sous-traitant ne voit pas les pièces chiffrées du titulaire (OS, avenants, situations…).</p>
      )}
      <fieldset className="flex flex-col gap-2">
        <legend className="text-xs font-semibold text-attenue">Personnes (un code d'accès chacune)</legend>
        {personnes.map((p, indice) => (
          <div key={indice} className="flex flex-wrap items-end gap-2">
            <Champ id={`personne-nom-${indice}`} libelle="Nom">
              <input
                id={`personne-nom-${indice}`}
                value={p.nom}
                onChange={(e) => setPersonnes((l) => l.map((x, i) => (i === indice ? { ...x, nom: e.target.value } : x)))}
                maxLength={255}
                className={CLASSE_CHAMP}
              />
            </Champ>
            <Champ id={`personne-email-${indice}`} libelle="E-mail" large>
              <input
                id={`personne-email-${indice}`}
                type="email"
                value={p.email}
                onChange={(e) => setPersonnes((l) => l.map((x, i) => (i === indice ? { ...x, email: e.target.value } : x)))}
                className={CLASSE_CHAMP}
              />
            </Champ>
            {personnes.length > 1 && (
              <button
                type="button"
                onClick={() => setPersonnes((l) => l.filter((_, i) => i !== indice))}
                className="grid size-11 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger"
                aria-label="Retirer cette personne"
              >
                <Trash2 aria-hidden="true" className="size-4" />
              </button>
            )}
          </div>
        ))}
        <button type="button" onClick={() => setPersonnes((l) => [...l, { nom: "", email: "" }])} className={`${CLASSE_BOUTON} self-start`}>
          <Plus aria-hidden="true" className="size-4" />
          Autre personne
        </button>
      </fieldset>
      {erreur && (
        <p role="alert" className="text-danger">
          {erreur}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <button type="button" onClick={surFermer} className={CLASSE_BOUTON}>
          Annuler
        </button>
        <button type="submit" disabled={envoi} className={CLASSE_BOUTON_PRINCIPAL}>
          Ajouter et créer les codes
        </button>
      </div>
    </form>
  );
}

function CarteIntervenant({
  intervenant: i,
  lots,
  entreprises,
  emailActif,
  clos,
  surMaj,
  surInvitations,
}: {
  intervenant: IntervenantGed;
  lots: LotCourt[];
  entreprises: IntervenantGed[];
  emailActif: boolean;
  clos: boolean;
  surMaj: () => void;
  surInvitations: (invitations: Invitation[]) => void;
}) {
  const [modifLots, setModifLots] = useState<number[] | null>(null);
  const [personne, setPersonne] = useState<Personne | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const titulaire = entreprises.find((e) => e.id === i.sous_traitant_de);

  async function action(chemin: string, options: RequestInit, defaut: string) {
    setErreur(null);
    try {
      const resultat = await api<unknown>(chemin, options);
      surMaj();
      return resultat;
    } catch (p) {
      setErreur(messageErreur(p, defaut));
      return null;
    }
  }

  /** Renvoie null en cas d'échec (message affiché). */
  async function modifier(champs: Record<string, unknown>) {
    return action(`/ged/intervenants/${i.id}`, { method: "PATCH", body: JSON.stringify(champs) }, "Modification impossible.");
  }

  async function nouveauCode(acces: AccesGed, envoyer: boolean) {
    const question = envoyer
      ? `Créer un nouveau code pour ${acces.nom} et l'envoyer à ${acces.email} ? L'ancien code cessera de fonctionner.`
      : `Créer un nouveau code pour ${acces.nom} ? L'ancien code cessera de fonctionner (ses collègues ne sont pas concernés).`;
    if (!window.confirm(question)) return;
    const resultat = (await action(
      `/ged/acces/${acces.id}/invitation`,
      { method: "POST", body: JSON.stringify({ envoyer }) },
      "Nouveau code impossible.",
    )) as Invitation | null;
    if (resultat) surInvitations([resultat]);
  }

  async function ajouterPersonne(evenement: FormEvent) {
    evenement.preventDefault();
    if (!personne || envoi) return;
    setEnvoi(true);
    try {
      const resultat = (await action(
        `/ged/intervenants/${i.id}/acces`,
        { method: "POST", body: JSON.stringify(personne) },
        "Ajout impossible.",
      )) as Invitation | null;
      if (resultat) {
        setPersonne(null);
        surInvitations([resultat]);
      }
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <li className={`flex flex-col gap-3 rounded-xl border bg-surface px-4 py-4 ${i.actif ? "border-bordure" : "border-bordure opacity-70"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <span className="font-titre text-lg font-semibold">
            {i.nom} {!i.actif && <span className="text-sm font-normal text-danger">(accès désactivé)</span>}
          </span>
          <span className="text-sm text-attenue">
            {i.profil_libelle}
            {i.lots.length ? ` · lots ${i.lots.map((l) => l.code).join(", ")}` : ""}
            {titulaire ? ` · sous-traitant de ${titulaire.nom}` : ""}
          </span>
        </div>
        {!clos && (
          <div className="flex flex-wrap gap-2">
            {(i.profil === "ENTREPRISE" || i.profil === "MOE_EXTERNE") && (
              <button type="button" onClick={() => setModifLots(modifLots ? null : i.lots.map((l) => l.id))} className={CLASSE_BOUTON}>
                Lots
              </button>
            )}
            <button type="button" onClick={() => setPersonne(personne ? null : { nom: "", email: "" })} className={CLASSE_BOUTON}>
              <UserPlus aria-hidden="true" className="size-4" />
              Personne
            </button>
            <button
              type="button"
              onClick={() => {
                if (i.actif && !window.confirm(`Désactiver l'accès de ${i.nom} ? Toutes ses personnes perdent l'accès ; l'historique est conservé.`)) return;
                void modifier({ actif: !i.actif });
              }}
              className={`${CLASSE_BOUTON} ${i.actif ? "text-danger" : ""}`}
            >
              {i.actif ? "Désactiver" : "Réactiver"}
            </button>
          </div>
        )}
      </div>
      {i.profil === "ENTREPRISE" && (
        <label className="flex items-center gap-2 text-sm text-attenue">
          <input
            type="checkbox"
            checked={i.voit_confidentielles}
            disabled={clos}
            onChange={(e) => void modifier({ voit_confidentielles: e.target.checked })}
            className="size-4 accent-accent"
          />
          Voit les pièces chiffrées de ses lots (OS, avenants, devis, situations, sous-traitance)
        </label>
      )}
      {modifLots && (
        <div className="flex flex-col gap-2 rounded-lg border border-bordure-forte bg-fond p-3">
          <ChoixLots id={`lots-${i.id}`} lots={lots} choisis={modifLots} surChangement={setModifLots} />
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setModifLots(null)} className={CLASSE_BOUTON}>
              Annuler
            </button>
            <button
              type="button"
              onClick={() => {
                // Panneau refermé seulement si l'enregistrement a réussi.
                void modifier({ lot_ids: modifLots }).then((r) => {
                  if (r !== null) setModifLots(null);
                });
              }}
              disabled={i.profil === "ENTREPRISE" && modifLots.length === 0}
              className={CLASSE_BOUTON_PRINCIPAL}
            >
              Enregistrer les lots
            </button>
          </div>
        </div>
      )}
      {personne && (
        <form onSubmit={ajouterPersonne} className="flex flex-wrap items-end gap-2 rounded-lg border border-bordure-forte bg-fond p-3">
          <Champ id={`nouvelle-personne-nom-${i.id}`} libelle="Nom">
            <input
              id={`nouvelle-personne-nom-${i.id}`}
              value={personne.nom}
              onChange={(e) => setPersonne({ ...personne, nom: e.target.value })}
              required
              maxLength={255}
              className={CLASSE_CHAMP}
            />
          </Champ>
          <Champ id={`nouvelle-personne-email-${i.id}`} libelle="E-mail" large>
            <input
              id={`nouvelle-personne-email-${i.id}`}
              type="email"
              value={personne.email}
              onChange={(e) => setPersonne({ ...personne, email: e.target.value })}
              className={CLASSE_CHAMP}
            />
          </Champ>
          <button type="submit" disabled={envoi} className={CLASSE_BOUTON_PRINCIPAL}>
            Créer son code
          </button>
        </form>
      )}
      {erreur && (
        <p role="alert" className="text-danger">
          {erreur}
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="text-left text-xs text-attenue">
            <tr>
              <th scope="col" className="py-1.5 pr-3">
                Personne
              </th>
              <th scope="col" className="py-1.5 pr-3">
                Courriels
              </th>
              <th scope="col" className="py-1.5 pr-3">
                Code
              </th>
              <th scope="col" className="py-1.5 pr-3">
                Dernière connexion
              </th>
              <th scope="col" className="py-1.5">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {i.acces.map((a) => (
              <tr key={a.id} className={`border-t border-bordure ${a.actif ? "" : "text-attenue line-through"}`}>
                <td className="py-2 pr-3">
                  <span className="font-semibold">{a.nom}</span>
                  <br />
                  <span className="text-xs text-attenue">{a.email || "pas d'adresse e-mail"}</span>
                </td>
                <td className="py-2 pr-3">
                  <select
                    aria-label={`Courriels de ${a.nom}`}
                    value={a.frequence}
                    disabled={clos || !a.actif}
                    onChange={(e) =>
                      void action(
                        `/ged/acces/${a.id}`,
                        { method: "PATCH", body: JSON.stringify({ frequence: e.target.value as Frequence }) },
                        "Modification impossible.",
                      )
                    }
                    className={`${CLASSE_CHAMP} min-h-9 py-1`}
                  >
                    {FREQUENCES.map((f) => (
                      <option key={f.code} value={f.code}>
                        {f.libelle}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="whitespace-nowrap py-2 pr-3 font-mono text-xs">
                  ••••-••••-{a.code_fin}
                  <br />
                  <span className="font-sans text-attenue">créé le {formaterDateHeure(a.code_genere_le)}</span>
                </td>
                <td className="whitespace-nowrap py-2 pr-3 text-attenue">{a.dernier_acces ? formaterDateHeure(a.dernier_acces) : "jamais"}</td>
                <td className="py-2">
                  {!clos && (
                    <div className="flex flex-wrap justify-end gap-1.5">
                      {a.actif && i.actif && (
                        <>
                          <button
                            type="button"
                            onClick={() => void nouveauCode(a, false)}
                            className={CLASSE_BOUTON}
                            title="Créer un nouveau code (l'ancien cesse de fonctionner)"
                          >
                            <KeyRound aria-hidden="true" className="size-4" />
                            Nouveau code
                          </button>
                          {emailActif && a.email && (
                            <button
                              type="button"
                              onClick={() => void nouveauCode(a, true)}
                              className={CLASSE_BOUTON}
                              title="Créer un nouveau code et l'envoyer par courriel"
                            >
                              <Send aria-hidden="true" className="size-4" />
                              Envoyer
                            </button>
                          )}
                        </>
                      )}
                      <button
                        type="button"
                        onClick={() =>
                          void action(`/ged/acces/${a.id}`, { method: "PATCH", body: JSON.stringify({ actif: !a.actif }) }, "Modification impossible.")
                        }
                        className={CLASSE_BOUTON}
                      >
                        {a.actif ? "Désactiver" : "Réactiver"}
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </li>
  );
}
