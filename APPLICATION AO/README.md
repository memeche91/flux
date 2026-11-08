# Application AO

Application web pour gérer les appels d'offres de A à Z : pièces écrites (CCTP, DPGF, CCAP, RC, AE), DCE, analyse des offres (rapport ACT) et GED de chantier.
L'application est **100 % gratuite et open source**. Elle tourne sur un poste ou un serveur du cabinet, et aucune donnée n'est envoyée sur Internet.

> **Version actuelle : étape 1.2.** Bibliothèque documentaire, articles et prix de référence (étapes 1.0 et 1.1), et maintenant **rédaction du CCTP et de la DPGF de chaque lot** : éditeur visuel, PSE et variantes, reprise d'un ancien CCTP ou d'une ancienne DPGF, exports **Word, PDF et Excel** avec page de garde, sommaire et récapitulatif.

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

> ⚠️ Ne supprimez jamais le fichier `.env` : il contient le mot de passe de la base de données. Sans lui, l'application ne peut plus ouvrir vos données.

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

## Fonctionnalités

### Documents (bibliothèque documentaire)

- Cinq onglets : **CCAP**, **Acte d'engagement**, **Règlement de consultation**, **CCTP** et **DPGF**.
- Les CCTP et DPGF sont **classés par lot**. Un document « tous corps d'état » va dans le lot **TCE** : les lots sont alors retrouvés dans ses titres (« LOT 08 – … »).
- **Aucune limite de nombre** : glisser-déposer de plusieurs fichiers à la fois, avec la progression de chaque envoi.
- Pour chaque document : opération d'origine, année, marché public ou privé.
- Les **doublons** (même fichier déjà importé) sont détectés et refusés.
- **Tous les formats sont lus** : Word, Excel, PDF, CSV, OpenDocument. Les anciens `.doc`, `.xls`, `.odt`, `.rtf` et `.ods` sont convertis par LibreOffice, et les **PDF scannés** passent par la reconnaissance de texte (Tesseract, en français).
- Bouton **Relancer l'analyse** sur chaque document.

### Articles

- Chaque CCTP est **découpé en articles** : numéro, titre, rubrique parente, lot, contenu (tableaux compris).
- Les titres sont reconnus grâce aux styles Word (Titre 1, 2, 3…), à la numérotation automatique ou au texte (« 3.2.4 Châssis… », « ARTICLE 4 – … »). Les sommaires, en-têtes et pieds de page sont ignorés.
- Classement en **Généralités** ou **Ouvrages**. Les CCAP, RC et AE sont découpés en **clauses**.
- Recherche sans accents ni majuscules, filtres par lot, catégorie et **norme / DTU cité**, bouton **Copier le texte**.
- **Normes et DTU cités** : la liste des références (DTU, NF EN, Eurocodes, RE2020…) relevées dans *vos* documents, avec leur fréquence. Les textes des normes ne sont pas récupérés : ils sont payants (AFNOR / CSTB).

### Projets : rédaction du CCTP et de la DPGF

- Un **projet** (opération) regroupe ses **lots**. Les informations du projet (maître d'ouvrage, adresse, procédure, phase, indice, date) remplissent les **pages de garde**.
- Chaque lot a une seule structure qui produit **le CCTP et la DPGF avec la même numérotation** (8.1, 8.1.1…) :
  - **Chapitre** ;
  - **Article** : texte seul, présent dans le CCTP uniquement (généralités, prescriptions) ;
  - **Ouvrage** : texte dans le CCTP, plus unité, quantité et prix estimé dans la DPGF.
- **PSE et variantes exigées** : les ouvrages rattachés sont signalés dans le CCTP (« PSE n°1 ») et chiffrés à part dans la DPGF et le récapitulatif.
- **Éditeur visuel** (aperçu « page blanche ») : police, taille, gras, italique, souligné, barré, couleur, surlignage, titres, listes, alignement, tableaux (ajout et suppression de lignes et de colonnes, fusion, ligne d'en-tête, **couleur de fond des cellules**).
- **Ma bibliothèque** dans l'éditeur : insérer un article, ou **reprendre d'un coup un ancien CCTP ou une ancienne DPGF** du même lot (pour un document tous corps d'état, seul le lot concerné est repris).
- **Prix proposé** pour un ouvrage : la médiane de vos anciennes DPGF, en un clic.
- **Mise en page** par projet : police (Arial, Calibri, Times New Roman), taille, couleur des titres, fond des en-têtes de tableaux.
- Raccourci **Ctrl+S** pour enregistrer.

**Exports**

| Pièce | Formats | Contenu |
|---|---|---|
| CCTP | Word, PDF | Page de garde, sommaire (le PDF a les numéros de page ; Word le met à jour à l'ouverture), titres numérotés, pied de page « Page X / Y » |
| DPGF vierge | Excel, PDF | Page de garde avec **cadre réservé à l'entreprise**, quantités, prix à compléter, sous-totaux et totaux en formules, récapitulatif HT / TVA / TTC, emplacement pour cachet et signature |
| DPGF chiffrée | Excel, PDF | La même DPGF avec vos prix unitaires : estimation du maître d'œuvre |

### Prix de référence

- Chaque DPGF est lue ligne par ligne : chapitre, désignation, unité, quantité, prix unitaire et montant. Les colonnes sont reconnues automatiquement, et les totaux et la TVA sont ignorés.
- Recherche d'un ouvrage : **médiane, minimum et maximum par unité**, ainsi que la liste des prix relevés avec leur opération et leur année.

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
│   ├── bibliotheque/      Documents de référence, import, lecture (conversion, OCR)
│   ├── articles/          Découpage en articles, lignes de prix, normes citées
│   └── projets/           Projets, lots, PSE, CCTP et DPGF, exports Word / PDF / Excel
└── frontend/              React 19 · TypeScript · Vite · Tailwind CSS
    └── src/
        ├── pages/         Connexion, Tableau de bord, Projets, éditeur de lot, Documents, Articles, Prix
        ├── components/    En-tête, liste des lots, zone d'import, tableau
        └── api/           Accès à l'API (session + protection CSRF)
```

| Service | Rôle |
|---|---|
| `base` | PostgreSQL 16 + pgvector (recherche sémantique pour l'IA, plus tard) |
| `redis` | File d'attente des tâches (Valkey, fork open source de Redis) |
| `backend` | API Django (gunicorn) |
| `worker` | Tâches de fond : lecture, conversion, OCR et découpage des documents (puis exports, IA, e-mails) |
| `web` | Caddy : sert l'interface et relaie l'API |

## Développement (facultatif)

```bash
# Backend (SQLite, sans Docker)
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
DJANGO_DEBUG=1 python manage.py migrate
DJANGO_DEBUG=1 python manage.py createsuperuser
DJANGO_DEBUG=1 python manage.py runserver

# Tests (LibreOffice et Tesseract nécessaires pour les tests de conversion et d'OCR)
DJANGO_DEBUG=1 python manage.py test

# Relancer l'analyse de tous les documents (après une mise à jour)
docker compose exec backend python manage.py reanalyser_documents

# Interface (relais automatique vers le port 8000)
cd frontend
npm install && npm run dev
```

## Feuille de route

- [x] **1.0** Socle, thème « Chantier Nuit », bibliothèque documentaire
- [x] **1.1** Découpage en articles par lot, prix de référence, OCR, conversion des anciens formats
- [x] **1.2** Rédaction CCTP / DPGF (PSE, variantes), éditeur visuel, exports Word / PDF / Excel
- [ ] **1.3** CCAP, RC, AE à partir de modèles
- [ ] **1.4** Assistant IA local (chat et voix, administrateur uniquement)
- [ ] **2** DCE : dossier .zip classé, annuaire des entreprises
- [ ] **3** Analyse des offres et rapport ACT
- [ ] **4** GED de chantier, accès entreprises, archivage
