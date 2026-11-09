import { Fragment, type ReactNode } from "react";

/**
 * Affiche la réponse de l'assistant : paragraphes, listes, titres, gras, italique,
 * et renvois [n] cliquables vers les sources. Aucun HTML n'est interprété.
 */
export default function TexteReponse({ texte, surRenvoi }: { texte: string; surRenvoi?: (numero: number) => void }) {
  const blocs: ReactNode[] = [];
  let liste: { ordonnee: boolean; elements: string[] } | null = null;

  const fermerListe = () => {
    if (!liste) return;
    const Balise = liste.ordonnee ? "ol" : "ul";
    blocs.push(
      <Balise key={blocs.length} className={`my-1.5 flex flex-col gap-1 pl-5 ${liste.ordonnee ? "list-decimal" : "list-disc"}`}>
        {liste.elements.map((element, indice) => (
          <li key={indice}>{enLigne(element, surRenvoi)}</li>
        ))}
      </Balise>,
    );
    liste = null;
  };

  for (const brute of texte.split("\n")) {
    const ligne = brute.trimEnd();
    const puce = /^\s*[-*•]\s+(.*)$/.exec(ligne);
    const numero = /^\s*\d+[.)]\s+(.*)$/.exec(ligne);
    if (puce || numero) {
      const ordonnee = Boolean(numero);
      if (liste && liste.ordonnee !== ordonnee) fermerListe();
      liste ??= { ordonnee, elements: [] };
      liste.elements.push((puce ?? numero)![1]);
      continue;
    }
    fermerListe();
    if (!ligne.trim()) continue;
    const titre = /^#{1,4}\s+(.*)$/.exec(ligne);
    if (titre) {
      blocs.push(
        <p key={blocs.length} className="mt-2 font-titre font-semibold text-texte">
          {enLigne(titre[1], surRenvoi)}
        </p>,
      );
    } else if (/^-{3,}$/.test(ligne.trim())) {
      blocs.push(<hr key={blocs.length} className="my-2 border-bordure" />);
    } else {
      blocs.push(
        <p key={blocs.length} className="my-1">
          {enLigne(ligne, surRenvoi)}
        </p>,
      );
    }
  }
  fermerListe();
  return <>{blocs}</>;
}

function enLigne(texte: string, surRenvoi?: (numero: number) => void): ReactNode[] {
  // **gras**, *italique*, [1] ou [1, 2] ou [1]-[3]
  const morceaux = texte.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[\d+(?:\s*[,;–-]\s*\d+)*\])/g);
  return morceaux.map((morceau, indice) => {
    if (/^\*\*[^*]+\*\*$/.test(morceau)) return <strong key={indice} className="font-semibold text-white">{morceau.slice(2, -2)}</strong>;
    if (/^\*[^*].*\*$/.test(morceau)) return <em key={indice}>{morceau.slice(1, -1)}</em>;
    const renvoi = /^\[(.+)\]$/.exec(morceau);
    if (renvoi && /^[\d\s,;–-]+$/.test(renvoi[1])) {
      const numeros = renvoi[1].split(/[,;–-]/).map((n) => Number(n.trim())).filter(Boolean);
      return (
        <Fragment key={indice}>
          {numeros.map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => surRenvoi?.(n)}
              aria-label={`Voir la source ${n}`}
              className="mx-0.5 inline-grid h-5 min-w-5 place-items-center rounded bg-accent/15 px-1 align-baseline text-[11px] font-bold text-accent hover:bg-accent/30"
            >
              {n}
            </button>
          ))}
        </Fragment>
      );
    }
    return <Fragment key={indice}>{morceau}</Fragment>;
  });
}
