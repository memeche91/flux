# D’Aplomb

*Vos projets d’aplomb, de l’appel d’offres à la réception.*

D’Aplomb est une application web pour gérer les appels d'offres de A à Z : pièces écrites (CCTP, DPGF, CCAP, RC, AE), DCE, analyse des offres (rapport ACT) et GED de chantier.
Elle est **100 % gratuite et open source**, tourne sur un poste ou un serveur du cabinet, et aucune donnée n'est envoyée sur Internet.

> **Version actuelle : étape 4.** Pièces écrites et assistant IA local (étape 1), DCE et annuaire des entreprises (étape 2), analyse des offres et rapport ACT (étape 3), et maintenant la **GED de chantier** : espace partagé avec les entreprises (un code d'accès par personne), plans et visas classés par lot, indices et historique complet, notifications par courriel, puis **archive complète du projet** sur le PC ou le serveur du cabinet et purge des fichiers.

---

## Installation sous Windows (une seule fois)

### 1. Installer Docker Desktop

- Téléchargez [Docker Desktop](https://www.docker.com/products/docker-desktop/) et installez-le. Gardez l'option « Use WSL 2 » cochée.
- Redémarrez le PC si on vous le demande, puis ouvrez Docker Desktop. Attendez l'indication **Engine running**.
- Dans Docker Desktop › *Settings* › *General*, cochez **Start Docker Desktop when you sign in**. L'application redémarrera alors toute seule à chaque ouverture de session.

> Docker Desktop est gratuit pour les entreprises de moins de 250 salariés **et** de moins de 10 M$ de chiffre d'affaires.

### 2. Récupérer D’Aplomb

Récupérez le dossier `APPLICATION AO`, soit avec `git clone`, soit en téléchargeant le ZIP du dépôt sur GitHub. Placez-le par exemple dans `C:\APPLICATION AO`.
Le dossier garde son nom technique d'origine, `APPLICATION AO` (comme le projet Docker `application-ao` et ses volumes de données) : seul le nom affiché est devenu D’Aplomb.

### 3. Lancer l'installateur

Clic droit sur **`installer.ps1`** › **Exécuter avec PowerShell**.

Si Windows bloque le script, ouvrez PowerShell dans le dossier et tapez :

```powershell
powershell -ExecutionPolicy Bypass -File .\installer.ps1
```

L'installateur :
1. vérifie que Docker Desktop fonctionne ;
2. crée le fichier `.env` avec des clés de sécurité aléatoires (il s’arrête et explique quoi faire si une installation existe déjà sans son `.env`, voir « Mettre à jour sans rien perdre ») ;
3. propose d’enregistrer les fichiers et les sauvegardes sur le **serveur de l’agence** (recommandé, voir « Stockage sur le serveur de l’agence ») et vérifie l’accès au dossier partagé ;
4. construit et démarre l'application (5 à 10 minutes la première fois) ;
5. vous demande de **créer votre compte administrateur** (mot de passe de 12 caractères minimum) ;
6. télécharge **une seule fois** les modèles gratuits de l'assistant IA (environ 8 Go : comptez 10 à 30 minutes selon la connexion) ;
7. fait une **première sauvegarde**, vérifiée, et affiche le résultat (ensuite, une sauvegarde est faite chaque nuit) ;
8. ouvre **http://localhost:8080** dans votre navigateur.

> **Mémoire** : Docker Desktop ne reçoit par défaut que la moitié de la mémoire du PC. L'installateur la mesure et choisit le modèle de l'assistant en conséquence : modèle complet à partir de 14 Go pour Docker (PC de 32 Go), modèle léger en dessous. **Carte graphique NVIDIA** : l'installateur vérifie que Docker peut l'utiliser ; l'assistant répond alors beaucoup plus vite. Si elle cesse d'être accessible, l'application redémarre sans elle.

---

## Utilisation au quotidien

| Action | Comment |
|---|---|
| Ouvrir D’Aplomb | http://localhost:8080 |
| Paramétrer les lots et les utilisateurs | Bouton **Paramétrage** (en haut à droite, réservé à l'administrateur) |
| Arrêter D’Aplomb | `docker compose down` dans le dossier (les tâches en attente sont conservées) |
| Redémarrer / mettre à jour | Relancer `installer.ps1` (données conservées : voir « Mettre à jour sans rien perdre ») |
| Sauvegarder tout de suite | `docker compose exec worker python manage.py sauvegarder` (sinon : chaque nuit à 2 h 30) |
| Restaurer une sauvegarde | Clic droit sur `restaurer.ps1` › **Exécuter avec PowerShell** |
| Voir les journaux en cas de problème | `docker compose logs -f backend worker` |
| Ouvrir la GED aux entreprises sur Internet | Vider la ligne `GED_INTERNET=` du fichier `.env`, puis relancer `installer.ps1` et répondre **O** à la question « Ouvrir la GED aux entreprises sur Internet » |

### Où sont mes données ?

- **Fichiers importés** : dossier `donnees\fichiers`, classés par type, puis par lot (par exemple `bibliotheque\CCTP\08\...`). Avec le stockage sur le serveur de l’agence : sous-dossier `fichiers` du dossier partagé (par exemple `\\SERVEUR\DAplomb\fichiers`).
- **Base de données** : volume Docker `application-ao_base_donnees`, toujours sur ce PC (invisible dans l’Explorateur) ; sa copie vérifiée est faite chaque nuit dans le dossier des sauvegardes.
- **Archives de fin de chantier** : dossier `donnees\archives` (ou le dossier choisi dans `.env`, ligne `DOSSIER_ARCHIVES_PC`, par exemple `D:\Archives chantiers`) ; avec le serveur de l’agence : `\\SERVEUR\DAplomb\archives`.
- **Sauvegardes de chaque nuit** : dossier `donnees\sauvegardes` (ou ligne `DOSSIER_SAUVEGARDES_PC` de `.env`) ; avec le serveur de l’agence : `\\SERVEUR\DAplomb\sauvegardes`.
- **Journal des connexions à la GED depuis Internet** : dossier `donnees\journaux`.

> ⚠️ Ne supprimez jamais le fichier `.env` : il contient le mot de passe de la base de données, la clé `DJANGO_SECRET_KEY` (sans elle, les codes d’accès des entreprises à la GED ne fonctionnent plus) et, avec le serveur de l’agence, le mot de passe du compte dédié. Sans lui, l'application ne peut plus ouvrir vos données. Une copie est faite chaque nuit dans `sauvegardes\configuration` (dossier confidentiel).

En fin de chantier, l'archive complète du projet (bouton **Préparer l'archive complète**, page GED du projet) se télécharge ou se copie sur le serveur du cabinet ; la purge des fichiers libère ensuite la place (voir « GED de chantier »).

### Accès depuis un autre poste du cabinet

1. Notez l'adresse IP du PC qui héberge l'application (par exemple `192.168.1.20`).
2. Dans le fichier `.env`, complétez ces deux lignes :
   ```
   DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.20
   DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080,http://192.168.1.20:8080
   ```
3. Relancez `installer.ps1`. Les autres postes ouvrent alors `http://192.168.1.20:8080`.

---

## Données : stockage, sauvegarde, restauration, mises à jour

### Stockage sur le serveur de l’agence (recommandé)

Par défaut, D’Aplomb range tout sur le PC où il est installé : une panne de son disque emporterait tout. Il est recommandé d’enregistrer les fichiers sur le serveur de l’agence, qui est lui-même sauvegardé :

| Contenu | Fichiers sur le PC | Avec le serveur de l’agence |
|---|---|---|
| Fichiers importés, documents de la GED | `donnees\fichiers` | `\\SERVEUR\DAplomb\fichiers` |
| Archives de fin de chantier | `donnees\archives` (ou `DOSSIER_ARCHIVES_PC`) | `\\SERVEUR\DAplomb\archives` |
| Sauvegardes de chaque nuit | `donnees\sauvegardes` (ou `DOSSIER_SAUVEGARDES_PC`) | `\\SERVEUR\DAplomb\sauvegardes` |
| Base de données | volume Docker du PC | volume Docker du PC (sa copie de chaque nuit part sur le serveur) |

La base de données reste toujours sur le PC : PostgreSQL ne fonctionne pas de façon fiable sur un dossier réseau. C’est sa copie de chaque nuit, vérifiée, qui part sur le serveur.

**Préparer le serveur** (Windows Server ; avec votre prestataire informatique au besoin) :
1. créez un dossier, par exemple `D:\DAplomb`, partagez-le sous le nom `DAplomb`, et créez dedans les sous-dossiers `fichiers`, `archives` et `sauvegardes` (l’installateur les réutilise) ;
2. créez un **compte Windows dédié** (par exemple `daplomb`), avec un mot de passe sans virgule, guillemet ni apostrophe, et qui n’expire pas, et donnez-lui le droit **Modifier** sur ce dossier (onglets Partage et Sécurité), et sur rien d’autre ;
3. vérifiez que le pare-feu du serveur autorise le partage de fichiers (port 445) depuis le PC de D’Aplomb, et que le partage accepte SMB 3 (c’est le cas par défaut depuis Windows Server 2012) ;
4. si d’autres personnes doivent consulter les archives, donnez-leur seulement la **lecture** sur le sous-dossier `archives`. Les sous-dossiers `sauvegardes` et `fichiers` restent réservés au compte dédié et aux administrateurs (Propriétés › Sécurité › Avancé › désactiver l’héritage sur `sauvegardes` et `fichiers`) : `sauvegardes` contient les clés de l’application et des copies complètes de la base.

**Activer** : lancez `installer.ps1` et répondez **O** à « Enregistrer les fichiers et les sauvegardes sur le serveur de l’agence ». Indiquez le chemin du dossier (`\\SERVEUR\DAplomb`, ou un sous-dossier : `\\SERVEUR\Donnees\DAplomb`), le compte (`DOMAINE\daplomb`, ou `SERVEUR\daplomb` pour un compte local du serveur) et son mot de passe. L’installateur :
- trouve l’adresse IP du serveur (Docker ne connaît pas les noms du réseau Windows) ;
- vérifie l’accès depuis Windows (création des sous-dossiers `fichiers`, `archives` et `sauvegardes`, écriture puis effacement d’un fichier d’essai), puis depuis Docker ;
- copie sur le serveur les fichiers déjà enregistrés sur le PC, avant le redémarrage, puis renomme les anciens dossiers du PC (`donnees\fichiers-copie-avant-serveur-…`, à supprimer une fois l’application vérifiée) ;
- active le fichier `docker-compose.serveur.yml` (ligne `COMPOSE_FILE` de `.env`).

> Le mot de passe du compte dédié est enregistré dans `.env`, comme les autres clés de l’application : c’est pourquoi ce compte doit être **dédié** et limité au seul dossier de D’Aplomb. Docker s’en sert pour ouvrir le dossier partagé. Il n’est pas fourni aux services comme réglage, mais le fichier `.env` qui le contient est copié chaque nuit dans `sauvegardes\configuration`.

À savoir :
- le serveur doit être joignable quand l’application démarre (Docker ouvre le dossier partagé à ce moment-là). S’il ne l’est pas encore à l’ouverture de la session Windows, l’application redémarre seule quand le serveur revient : la tâche planifiée « D’Aplomb - démarrage », créée par `installer.ps1`, relance `docker compose up -d` chaque minute pendant 20 minutes. Au-delà, relancez `installer.ps1`, ou `docker compose up -d`, une fois le serveur revenu ;
- mot de passe du compte changé, serveur renuméroté : relancez `installer.ps1`. Il retrouve l’adresse du serveur, vérifie l’accès et, s’il échoue, propose de saisir à nouveau le dossier et le compte. Les fichiers du serveur ne sont jamais effacés par cette opération ;
- nouveau dossier partagé : copiez-y d’abord les sous-dossiers `fichiers` et `archives` de l’ancien, puis videz la ligne `STOCKAGE=` de `.env` et relancez `installer.ps1` ;
- revenir aux fichiers sur le PC : mettez `STOCKAGE=pc` dans `.env`, puis relancez `installer.ps1`. Les fichiers du serveur sont recopiés sur le PC avant le redémarrage ; le mot de passe du compte dédié est effacé de `.env` et de Docker, et la tâche planifiée est supprimée.

### Sauvegarde automatique chaque nuit

Chaque nuit à 2 h 30 (heure de Paris, ligne `SAUVEGARDE_HEURE` de `.env`), le service `worker` :
1. copie la base de données dans `sauvegardes\base\AAAA-MM-JJ_HHMM.dump` ;
2. **vérifie cette copie** : il la restaure dans une base temporaire et compare le nombre de lignes de tables clés avec la base réelle ;
3. copie le fichier `.env` dans `sauvegardes\configuration\.env` : sa clé `DJANGO_SECRET_KEY` garde valides les codes d’accès des entreprises à la GED après une restauration. **Ce dossier est confidentiel** ;
4. si les fichiers sont sur le PC, copie les fichiers nouveaux ou modifiés dans `sauvegardes\fichiers` et `sauvegardes\archives` (un fichier supprimé de l’application y reste encore 30 jours). Avec le serveur de l’agence, cette copie est inutile : les fichiers y sont déjà ;
5. garde la dernière sauvegarde de chacun des 14 derniers jours qui ont une sauvegarde (`SAUVEGARDE_JOURS` ; un PC éteint le week-end garde donc plus de 14 jours de calendrier) et la première de chacun des 6 derniers mois (`SAUVEGARDE_MOIS`).

En cas d’échec, les administrateurs (comptes administrateur actifs avec une adresse e-mail) reçoivent un courriel, si la messagerie est réglée. L’état de la dernière sauvegarde est affiché dans l’application, avec une alerte si aucune n’a réussi depuis plus de 36 heures, si la dernière a échoué, ou si les sauvegardes sont sur le même disque que l’application.

- Le PC doit être allumé et la session Windows ouverte (Docker Desktop) à l’heure prévue. S’il était éteint, la sauvegarde est faite à son démarrage suivant.
- Sauvegarder tout de suite : depuis l’application (administrateur), ou `docker compose exec worker python manage.py sauvegarder`. `installer.ps1` en fait une à la fin de chaque passage et affiche le résultat.
- Fichiers sur le PC : placez les sauvegardes sur un autre disque, toujours branché (ligne `DOSSIER_SAUVEGARDES_PC` de `.env`, par exemple `E:\Sauvegardes DAplomb`), puis relancez `installer.ps1`. Sinon, une panne du disque emporterait l’application **et** ses sauvegardes. Un dossier réseau n’est pas accepté (Docker ne sait pas l’ouvrir) : choisissez plutôt le stockage sur le serveur de l’agence.

### Restaurer une sauvegarde

Clic droit sur **`restaurer.ps1`** › **Exécuter avec PowerShell** (ou `powershell -ExecutionPolicy Bypass -File .\restaurer.ps1`). Le script :
1. reprend le fichier `.env` enregistré avec les sauvegardes s’il est absent du dossier (nouveau PC). Fichiers sur le PC : le dossier indiqué devient le dossier des sauvegardes de l’application (ligne `DOSSIER_SAUVEGARDES_PC`) ; un dossier réseau est d’abord recopié dans `donnees\sauvegardes` ;
2. liste les sauvegardes et propose la plus récente (option `-Sauvegarde 2026-11-08_0230.dump` pour en choisir une sans la liste). Fichiers sur le PC, `.env` déjà présent : il indique le dossier où il lit les sauvegardes et permet d’en choisir un autre (disque externe, `installer.ps1` déjà lancé sur un nouveau PC) ; s’il n’en trouve aucune (disque externe qui a changé de lettre, sauvegardes recopiées ailleurs), il demande le dossier qui les contient ;
3. vérifie que la clé des codes d’accès de la GED est bien celle de la sauvegarde, et propose de la reprendre sinon ;
4. si les fichiers sont sur le PC, propose de les recopier depuis la sauvegarde (rien n’est effacé) ;
5. après confirmation (taper `OUI`), arrête l’application, copie la base actuelle (`sauvegardes\base\avant-restauration_…`), restaure la base choisie, applique les mises à jour de structure, puis redémarre l’application (si ces mises à jour échouent, l’application n’est pas redémarrée : relancez le script et choisissez une autre copie).

**Après une panne du PC** : installez Docker Desktop sur le nouveau PC, récupérez le dossier de l’application (étape 2 de l’installation), puis lancez **directement `restaurer.ps1`** et indiquez le dossier des sauvegardes (par exemple `\\SERVEUR\DAplomb\sauvegardes` ; le script demande le compte dédié si votre session n’y a pas accès). Il reprend `.env`, restaure la base, puis lance `installer.ps1` pour terminer (modèles de l’assistant, carte graphique, tâche de démarrage si les fichiers sont sur le serveur) ; si la restauration échoue, l’application n’est pas démarrée : relancez `restaurer.ps1`. Si `installer.ps1` a déjà été lancé sur ce PC, `restaurer.ps1` garde le `.env` qu’il a créé : fichiers sur le PC, indiquez le dossier des sauvegardes quand le script le propose (sinon il ne voit que la sauvegarde de contrôle d’`installer.ps1`) ; choisissez une copie antérieure à cette installation (la sauvegarde de contrôle est une copie de la base neuve), puis acceptez de reprendre la clé de la sauvegarde.

Commande équivalente, application arrêtée (`docker compose stop`, puis `docker compose up -d base redis`) : `docker compose run --rm --no-deps -T worker python manage.py restaurer 2026-11-08_0230.dump --confirmer` (option `--avec-fichiers` pour recopier aussi les fichiers sauvegardés), puis `docker compose up -d`.

### Mettre à jour sans rien perdre

Vos données ne sont pas dans le code : la base est dans un volume Docker, les fichiers dans `donnees\` (ou sur le serveur de l’agence) et les clés dans `.env`. Pour mettre à jour :
- **avec git** : `git pull` dans le dossier de l’application, puis relancez `installer.ps1` ;
- **avec le ZIP** : copiez le contenu de la nouvelle version **par-dessus le dossier existant**, en acceptant de remplacer les fichiers. `.env` et le contenu de `donnees\` ne font pas partie du ZIP : ils sont conservés. Relancez ensuite `installer.ps1` ;
- **dans un nouveau dossier** : copiez d’abord le fichier `.env` et le dossier `donnees` de l’ancien dossier dans le nouveau, puis lancez `installer.ps1`. Ne supprimez l’ancien dossier qu’une fois l’application vérifiée.

Si le fichier `.env` manque alors qu’une base existe déjà, l’installateur s’arrête et explique quoi faire, au lieu de créer de nouvelles clés (qui rendraient la base inaccessible et les codes d’accès de la GED invalides). Les mises à jour de structure de la base sont appliquées automatiquement au démarrage. Par prudence, lancez une sauvegarde juste avant (`docker compose exec worker python manage.py sauvegarder`) ; `installer.ps1` en fait une à la fin de la mise à jour.

### Journaux des services

Chaque service garde au plus 5 fichiers de journal de 10 Mo (50 Mo) ; les plus anciens sont effacés automatiquement. Les journaux ne peuvent donc plus remplir le disque, même si la GED ouverte sur Internet reçoit beaucoup de requêtes. Pour lire les derniers messages : `docker compose logs --tail 200 backend worker`.

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

### Entreprises (annuaire)

- **Bibliothèque des entreprises** : coordonnées, SIRET, lots sur lesquels l'entreprise est consultée, savoir-faire, qualifications (Qualibat, RGE…), assureur et échéance de l'attestation décennale (signalée quand elle est échue), contacts, notes internes.
- **Import de votre carnet d'adresses** (Excel ou CSV) : les colonnes sont reconnues (Entreprise, Ville, E-mail, Lots, Contact…), les lots sont retrouvés par leur code ou leur intitulé, et une fiche existante est complétée, jamais écrasée. **Export** en un clic.
- **Historique** : chaque fiche montre les projets et les lots pour lesquels l'entreprise a été consultée, et la suite donnée (offre remise, excusée, retenue…).

### DCE (dossier de consultation des entreprises)

Bouton **Préparer le DCE** sur la page du projet :

1. **Contrôle du dossier** : pièces manquantes, champs à compléter dans le RC, le CCAP et les actes d'engagement, ouvrages sans quantité, date limite, plans.
2. **Plans et documents à joindre** : plans, études, diagnostics, PGC… sans limite de nombre, communs ou rattachés à un lot.
3. **Génération du .zip**, classé ainsi :

```
DCE <opération> - Indice A/
  00 - Bordereau des pièces.pdf
  01 - Pièces administratives/    RC, CCAP, Actes d'engagement/ (Word + PDF)
  02 - Pièces techniques/
       Lot 08 - Menuiseries extérieures/   CCTP (PDF), DPGF à compléter (Excel + PDF), Plans du lot/
  03 - Plans/   04 - Études et rapports/   05 - Diagnostics/
  06 - Sécurité et santé (PGC)/   07 - Autres documents/
```

4. **Diffusion**, selon le type de marché :
   - **Marché public** : transmission du DCE au **maître d'ouvrage**, qui le publie sur son profil d'acheteur ; invitation facultative d'entreprises à le consulter sur la plateforme (sans pièce jointe : la plateforme fait foi).
   - **Marché privé** : choix des entreprises de l'annuaire pour chaque lot ; chacune reçoit **un dossier limité à ses lots**, avec une **lettre de consultation** personnalisée.
5. **Suivi des envois** et statut de chaque entreprise (consultée, offre remise, excusée…).

**Envoi des courriels** : renseignez la messagerie du cabinet dans `.env` (lignes `EMAIL_…`, voir `.env.example`), puis relancez `installer.ps1`. Sans messagerie, l'application prépare chaque message (bouton **Ouvrir dans ma messagerie**) et vous l'envoyez vous-même. Un dossier de plus de 20 Mo n'est pas joint : transmettez-le par [FranceTransfert](https://francetransfert.numerique.gouv.fr) (gratuit) ou un service équivalent.

### Analyse des offres (rapport ACT)

Bouton **Analyser les offres** sur la page du projet, un onglet par lot :

1. **Offres reçues** : déposez la DPGF remplie par l'entreprise (Excel, PDF même scanné, Word, CSV) ou son devis, ou saisissez simplement le montant, avec la date de réception (offres hors délai signalées). Les prix sont lus en tâche de fond et rapprochés des ouvrages de votre DPGF : par leur numéro (8.2.1) quand la désignation concorde, sinon par la désignation. Forfaits, remises et moins-values sont pris en compte. Le **total déclaré** (« Total solution de base HT », « Total PSE n°1 HT » ou « Total HT » d'un devis) est comparé à la somme des lignes, et chaque ligne à Qté × PU : en cas d'erreur de calcul, l'offre passe « À vérifier » (le total déclaré est retenu, l'écart est signalé). Variantes à l'initiative de l'entreprise (classées seulement si le RC les autorise), offres écartées avec leur motif, délai proposé.
2. **Comparatif des prix** : tableau ouvrage par ouvrage (estimation et chaque offre, prix le plus bas en vert, le plus élevé en rouge), totaux de la solution de base et de chaque PSE, choix des **PSE retenues**, écarts à l'estimation et à la moyenne, **offres anormalement basses** repérées (seuil réglable) : vous enregistrez la demande de précisions puis votre appréciation des justifications (acceptées, ou rejetées et l'offre est écartée), reprise dans le rapport. Une offre qui ne chiffre pas une PSE retenue n'est pas classée tant qu'elle n'est pas complétée.
3. **Notation et classement** : critères et pondérations repris des paramètres de la consultation (RC). La note de prix est calculée (méthode proportionnelle ou linéaire, notes sur 5, 10, 20 ou 100) ; vous notez les autres critères avec une justification, reprise dans le rapport.
4. **Proposition d'attribution** : offre la mieux classée par défaut (ou une autre offre classée, avec vos observations), montants HT / TVA / TTC ; la validation met à jour l'annuaire (entreprise retenue, autres non retenues). Toute modification ultérieure du classement annule la validation.

**Exports** : rapport ACT d'un lot ou de tous les lots (Word modifiable et PDF, même mise en page que vos pièces écrites, avec récapitulatif général) et comparatif Excel (une feuille par lot).

### GED de chantier

Bouton **Ouvrir la GED** sur la page du projet, une fois les marchés notifiés.

1. **Ouverture de l'espace** : les entreprises retenues à l'analyse des offres sont proposées avec leurs lots et les contacts de l'annuaire. **Chaque personne reçoit son propre code d'accès** (12 caractères) : un nouveau code (invitation renvoyée, départ d'un salarié, code divulgué) ne touche pas ses collègues. Les codes ne sont affichés qu'une fois : envoi par l'application, par votre messagerie, ou fiche d'accès imprimée. Les plans du DCE peuvent être repris comme « Pièces du marché » (indice 0). Ajoutez ensuite la maîtrise d'œuvre associée (BET), le maître d'ouvrage, le contrôleur technique, le CSPS et l'OPC ; un sous-traitant (DC4) ne voit pas les pièces chiffrées du titulaire.
2. **Classement rigoureux** : « Commun à tous » (plans MOE, comptes rendus, planning, PIC, SPS, contrôle technique, pièces du marché, réception), un dossier par **lot** (plans d'exécution, synthèse, notes de calcul, fiches techniques, PV d'essais, PPSPS, réserves, DOE, DIUO, photos, et pièces chiffrées : OS, avenants, devis, situations, sous-traitance) et un espace **réservé à la maîtrise d'œuvre**. Chaque document reçoit une référence (`08-EXE-003`) ; le n° du cartouche de l'entreprise est conservé à côté. Une entreprise dépose dans ses lots ; elle peut consulter les documents techniques des autres lots si vous l'autorisez (option « synthèse »).
3. **Indices** : A, B, C… (ou 0, 1, 2), jamais en arrière ; l'indice à utiliser est toujours signalé « **À utiliser** », les anciens sont conservés et téléchargés avec la mention `PERIME_`. Dépôt de plusieurs fichiers en une fois : l'indice et le n° de plan sont lus dans le nom (« EXE-08-003_C.pdf »), le DWG de même nom est joint comme fichier source, et un document déjà présent reçoit un nouvel indice.
4. **Visas** : les documents d'exécution d'une entreprise partent automatiquement « pour visa », avec une échéance (15 jours par défaut, jours ouvrés). Le BET, le contrôleur technique et le CSPS donnent leur avis ; la maîtrise d'œuvre émet le visa de synthèse (VSO, VAO, refusé, hors mission), avec document annoté et **fiche de visa PDF**. Un indice refusé est marqué « ne pas exécuter ». OS et avenants demandent un **accusé de lecture**.
5. **Notifications** : courriel à chaque nouveauté, regroupé (10 minutes) et limité aux personnes concernées ; chacun choisit « à chaque nouveauté », « récapitulatif quotidien » (7 h, jours ouvrés) ou « aucun ». Récépissé de dépôt à l'entreprise. Journal complet (dépôts, visas, téléchargements, connexions) et **registre des documents** Excel.
6. **Réception puis clôture** : après la réception, les entreprises ne déposent plus que DOE, DIUO, réserves et photos ; l'espace clos n'est plus accessible aux intervenants.
7. **Archive et purge** : **Préparer l'archive complète** produit un .zip vérifié (pièces écrites, DCE, offres et rapport ACT, GED classée par lot avec indices antérieurs, visas et sources, registre Excel avec liens, journal, « Lisez-moi »), enregistré dans le dossier d'archives. Après téléchargement ou copie confirmée sur le serveur du cabinet, **la purge des fichiers** est programmée à 30 jours (annulable) : les données (lots, prix, offres) restent pour vos prochaines estimations. La suppression complète d'un projet est réservée à l'administrateur.

#### Ouvrir la GED aux entreprises sur Internet (gratuit)

Les entreprises se connectent depuis le chantier sur une adresse du domaine du cabinet, par exemple `https://ged.cabinet.fr/ged`. Videz la ligne `GED_INTERNET=` du fichier `.env`, puis relancez `installer.ps1` et répondez **O** à la question « Ouvrir la GED aux entreprises sur Internet ». Choisissez ensuite :

- **1 – Adresse IP fixe de la box (recommandé)** : chez le gestionnaire de votre nom de domaine, créez un enregistrement **A** `ged.cabinet.fr` vers l'adresse IP de la box (l'installateur l'affiche) ; dans la box, redirigez le **port TCP 443** vers le PC (l'installateur affiche l'adresse du PC à indiquer). Le certificat HTTPS est obtenu et renouvelé automatiquement (Let's Encrypt, gratuit). Le port 80 reste fermé.
- **2 – Cloudflare Tunnel** (box sans IP fixe ou sans redirection de port) : nom de domaine géré par Cloudflare (offre gratuite), tunnel créé dans *Zero Trust > Networks > Tunnels*, nom public `ged.cabinet.fr` dirigé vers `http://web:8081`, jeton collé dans l'installateur. Aucun port ouvert ; 100 Mo maximum par fichier.

Seul le portail des intervenants est accessible depuis Internet : il tourne dans un service séparé (`ged`) qui ne connaît ni l'administration ni les outils du cabinet. Le PC doit rester allumé (l'installateur propose de désactiver la mise en veille sur secteur). Docker Desktop ne démarre qu'à l'ouverture d'une session Windows : après un redémarrage (mises à jour), ouvrez une session, ou réglez les heures d'activité de Windows Update. Testez depuis un téléphone en 4G, Wi-Fi coupé. Si Windows demande l'autorisation réseau pour Docker, acceptez pour les réseaux privés. Pour refermer l'accès : `GED_INTERNET=aucun` dans `.env`, puis relancez `installer.ps1`.

Pour que les liens des courriels de la GED fonctionnent depuis les autres postes du cabinet, renseignez `URL_APPLICATION` dans `.env` (par exemple `http://192.168.1.20:8080`).

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
├── restaurer.ps1          Restauration d'une sauvegarde (y compris sur un nouveau PC)
├── docker-compose.yml     Les 7 services : base, redis, backend, worker, voix, ollama, web
├── docker-compose.serveur.yml    Fichiers, archives et sauvegardes sur le serveur de l'agence (partage Windows)
├── docker-compose.internet.yml   GED sur Internet par l'adresse publique (service ged, port 443)
├── docker-compose.tunnel.yml     GED sur Internet par Cloudflare Tunnel (services ged et tunnel)
├── .env.example           Modèle de configuration (copié en .env par l'installateur)
├── donnees/               Fichiers importés (non versionnés)
├── backend/               Python 3.12 · Django 5.2 · Django Ninja · Celery
│   ├── config/            Paramètres, API, tâches de fond
│   ├── comptes/           Utilisateurs et rôles (Administrateur, MOE, Entreprise)
│   ├── referentiel/       Nomenclature des lots (modifiable dans Paramétrage)
│   ├── bibliotheque/      Documents de référence, import, lecture (conversion, OCR)
│   ├── articles/          Découpage en articles, lignes de prix, normes citées
│   ├── projets/           Projets, lots, PSE, CCTP et DPGF, CCAP / RC / AE, modèles, exports Word / PDF / Excel
│   ├── entreprises/       Annuaire des entreprises (import, historique)
│   ├── dce/               Dossier de consultation : contrôle, .zip classé, envois
│   ├── offres/            Analyse des offres : lecture des DPGF remplies, comparatif, notation, rapport ACT
│   ├── ged/               GED de chantier : accès par code, droits, indices, visas, notifications, archive et purge
│   ├── sauvegardes/       Sauvegarde de chaque nuit (base vérifiée, configuration, fichiers) et restauration
│   └── assistant/         Assistant IA local : recherche par le sens, conversations, voix
└── frontend/              React 19 · TypeScript · Vite · Tailwind CSS
    └── src/
        ├── pages/         Connexion, Tableau de bord, Projets, éditeurs, DCE, Analyse des offres, GED, Entreprises, Documents, Articles, Prix, Assistant
        ├── ged/           Explorateur des documents, dépôt, visas, intervenants, clôture (communs au cabinet et au portail)
        ├── portail/       Portail des intervenants (ged.html), seul servi sur l'adresse Internet
        ├── components/    En-tête, liste des lots, zone d'import, tableau
        └── api/           Accès à l'API (session + protection CSRF)
```

| Service | Rôle |
|---|---|
| `base` | PostgreSQL 16 |
| `redis` | File d'attente des tâches (Valkey, fork open source de Redis), conservée dans le volume `valkey_donnees` |
| `backend` | API Django (gunicorn) |
| `worker` | Tâches de fond : lecture, conversion, OCR et découpage des documents, lecture des offres, lecture des documents par l'IA ; tâches planifiées (sauvegarde de chaque nuit, récapitulatif GED du matin, relance des courriels, purges programmées). Mémoire limitée à 6 Go |
| `voix` | Voix de l'assistant : transcription (Whisper) et lecture à voix haute (Piper), chargées une seule fois |
| `ollama` | Moteur d'IA local de l'assistant (modèles dans le volume `modeles_ia`) |
| `web` | Caddy : sert l'interface et relaie l'API ; en mode Internet, site HTTPS public limité au portail de la GED |
| `ged` | (mode Internet) Processus Django séparé, limité au portail des intervenants |
| `tunnel` | (mode Cloudflare Tunnel) Relais cloudflared |

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
- [x] **2** DCE : dossier .zip classé, annuaire des entreprises, envois public / privé
- [x] **3** Analyse des offres : lecture des DPGF remplies, comparatif, notation, rapport ACT
- [x] **4** GED de chantier : accès par code personnel, classement par lots, indices, visas, notifications, accès Internet, archive et purge
