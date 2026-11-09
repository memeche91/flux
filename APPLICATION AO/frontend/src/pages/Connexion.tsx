import { useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router";

import { useAuth } from "../auth/AuthContext";
import Logo from "../components/Logo";

export default function Connexion() {
  const { utilisateur, connexion } = useAuth();
  const emplacement = useLocation();
  const [identifiant, setIdentifiant] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  const destination = (emplacement.state as { depuis?: string } | null)?.depuis ?? "/";
  if (utilisateur) return <Navigate to={destination} replace />;

  async function soumettre(evenement: FormEvent) {
    evenement.preventDefault();
    setErreur(null);
    setEnvoi(true);
    try {
      await connexion(identifiant, motDePasse);
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Connexion impossible.");
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center px-4 py-10">
      <div className="flex w-full max-w-sm flex-col gap-8">
        <div className="flex flex-col items-center gap-3 text-center">
          <Logo taille="grand" />
          <div className="flex flex-col gap-1">
            <p className="font-titre text-base text-texte">Vos projets d’aplomb, de l’appel d’offres à la réception.</p>
            <p className="text-xs text-attenue">Appels d’offres, DCE, analyse des offres et GED de chantier.</p>
          </div>
        </div>

        <form onSubmit={soumettre} className="flex flex-col gap-4 rounded-xl border border-bordure bg-surface p-6" noValidate>
          <h1 className="font-titre text-xl font-semibold">Connexion</h1>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="identifiant" className="text-xs font-semibold text-attenue">
              Identifiant
            </label>
            <input
              id="identifiant"
              autoComplete="username"
              required
              value={identifiant}
              onChange={(e) => setIdentifiant(e.target.value)}
              className="min-h-11 rounded-lg border border-bordure-forte bg-fond px-3.5 text-texte"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="mot-de-passe" className="text-xs font-semibold text-attenue">
              Mot de passe
            </label>
            <input
              id="mot-de-passe"
              type="password"
              autoComplete="current-password"
              required
              value={motDePasse}
              onChange={(e) => setMotDePasse(e.target.value)}
              className="min-h-11 rounded-lg border border-bordure-forte bg-fond px-3.5 text-texte"
            />
          </div>

          {erreur && (
            <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
              {erreur}
            </p>
          )}

          <button
            type="submit"
            disabled={envoi || !identifiant || !motDePasse}
            className="min-h-11 rounded-lg bg-accent font-bold text-sur-accent hover:bg-accent-clair disabled:opacity-50"
          >
            {envoi ? "Connexion…" : "Se connecter"}
          </button>
        </form>
      </div>
    </div>
  );
}
