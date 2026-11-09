import { useEffect } from "react";

export const MESSAGE_SORTIE = "Abandonner les modifications non enregistrées ?";

/**
 * Tant que `modifie` est vrai, demande confirmation avant de quitter la page :
 * fermeture ou rechargement de l'onglet, mais aussi clic sur un lien interne
 * (menu, fil d'Ariane…), que le routeur traiterait sans recharger la page.
 */
export function useAvertirSortie(modifie: boolean) {
  useEffect(() => {
    if (!modifie) return;
    const avantFermeture = (evenement: BeforeUnloadEvent) => evenement.preventDefault();
    const surClic = (evenement: MouseEvent) => {
      if (evenement.defaultPrevented || evenement.button !== 0 || evenement.metaKey || evenement.ctrlKey || evenement.shiftKey || evenement.altKey) return;
      const lien = (evenement.target as Element | null)?.closest?.("a[href]");
      if (!(lien instanceof HTMLAnchorElement) || lien.target === "_blank" || lien.hasAttribute("download")) return;
      const url = new URL(lien.href, window.location.href);
      if (url.origin !== window.location.origin || url.pathname.startsWith("/api/")) return;
      if (url.pathname === window.location.pathname && url.search === window.location.search) return;
      if (!window.confirm(MESSAGE_SORTIE)) {
        evenement.preventDefault();
        evenement.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", avantFermeture);
    document.addEventListener("click", surClic, true);
    return () => {
      window.removeEventListener("beforeunload", avantFermeture);
      document.removeEventListener("click", surClic, true);
    };
  }, [modifie]);
}
