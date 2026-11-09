import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// En développement, Vite relaie l'API et l'administration vers Django (port 8000).
const backend = "http://127.0.0.1:8000";

/** /ged… : portail des intervenants (application séparée ged.html), comme le fait Caddy. */
const portailGed: Plugin = {
  name: "portail-ged",
  configureServer(serveur) {
    serveur.middlewares.use((requete, _reponse, suite) => {
      const r = requete as unknown as { url?: string };
      if (r.url && /^\/ged(\/|\?|$)/.test(r.url)) r.url = "/ged.html";
      suite();
    });
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss(), portailGed],
  build: {
    rollupOptions: {
      input: { application: "index.html", portail: "ged.html" },
    },
  },
  server: {
    proxy: {
      "/api": backend,
      "/admin": backend,
      "/static": backend,
    },
  },
});
