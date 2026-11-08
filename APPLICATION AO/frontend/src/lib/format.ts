export function formaterTaille(octets: number): string {
  if (octets < 1024) return `${octets} o`;
  const unites = ["Ko", "Mo", "Go"];
  let valeur = octets / 1024;
  let indice = 0;
  while (valeur >= 1024 && indice < unites.length - 1) {
    valeur /= 1024;
    indice += 1;
  }
  const chiffres = valeur < 10 ? 1 : 0;
  return `${valeur.toLocaleString("fr-FR", { maximumFractionDigits: chiffres })} ${unites[indice]}`;
}

export function formaterDate(iso: string): string {
  return new Date(iso).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
}

export function formaterNombre(nombre: number): string {
  return nombre.toLocaleString("fr-FR");
}

export function pluriel(nombre: number, singulier: string, plurielForme = `${singulier}s`): string {
  return `${formaterNombre(nombre)} ${nombre > 1 ? plurielForme : singulier}`;
}

const FORMAT_EUROS = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });

export function formaterEuros(montant: number | null | undefined): string {
  return montant == null ? "—" : FORMAT_EUROS.format(montant);
}

export function formaterQuantite(quantite: number | null | undefined): string {
  return quantite == null ? "—" : quantite.toLocaleString("fr-FR", { maximumFractionDigits: 3 });
}

/** Description courte de l'origine d'un document : « Collège Pasteur · 2024 ». */
export function origineDocument(document: { operation: string; annee: number | null; nom_original: string }): string {
  const elements = [document.operation, document.annee ? String(document.annee) : ""].filter(Boolean);
  return elements.length ? elements.join(" · ") : document.nom_original;
}
