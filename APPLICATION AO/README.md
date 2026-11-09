# Application AO

Application web pour gérer les appels d'offres de A à Z : pièces écrites (CCTP, DPGF, CCAP, RC, AE), DCE, analyse des offres (rapport ACT) et GED de chantier.
L'application est **100 % gratuite et open source**. Elle tourne sur un poste ou un serveur du cabinet, et aucune donnée n'est envoyée sur Internet.

> **Version actuelle : étape 1.4.** Bibliothèque, articles et prix (1.0 et 1.1), CCTP et DPGF (1.2), CCAP, RC et actes d'engagement à partir de modèles vérifiés (1.3), et maintenant l'**assistant IA local** de l'administrateur, à l'écrit et à la voix : il répond à partir de vos documents, de vos prix et des modèles vérifiés, sans rien envoyer sur Internet.

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
5. télécharge **une seule fois** les modèles gratuits de l'assistant IA (environ 8 Go : comptez 10 à 30 minutes selon la connexion) ;
6. ouvre **http://localhost:8080** dans votre navigateur.

> **Mémoire** : Docker Desktop ne reçoit par défaut que la moitié de la mémoire du PC. L'installateur la mesure et choisit le modèle de l'assistant en conséquence : modèle complet à partir de 14 Go pour Docker (PC de 32 Go), modèle léger en dessous. **Carte graphique NVIDIA** : l'installateur vérifie que Docker peut l'utiliser ; l'assistant répond alors beaucoup plus vite. Si elle cesse d'être accessible, l'application redémarre sans elle.

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

### Pièces administratives : CCAP, RC et actes d'engagement

- **Paramètres de la consultation** (sur la page du projet) : date et heure limites de remise des offres, validité des offres, délai d'exécution, démarrage prévisionnel, visite du site, variantes, forme des prix et index de référence, retenue de garantie, avance, pénalités de retard, profil d'acheteur, contact, et **critères de jugement des offres** pondérés (le total doit faire 100 %).
- Un **CCAP** et un **RC** communs à tous les lots, et **un acte d'engagement par lot** (bouton pour créer d'un coup tous les actes d'engagement manquants).
- Point de départ au choix :
  - un **modèle de base** (marché public ou privé, celui qui correspond au projet est proposé en premier) ;
  - un **modèle du cabinet** : bouton **Enregistrer comme modèle** sur n'importe quelle pièce ;
  - un **ancien CCAP, RC ou AE** de votre bibliothèque, repris clause par clause ;
  - une page blanche.
- **Champs automatiques** : `{{nom_operation}}`, `{{maitre_ouvrage}}`, `{{date_limite_offres}}`, `{{criteres_jugement}}`, `{{liste_lots}}`, `{{lot_intitule}}`… s'insèrent depuis l'éditeur et sont remplacés à l'export par les données du projet, du lot et de la consultation. Le panneau **Champs** liste ceux qui restent à compléter ; à l'export, une valeur manquante apparaît surlignée « [à compléter : …] ».
- Les clauses sont numérotées automatiquement (« Article 3 – Prix », « 3.1 Forme des prix ») et se déplacent avec leurs sous-articles.
- **Ma bibliothèque** dans l'éditeur : insérer une clause de vos anciens documents du même type.

> Les modèles de base sont un point de départ : relisez-les et adaptez-les à chaque opération. Leurs références (code de la commande publique, CCAG-Travaux 2021, Code civil, norme NF P 03-001) ont été vérifiées à la date de leur rédaction ; contrôlez-les sur [Légifrance](https://www.legifrance.gouv.fr) avant chaque consultation.

**Exports**

| Pièce | Formats | Contenu |
|---|---|---|
| CCTP | Word, PDF | Page de garde, sommaire (le PDF a les numéros de page ; Word le met à jour à l'ouverture), titres numérotés, pied de page « Page X / Y » |
| CCAP, RC, AE | Word, PDF | Page de garde (avec le lot pour l'acte d'engagement), sommaire, articles numérotés, champs automatiques remplis, pied de page « Page X / Y » |
| DPGF vierge | Excel, PDF | Page de garde avec **cadre réservé à l'entreprise**, quantités, prix à compléter, sous-totaux et totaux en formules, récapitulatif HT / TVA / TTC, emplacement pour cachet et signature |
| DPGF chiffrée | Excel, PDF | La même DPGF avec vos prix unitaires : estimation du maître d'œuvre |

### Assistant IA (administrateur)

- Page **Assistant** (visible par l'administrateur uniquement) : une conversation à l'écrit ou **au micro**, et les réponses **lues à voix haute** si vous le souhaitez.
- Il répond à partir de **vos documents** (articles de CCTP, clauses de CCAP, RC et AE), de **vos prix** (médiane, minimum et maximum relevés dans vos DPGF) et des **modèles de pièces vérifiés**. Chaque information est suivie de sa source numérotée, cliquable.
- Il **rédige dans votre style** (par exemple un article de CCTP à partir de vos anciens articles) et laisse « [à préciser] » plutôt que d'inventer.
- Consigne stricte : **aucune référence, norme, DTU ou prix inventé**. S'il ne trouve pas la réponse dans vos documents, il le dit et renvoie vers Légifrance.
- **Projet** : choisissez un projet en haut de la conversation pour qu'il connaisse ses lots, ses estimations et les paramètres de la consultation.
- **100 % local et gratuit** : moteur [Ollama](https://ollama.com) avec le modèle Qwen 3.5 (9B), recherche par le sens avec BGE-M3, transcription de la voix avec Whisper, voix de synthèse Piper. Seuls les modèles sont téléchargés, une fois ; vos questions et vos documents ne quittent jamais le poste.
- L'assistant lit vos documents **en arrière-plan** après chaque import (barre de progression sur la page Assistant). La première lecture d'une grosse bibliothèque peut prendre une à deux heures sur un PC sans carte graphique ; l'assistant répond déjà avec ce qui est lu.
- Temps de réponse indicatifs : 20 à 60 secondes sur un PC récent sans carte graphique, quelques secondes avec une carte NVIDIA.

| Réglage (fichier `.env`) | Valeur par défaut | Rôle |
|---|---|---|
| `IA_MODELE` | `qwen3.5:9b` | Modèle de conversation (`qwen3.5:4b` : plus rapide, moins précis) |
| `IA_MODELE_EMBEDDING` | `bge-m3` | Recherche par le sens dans vos documents |
| `IA_WHISPER` | `large-v3-turbo` | Transcription de la voix (`small` : plus léger) |
| `IA_VOIX` | `fr_FR-siwis-medium` | Voix de lecture |

Après un changement de réglage, relancez `installer.ps1` : il télécharge le nouveau modèle.

### Prix de référence

- Chaque DPGF est lue ligne par ligne : chapitre, désignation, unité, quantité, prix unitaire et montant. Les colonnes sont reconnues automatiquement, et les totaux et la TVA sont ignorés.
- Recherche d'un ouvrage : **médiane, minimum et maximum par unité**, ainsi que la liste des prix relevés avec leur opération et leur année.

---

## Architecture technique

```
APPLICATION AO/
├── installer.ps1          Installation / mise à jour Windows
├── docker-compose.yml     Les 7 services : base, redis, backend, worker, voix, ollama, web
├── .env.example           Modèle de configuration (copié en .env par l'installateur)
├── donnees/               Fichiers importés (non versionnés)
├── backend/               Python 3.12 · Django 5.2 · Django Ninja · Celery
│   ├── config/            Paramètres, API, tâches de fond
│   ├── comptes/           Utilisateurs et rôles (Administrateur, MOE, Entreprise)
│   ├── referentiel/       Nomenclature des lots (modifiable dans Paramétrage)
│   ├── bibliotheque/      Documents de référence, import, lecture (conversion, OCR)
│   ├── articles/          Découpage en articles, lignes de prix, normes citées
│   ├── projets/           Projets, lots, PSE, CCTP et DPGF, CCAP / RC / AE, modèles, exports Word / PDF / Excel
│   └── assistant/         Assistant IA local : recherche par le sens, conversations, voix
└── frontend/              React 19 · TypeScript · Vite · Tailwind CSS
    └── src/
        ├── pages/         Connexion, Tableau de bord, Projets, éditeurs de lot et de pièce, Documents, Articles, Prix, Assistant
        ├── components/    En-tête, liste des lots, zone d'import, tableau
        └── api/           Accès à l'API (session + protection CSRF)
```

| Service | Rôle |
|---|---|
| `base` | PostgreSQL 16 |
| `redis` | File d'attente des tâches (Valkey, fork open source de Redis) |
| `backend` | API Django (gunicorn) |
| `worker` | Tâches de fond : lecture, conversion, OCR et découpage des documents, lecture des documents par l'IA |
| `voix` | Voix de l'assistant : transcription (Whisper) et lecture à voix haute (Piper), chargées une seule fois |
| `ollama` | Moteur d'IA local de l'assistant (modèles dans le volume `modeles_ia`) |
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

# Assistant IA : télécharger les modèles et indexer la bibliothèque
docker compose exec backend python manage.py preparer_assistant

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
- [x] **1.3** CCAP, RC, AE à partir de modèles, champs automatiques, paramètres de la consultation
- [x] **1.4** Assistant IA local (chat et voix, administrateur uniquement)
- [ ] **2** DCE : dossier .zip classé, annuaire des entreprises
- [ ] **3** Analyse des offres et rapport ACT
- [ ] **4** GED de chantier, accès entreprises, archivage
