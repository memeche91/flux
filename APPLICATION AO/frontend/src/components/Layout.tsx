import { LogOut, Settings } from "lucide-react";
import { NavLink, Outlet } from "react-router";

import { useAuth } from "../auth/AuthContext";
import Logo from "./Logo";

const LIENS = [
  { vers: "/", libelle: "Tableau de bord", fin: true },
  { vers: "/projets", libelle: "Projets", fin: false },
  { vers: "/bibliotheque", libelle: "Documents", fin: false },
  { vers: "/articles", libelle: "Articles", fin: false },
  { vers: "/prix", libelle: "Prix de référence", fin: false },
];

export default function Layout() {
  const { utilisateur, deconnexion } = useAuth();

  return (
    <div className="min-h-screen">
      <header className="flex flex-wrap items-center gap-x-8 gap-y-3 border-b border-bordure bg-entete px-4 py-3 sm:px-8">
        <Logo />
        <nav aria-label="Navigation principale" className="flex flex-[1_1_320px] flex-wrap gap-1">
          {[...LIENS, ...(utilisateur?.est_administrateur ? [{ vers: "/assistant", libelle: "Assistant", fin: false }] : [])].map((lien) => (
            <NavLink
              key={lien.vers}
              to={lien.vers}
              end={lien.fin}
              className={({ isActive }) =>
                `flex min-h-11 items-center rounded-lg px-3.5 font-medium transition-colors ${
                  isActive ? "bg-surface-2 text-white" : "text-attenue hover:bg-surface hover:text-texte"
                }`
              }
            >
              {lien.libelle}
            </NavLink>
          ))}
        </nav>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex flex-col text-right leading-tight">
            <span className="font-medium">{utilisateur?.nom_complet}</span>
            <span className="text-xs text-attenue">{utilisateur?.role_libelle}</span>
          </div>
          {utilisateur?.est_administrateur && (
            <a
              href="/admin/"
              className="flex min-h-11 items-center gap-2 rounded-lg border border-bordure-forte px-3 text-texte no-underline hover:bg-surface-2"
            >
              <Settings aria-hidden="true" className="size-4" />
              Paramétrage
            </a>
          )}
          <button
            type="button"
            onClick={() => void deconnexion()}
            className="flex min-h-11 items-center gap-2 rounded-lg border border-bordure-forte px-3 text-texte hover:bg-surface-2"
          >
            <LogOut aria-hidden="true" className="size-4" />
            Déconnexion
          </button>
        </div>
      </header>

      <main className="mx-auto flex max-w-[1280px] flex-col gap-6 px-4 py-7 sm:px-8">
        <Outlet />
      </main>
    </div>
  );
}
