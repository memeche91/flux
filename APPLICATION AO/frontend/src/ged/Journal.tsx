/** Journal de l'espace : dépôts, indices, visas… (le cabinet voit aussi connexions,
 * téléchargements, adresses IP et envoi des notifications). */
import { useCallback, useEffect, useState } from "react";

import type { ClientGed } from "./client";
import { CLASSE_BOUTON, formaterDateHeure, messageErreur } from "./outils";
import type { EvenementGed } from "./types";

const PAR_PAGE = 50;

export default function Journal({ client, surOuvrirDocument }: { client: ClientGed; surOuvrirDocument: (id: number) => void }) {
  const [evenements, setEvenements] = useState<EvenementGed[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(
    (numero: number) => {
      client
        .journal(numero)
        .then((resultat) => {
          setEvenements((actuels) => (numero === 1 ? resultat.resultats : [...actuels, ...resultat.resultats]));
          setTotal(resultat.total);
          setPage(numero);
        })
        .catch((p: unknown) => setErreur(messageErreur(p, "Journal indisponible.")));
    },
    [client],
  );

  useEffect(() => charger(1), [charger]);

  if (erreur) {
    return (
      <p role="alert" className="text-danger">
        {erreur}
      </p>
    );
  }
  if (total === null) return <p className="text-attenue">Chargement du journal…</p>;
  if (total === 0) return <p className="rounded-xl border border-bordure bg-surface px-5 py-6 text-attenue">Aucun événement pour l'instant.</p>;

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto rounded-xl border border-bordure">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="bg-surface-2 text-left text-xs text-attenue">
            <tr>
              <th scope="col" className="px-3 py-2">
                Date
              </th>
              <th scope="col" className="px-3 py-2">
                Événement
              </th>
              <th scope="col" className="px-3 py-2">
                Par
              </th>
              <th scope="col" className="px-3 py-2">
                Détail
              </th>
              {client.cabinet && (
                <th scope="col" className="px-3 py-2">
                  Adresse IP
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {evenements.map((e) => (
              <tr key={e.id} className="border-t border-bordure align-top">
                <td className="whitespace-nowrap px-3 py-2 text-attenue">{formaterDateHeure(e.date)}</td>
                <td className="whitespace-nowrap px-3 py-2 font-semibold">{e.type_libelle}</td>
                <td className="px-3 py-2">{e.acteur}</td>
                <td className="px-3 py-2">
                  {e.document_id ? (
                    <button
                      type="button"
                      onClick={() => surOuvrirDocument(e.document_id!)}
                      className="text-left text-accent underline-offset-2 hover:underline"
                    >
                      {e.description}
                    </button>
                  ) : (
                    e.description
                  )}
                </td>
                {client.cabinet && <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-attenue">{e.adresse_ip || "—"}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {evenements.length < total && (
        <button type="button" onClick={() => charger(page + 1)} className={`${CLASSE_BOUTON} self-center`}>
          Afficher plus ({total - evenements.length} restants)
        </button>
      )}
      <p className="text-xs text-attenue">{PAR_PAGE} événements par page · journal conservé avec l'archive du chantier.</p>
    </div>
  );
}
