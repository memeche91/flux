# Application AO

Application web pour gérer les appels d'offres de A à Z : pièces écrites (CCTP, DPGF, CCAP, RC, AE), DCE, analyse des offres (rapport ACT) et GED de chantier.
L'application est **100 % gratuite et open source**. Elle tourne sur un poste ou un serveur du cabinet, et aucune donnée n'est envoyée sur Internet.

> **Version actuelle : étape 1.0.** Socle (comptes, thème « Chantier Nuit ») et **bibliothèque documentaire** : import illimité de vos CCAP, actes d'engagement, RC, CCTP par lot et DPGF par lot.

---

## Installation sous Windows (une seule fois)

### 1. Installer Docker Desktop

- Téléchargez [Docker Desktop](https://www.docker.com/products/docker-desktop/) et installez-le. Gardez l'option « Use WSL 2 » cochée.
- Redémarrez le PC si on vous le demande, puis ouvrez Docker Desktop. Attendez l'indication **Engine running**.
- Dans Docker Desktop › *Settings* › *General*, cochez **Start Docker Desktop when you sign in**. L'application redémarrera alors toute seule à chaque ouverture de session.

> Docker Desktop est gratuit pour les entreprises de moins de 250 salariés **et** de moins de 10 M$ de chiffre d'affaires.

### 2. Récupérer l'application

Récupérez le dossier `APPLICATION AO`, soit avec `git clone`, soit en téléchargeant le ZIP du dépôt sur GitHub. Placez-le par exemple dans `C:\APPLICATION AO`.

### 3. Lancer l'installateur

Clic droit sur **`installer.ps1`** › **Exécuter avec PowerShell**.

Si Windows bloque le script, ouvrez PowerShell dans le dossier et tapez :

```powershell
powershell -ExecutionPolicy Bypass -File .\installer.ps1
```

L'installateur :
1. vérifie que Docker Desktop fonctionne ;
2. crée le fichier `.env` avec des clés de sécurité aléatoires ;
3. construit et démarre l'application (5 à 10 minutes la première fois) ;
4. vous demande de **créer votre compte administrateur** (mot de passe de 12 caractères minimum) ;
5. ouvre **http://localhost:8080** dans votre navigateur.

---

## Utilisation au quotidien

| Action | Comment |
|---|---|
| Ouvrir l'application | http://localhost:8080 |
| Paramétrer les lots et les utilisateurs | Bouton **Paramétrage** (en haut à droite, réservé à l'administrateur) |
| Arrêter l'application | `docker compose down` dans le dossier |
| Redémarrer / mettre à jour | Relancer `installer.ps1` (données conservées) |
| Voir les journaux en cas de problème | `docker compose logs -f backend worker` |

### Où sont mes données ?

- **Fichiers importés** : dossier `donnees\fichiers`, classés par type, puis par lot (par exemple `bibliotheque\CCTP\08\...`).
- **Base de données** : volume Docker `application-ao_base_donnees`.

La sauvegarde et l'archivage complet (export du chantier sur le PC ou le serveur, puis purge) arrivent avec l'étape 4 (GED).

### Accès depuis un autre poste du cabinet

1. Notez l'adresse IP du PC qui héberge l'application (par exemple `192.168.1.20`).
2. Dans le fichier `.env`, complétez ces deux lignes :
   ```
   DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.20
   DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080,http://192.168.1.20:8080
   ```
3. Relancez `installer.ps1`. Les autres postes ouvrent alors `http://192.168.1.20:8080`.

---

## Bibliothèque documentaire (étape 1.0)

- Cinq onglets : **CCAP**, **Acte d'engagement**, **Règlement de consultation**, **CCTP** et **DPGF**.
- Les CCTP et DPGF sont **classés par lot**. Un document « tous corps d'état » va dans le lot **TCE**.
- **Aucune limite de nombre** : glisser-déposer de plusieurs fichiers à la fois, avec la progression de chaque envoi.
- Pour chaque document : opération d'origine, année, marché public ou privé.
- Les **doublons** (même fichier déjà importé) sont détectés et refusés.
- **Analyse automatique** : le texte des `.docx`, `.xlsx`, `.pdf` et `.csv` est extrait, avec les titres Word conservés. C'est ce texte qui servira à l'étape 1.1 à découper vos documents en articles et à apprendre votre style.
- Les `.doc`, `.xls`, `.odt` et `.rtf` sont conservés. Leur conversion automatique arrive à l'étape suivante.

---

## Architecture technique

```
APPLICATION AO/
├── installer.ps1          Installation / mise à jour Windows
├── docker-compose.yml     Les 5 services : base, redis, backend, worker, web
├── .env.example           Modèle de configuration (copié en .env par l'installateur)
├── donnees/               Fichiers importés (non versionnés)
├── backend/               Python 3.12 · Django 5.2 · Django Ninja · Celery
│   ├── config/            Paramètres, API, tâches de fond
│   ├── comptes/           Utilisateurs et rôles (Administrateur, MOE, Entreprise)
│   ├── referentiel/       Nomenclature des lots (modifiable dans Paramétrage)
│   └── bibliotheque/      Documents de référence, import, extraction de texte
└── frontend/              React 19 · TypeScript · Vite · Tailwind CSS
    └── src/
        ├── pages/         Connexion, Tableau de bord, Bibliothèque
        ├── components/    En-tête, liste des lots, zone d'import, tableau
        └── api/           Accès à l'API (session + protection CSRF)
```

| Service | Rôle |
|---|---|
| `base` | PostgreSQL 16 + pgvector (recherche sémantique pour l'IA, plus tard) |
| `redis` | File d'attente des tâches (Valkey, fork open source de Redis) |
| `backend` | API Django (gunicorn) |
| `worker` | Tâches de fond : analyse des documents, puis exports, IA et e-mails |
| `web` | Caddy : sert l'interface et relaie l'API |

## Développement (facultatif)

```bash
# Backend (SQLite, sans Docker)
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
DJANGO_DEBUG=1 python manage.py migrate
DJANGO_DEBUG=1 python manage.py createsuperuser
DJANGO_DEBUG=1 python manage.py runserver

# Tests
DJANGO_DEBUG=1 python manage.py test

# Interface (relais automatique vers le port 8000)
cd frontend
npm install && npm run dev
```

## Feuille de route

- [x] **1.0** Socle, thème « Chantier Nuit », bibliothèque documentaire
- [ ] **1.1** Découpage en articles par lot, prix de référence, OCR, conversion des anciens formats
- [ ] **1.2** Rédaction CCTP / DPGF (PSE, variantes), éditeur visuel, exports Word / PDF / Excel
- [ ] **1.3** CCAP, RC, AE à partir de modèles
- [ ] **1.4** Assistant IA local (chat et voix, administrateur uniquement)
- [ ] **2** DCE : dossier .zip classé, annuaire des entreprises
- [ ] **3** Analyse des offres et rapport ACT
- [ ] **4** GED de chantier, accès entreprises, archivage
