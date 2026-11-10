<#
  D’Aplomb - installation et démarrage sous Windows
  Vos projets d’aplomb, de l’appel d’offres à la réception.

  Utilisation : clic droit sur ce fichier > « Exécuter avec PowerShell »
  ou, dans PowerShell :  powershell -ExecutionPolicy Bypass -File .\installer.ps1

  Le script peut être relancé sans risque : il conserve la configuration
  et les données existantes, et met à jour l'application.
  Pour remettre une sauvegarde en place : restaurer.ps1.
#>

Set-Location -LiteralPath $PSScriptRoot

Write-Host "D’Aplomb - installation et démarrage" -ForegroundColor Cyan
Write-Host "Vos projets d’aplomb, de l’appel d’offres à la réception."

function Ecrire-Etape([string]$texte) {
    Write-Host ""
    Write-Host "==> $texte" -ForegroundColor Yellow
}

function Arreter([string]$message) {
    # Connexion au partage du serveur ouverte par ce script : fermée avant de quitter.
    if ($script:connexionPartage) { net use $script:connexionPartage /delete /y 2>&1 | Out-Null }
    Write-Host ""
    Write-Host $message -ForegroundColor Red
    Read-Host "Appuyez sur Entrée pour fermer"
    exit 1
}

function Nouveau-Secret([int]$longueur) {
    $octets = New-Object byte[] 96
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($octets)
    $texte = [Convert]::ToBase64String($octets) -replace '[^A-Za-z0-9]', ''
    return $texte.Substring(0, $longueur)
}

# Lecture et écriture d'une ligne NOM=valeur du fichier .env.
function Lire-Variable([string]$contenu, [string]$nom) {
    $trouve = [regex]::Match($contenu, "(?m)^$nom=([^\r\n]*)")
    if ($trouve.Success) {
        $valeur = $trouve.Groups[1].Value.Trim()
        # Valeur entre apostrophes droites : Docker Compose la lit telle quelle (espaces, \, $ et # compris).
        if ($valeur.Length -ge 2 -and $valeur.StartsWith("'") -and $valeur.EndsWith("'")) { $valeur = $valeur.Substring(1, $valeur.Length - 2) }
        return $valeur
    }
    return ""
}

# Valeur à écrire dans .env : entre apostrophes droites dès qu'elle contient autre chose que des
# lettres, des chiffres et . _ - : / @ (chemin \\SERVEUR\..., mot de passe avec $ ou #, espaces).
function Valeur-Env([string]$valeur) {
    if ($valeur -match '^[A-Za-z0-9._:/@-]*$') { return $valeur }
    return "'$valeur'"
}

function Definir-Variable([string]$contenu, [string]$nom, [string]$valeur) {
    $ligne = "$nom=$valeur"
    if ($contenu -match "(?m)^$nom=") {
        return [regex]::Replace($contenu, "(?m)^$nom=[^\r\n]*", $ligne.Replace('$', '$$'))
    }
    return $contenu.TrimEnd() + "`n$ligne`n"
}

function Enregistrer-Env([string]$contenu) {
    # UTF-8 sans BOM : Docker Compose ne lit pas correctement un fichier avec BOM.
    [System.IO.File]::WriteAllText($cheminEnv, $contenu, (New-Object System.Text.UTF8Encoding($false)))
}

# Fichiers Docker Compose à utiliser : carte graphique, GED sur Internet, stockage sur le serveur
# de l'agence (ligne COMPOSE_FILE).
function Fichiers-Compose([bool]$gpu, [string]$modeGed, [bool]$serveur) {
    $liste = @("docker-compose.yml")
    if ($gpu) { $liste += "docker-compose.gpu.yml" }
    if ($modeGed -eq "ip") { $liste += "docker-compose.internet.yml" }
    if ($modeGed -eq "tunnel") { $liste += "docker-compose.tunnel.yml" }
    if ($serveur) { $liste += "docker-compose.serveur.yml" }
    return ($liste -join ";")
}

function Ligne-Compose([string]$contenu, [string]$fichiers) {
    if ($fichiers -eq "docker-compose.yml") {
        return (($contenu -split "`r?`n") | Where-Object { $_ -notmatch '^COMPOSE_FILE=' }) -join "`n"
    }
    return Definir-Variable $contenu "COMPOSE_FILE" $fichiers
}

# --- Stockage sur le serveur de l'agence (dossier partagé Windows) ------------------------------

$script:connexionPartage = ""

# Sortie d'une commande (lignes et erreurs) en un seul texte.
function Texte-Sortie($sortie) {
    return ((@($sortie) | ForEach-Object { "$_" }) -join "`n").Trim()
}

# Adresse IPv4 du serveur : Docker ne connaît pas les noms du réseau Windows.
function Adresse-Serveur([string]$nom) {
    if ($nom -match '^\d{1,3}(\.\d{1,3}){3}$') { return $nom }
    try {
        foreach ($adresse in [System.Net.Dns]::GetHostAddresses($nom)) {
            $texte = $adresse.ToString()
            if ($adresse.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and -not $texte.StartsWith("127.") -and -not $texte.StartsWith("169.254.")) {
                return $texte
            }
        }
    } catch { }
    return ""
}

# Options de montage du partage : les mêmes que dans docker-compose.serveur.yml.
function Options-Partage([string]$adresse, [string]$utilisateur, [string]$motDePasse, [string]$domaine) {
    $options = "addr=$adresse,username=$utilisateur,password=$motDePasse,"
    if ($domaine) { $options += "domain=$domaine," }
    return $options + "vers=3.0,uid=0,gid=0,file_mode=0660,dir_mode=0770,nounix,noserverino"
}

# Connexion de Windows au partage avec le compte dédié, par l'adresse IP comme Docker : une connexion
# déjà ouverte au nom du serveur avec le compte de la session ne gêne pas.
function Connecter-Partage([string]$adresse, [string]$partage, [string]$compte, [string]$motDePasse) {
    Deconnecter-Partage
    $racine = "\\$adresse\" + ($partage -split '/')[0]
    $sortie = net use $racine $motDePasse "/user:$compte" /persistent:no 2>&1
    if ($LASTEXITCODE -ne 0) {
        $texte = Texte-Sortie $sortie
        if ($texte -match '1219') {
            $texte += "`nUne connexion à $racine est déjà ouverte avec un autre compte : fermez-la (net use $racine /delete) ou redémarrez le PC, puis relancez ce script."
        }
        return "Connexion au dossier partagé refusée : $texte"
    }
    $script:connexionPartage = $racine
    return ""
}

function Deconnecter-Partage {
    if ($script:connexionPartage) {
        net use $script:connexionPartage /delete /y 2>&1 | Out-Null
        $script:connexionPartage = ""
    }
}

# Connexion avec le compte enregistré dans .env ; renvoie le chemin Windows du dossier (\\adresse\partage).
function Connecter-Partage-Env {
    $adresse = Lire-Variable $script:contenuEnv "SERVEUR_ADRESSE"
    $partage = Lire-Variable $script:contenuEnv "SERVEUR_PARTAGE"
    $domaine = Lire-Variable $script:contenuEnv "SERVEUR_DOMAINE"
    $compte = Lire-Variable $script:contenuEnv "SERVEUR_UTILISATEUR"
    if ($domaine) { $compte = "$domaine\$compte" }
    if (-not $script:connexionPartage) {
        $erreur = Connecter-Partage $adresse $partage $compte (Lire-Variable $script:contenuEnv "SERVEUR_MOT_DE_PASSE")
        if ($erreur) { Write-Host $erreur -ForegroundColor Yellow; return "" }
    }
    return "\\$adresse\" + $partage.Replace('/', '\')
}

# Crée les sous-dossiers fichiers, archives et sauvegardes, puis écrit et efface un fichier d'essai.
function Preparer-Dossiers-Partage([string]$dossier) {
    try {
        foreach ($sous in @("fichiers", "archives", "sauvegardes")) {
            [System.IO.Directory]::CreateDirectory((Join-Path $dossier $sous)) | Out-Null
        }
        $essai = Join-Path $dossier "sauvegardes\essai-daplomb.tmp"
        [System.IO.File]::WriteAllText($essai, "Essai d’écriture de D’Aplomb : ce fichier peut être supprimé.")
        [System.IO.File]::Delete($essai)
    } catch {
        return "Le compte se connecte, mais ne peut pas écrire dans $dossier : $($_.Exception.Message)"
    }
    return ""
}

# Montage du sous-dossier « sauvegardes » par Docker, exactement comme le feront les services.
function Tester-Partage-Docker([string]$adresse, [string]$partage, [string]$options) {
    $volume = "application-ao-essai-serveur"
    docker pull valkey/valkey:8-alpine 2>&1 | Out-Null
    docker volume rm -f $volume 2>&1 | Out-Null
    $sortie = docker volume create --driver local --opt type=cifs --opt "device=//$adresse/$partage/sauvegardes" --opt "o=$options" $volume 2>&1
    if ($LASTEXITCODE -ne 0) { return "Docker ne peut pas préparer l’accès au serveur : $(Texte-Sortie $sortie)" }
    $sortie = docker run --rm -v "${volume}:/essai" --entrypoint sh valkey/valkey:8-alpine -c "echo essai > /essai/essai-docker.tmp && rm -f /essai/essai-docker.tmp" 2>&1
    $code = $LASTEXITCODE
    docker volume rm -f $volume 2>&1 | Out-Null
    if ($code -eq 0) { return "" }
    $texte = Texte-Sortie $sortie
    $conseil = ""
    if ($texte -match 'permission denied|error\(13\)') { $conseil = "Compte ou mot de passe refusé par le serveur, ou compte sans droit de modification sur ce dossier." }
    elseif ($texte -match 'host is down|no route to host|connection refused|timed out|temporarily unavailable') { $conseil = "Le serveur ne répond pas depuis Docker : vérifiez qu’il est allumé et que son pare-feu autorise le partage de fichiers (port 445)." }
    elseif ($texte -match 'no such file') { $conseil = "Dossier introuvable sur le serveur : vérifiez le nom du partage." }
    elseif ($texte -match 'not supported|invalid argument') { $conseil = "Le serveur refuse la connexion en SMB 3 : demandez à votre prestataire informatique de l’activer pour ce partage." }
    return "Docker ne peut pas écrire dans le dossier partagé.`n$texte`n$conseil".Trim()
}

# Questions : dossier partagé, compte et mot de passe ; vérifie l'accès depuis Windows puis depuis Docker.
# Renvoie $true et enregistre les réglages dans $script:contenuEnv si tout fonctionne.
function Configurer-Serveur {
    Write-Host ""
    Write-Host "Préparez sur le serveur un dossier partagé (par exemple \\SERVEUR\DAplomb) et un compte Windows"
    Write-Host "dédié à D’Aplomb (par exemple « daplomb »), autorisé en modification sur ce seul dossier."
    $chemin = (Read-Host "Dossier partagé du serveur (par exemple \\SERVEUR\DAplomb)").Trim().Trim('"').Replace('/', '\').TrimEnd('\')
    $parties = @($chemin.TrimStart('\').Split('\') | Where-Object { $_ })
    if (-not $chemin.StartsWith('\\') -or $parties.Count -lt 2) {
        Write-Host "Chemin non reconnu : il commence par \\, suivi du nom du serveur et du nom du partage." -ForegroundColor Yellow
        return $false
    }
    $nomServeur = $parties[0]
    $partage = ($parties[1..($parties.Count - 1)]) -join '/'
    $adresse = Adresse-Serveur $nomServeur
    if (-not $adresse) {
        Write-Host "Serveur « $nomServeur » introuvable sur le réseau : vérifiez son nom, ou indiquez son adresse IP (\\192.168.1.10\DAplomb)." -ForegroundColor Yellow
        return $false
    }
    Write-Host "Serveur $nomServeur : adresse $adresse."
    $compte = (Read-Host "Compte dédié (DOMAINE\utilisateur, ou SERVEUR\utilisateur pour un compte local du serveur)").Trim()
    $domaine = ""
    $utilisateur = $compte
    if ($compte -match '^([^\\]+)\\(.+)$') { $domaine = $Matches[1]; $utilisateur = $Matches[2] }
    elseif ($compte -match '^([^@]+)@(.+)$') { $utilisateur = $Matches[1]; $domaine = $Matches[2] }
    if ($domaine -eq ".") { $domaine = $(if ($nomServeur -match '^\d{1,3}(\.\d{1,3}){3}$') { "" } else { $nomServeur }) }
    if (-not $utilisateur -or "$utilisateur$domaine" -match "[,'`"=\\]") {
        Write-Host "Compte non reconnu." -ForegroundColor Yellow
        return $false
    }
    $secret = Read-Host "Mot de passe de ce compte" -AsSecureString
    $motDePasse = (New-Object System.Management.Automation.PSCredential("compte", $secret)).GetNetworkCredential().Password
    if (-not $motDePasse) {
        Write-Host "Mot de passe vide : le serveur refusera la connexion." -ForegroundColor Yellow
        return $false
    }
    if ($motDePasse -match "[,'`"]") {
        Write-Host "Ce mot de passe contient une virgule ou un guillemet, que Docker ne sait pas transmettre au serveur :" -ForegroundColor Yellow
        Write-Host "donnez au compte dédié un mot de passe sans virgule ni guillemet, puis recommencez." -ForegroundColor Yellow
        return $false
    }
    $compteWindows = $utilisateur
    if ($domaine) { $compteWindows = "$domaine\$utilisateur" }
    $dossierWindows = "\\$adresse\" + $partage.Replace('/', '\')

    Write-Host "Vérification de l’accès depuis ce PC…"
    $erreur = Connecter-Partage $adresse $partage $compteWindows $motDePasse
    if (-not $erreur) { $erreur = Preparer-Dossiers-Partage $dossierWindows }
    if (-not $erreur) {
        Write-Host "Vérification de l’accès depuis Docker…"
        $erreur = Tester-Partage-Docker $adresse $partage (Options-Partage $adresse $utilisateur $motDePasse $domaine)
    }
    if ($erreur) {
        Write-Host $erreur -ForegroundColor Yellow
        Deconnecter-Partage
        return $false
    }
    Write-Host "Accès au dossier vérifié (lecture, écriture, sous-dossiers fichiers, archives et sauvegardes)." -ForegroundColor Green
    $script:contenuEnv = Definir-Variable $script:contenuEnv "SERVEUR_CHEMIN_AFFICHE" (Valeur-Env ("\\$nomServeur\" + $partage.Replace('/', '\')))
    $script:contenuEnv = Definir-Variable $script:contenuEnv "SERVEUR_ADRESSE" $adresse
    $script:contenuEnv = Definir-Variable $script:contenuEnv "SERVEUR_PARTAGE" (Valeur-Env $partage)
    $script:contenuEnv = Definir-Variable $script:contenuEnv "SERVEUR_UTILISATEUR" (Valeur-Env $utilisateur)
    $script:contenuEnv = Definir-Variable $script:contenuEnv "SERVEUR_MOT_DE_PASSE" (Valeur-Env $motDePasse)
    $script:contenuEnv = Definir-Variable $script:contenuEnv "SERVEUR_DOMAINE" (Valeur-Env $domaine)
    Write-Host "Le mot de passe de ce compte est enregistré dans le fichier .env de ce dossier, comme les autres clés" -ForegroundColor Cyan
    Write-Host "de l’application : utilisez bien un compte dédié, limité au dossier D’Aplomb, et ne partagez jamais .env." -ForegroundColor Cyan
    return $true
}

# Dossier du PC indiqué dans .env : chemin complet, ou relatif au dossier de l'application.
function Chemin-Pc([string]$valeur, [string]$defaut) {
    if (-not $valeur) { $valeur = $defaut }
    $valeur = $valeur.Replace('/', '\')
    if ([System.IO.Path]::IsPathRooted($valeur)) { return $valeur }
    return (Join-Path $PSScriptRoot ($valeur -replace '^\.\\', ''))
}

function Contient-Fichiers([string]$dossier) {
    if (-not (Test-Path -LiteralPath $dossier)) { return $false }
    return [bool](Get-ChildItem -LiteralPath $dossier -Recurse -File -Force -ErrorAction SilentlyContinue | Select-Object -First 1)
}

# Arrêt de tous les services de l'application (aucun fichier ne doit changer pendant une copie).
function Arreter-Application {
    $conteneurs = @(docker ps -q --filter "label=com.docker.compose.project=application-ao")
    if ($conteneurs.Count -gt 0) {
        Write-Host "Arrêt de l’application pendant la copie des fichiers…"
        docker stop $conteneurs | Out-Null
    }
}

# Copie des fichiers nouveaux ou plus récents (un fichier plus récent à l'arrivée n'est jamais écrasé).
function Copier-Dossier([string]$source, [string]$destination) {
    if (-not (Contient-Fichiers $source)) { return $true }
    Write-Host "Copie de « $source » vers « $destination »…"
    robocopy $source $destination /E /XO /R:2 /W:5 /NP /NFL /NDL /NJH | Out-Host
    if ($LASTEXITCODE -ge 8) {
        Write-Host "La copie a échoué (code robocopy $LASTEXITCODE)." -ForegroundColor Red
        return $false
    }
    return $true
}

Ecrire-Etape "Vérification de Docker Desktop"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Arreter "Docker Desktop n'est pas installé. Téléchargez-le sur https://www.docker.com/products/docker-desktop/ puis relancez ce script."
}
docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Arreter "Docker Desktop n'est pas démarré. Ouvrez-le, attendez qu'il indique « Engine running », puis relancez ce script."
}
Write-Host "Docker Desktop est prêt."

Ecrire-Etape "Préparation de la configuration (.env)"
$cheminEnv = Join-Path $PSScriptRoot ".env"
if (Test-Path -LiteralPath $cheminEnv) {
    Write-Host "Le fichier .env existe déjà : il est conservé."
} else {
    # Une base existe déjà (application installée dans un autre dossier, ou .env supprimé) : un nouveau .env
    # aurait un autre mot de passe (base inaccessible) et une autre clé (codes d'accès de la GED invalides).
    docker volume inspect application-ao_base_donnees 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Arreter ("Une installation de D’Aplomb existe déjà sur ce PC (sa base de données est conservée par Docker),`n" +
            "mais le fichier .env est absent de ce dossier. Un nouveau .env rendrait la base inaccessible et`n" +
            "invaliderait les codes d’accès des entreprises à la GED.`n`n" +
            "  - Nouvelle version décompressée dans un autre dossier : copiez le fichier .env et le dossier donnees`n" +
            "    de l’ancien dossier de l’application dans celui-ci, puis relancez ce script.`n" +
            "  - Fichier .env perdu : lancez restaurer.ps1, qui le reprend dans les sauvegardes de chaque nuit.")
    }
    $modele = [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot ".env.example"))
    $contenu = $modele.Replace("DJANGO_SECRET_KEY=__A_GENERER__", "DJANGO_SECRET_KEY=$(Nouveau-Secret 50)")
    $contenu = $contenu.Replace("POSTGRES_PASSWORD=__A_GENERER__", "POSTGRES_PASSWORD=$(Nouveau-Secret 32)")
    # UTF-8 sans BOM : Docker Compose ne lit pas correctement un fichier avec BOM.
    [System.IO.File]::WriteAllText($cheminEnv, $contenu, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Fichier .env créé avec des clés aléatoires."
}

Ecrire-Etape "Assistant IA : réglages selon votre ordinateur"
$contenuEnv = [System.IO.File]::ReadAllText($cheminEnv)
if ($contenuEnv -notmatch '(?m)^IA_MODELE=') {
    # Fichier .env d'une version précédente : ajout des réglages de l'assistant.
    $contenuEnv = $contenuEnv.TrimEnd() + "`n`n# Assistant IA local`nIA_MODELE=qwen3.5:9b`nIA_WHISPER=large-v3-turbo`n"
}
# Docker Desktop (WSL 2) ne reçoit qu'une partie de la mémoire du PC : c'est elle qui compte.
$memoireDocker = 0
$octets = docker info --format "{{.MemTotal}}" 2>$null
if ($LASTEXITCODE -eq 0 -and "$octets".Trim() -match '^\d+$') { $memoireDocker = [math]::Round([double]"$octets".Trim() / 1GB, 1) }
$memoirePc = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
Write-Host "Mémoire du PC : $memoirePc Go ; mémoire disponible pour Docker : $memoireDocker Go."
if ($memoireDocker -gt 0 -and $memoireDocker -lt 14) {
    $contenuEnv = $contenuEnv -replace '(?m)^IA_MODELE=qwen3\.5:9b', 'IA_MODELE=qwen3.5:4b'
    Write-Host "Modèle léger choisi pour l'assistant (qwen3.5:4b)."
    if ($memoirePc -ge 24) {
        Write-Host "Astuce : pour le modèle complet, donnez plus de mémoire à Docker. Créez le fichier"
        Write-Host "  $env:USERPROFILE\.wslconfig  contenant :  [wsl2]  puis  memory=$([math]::Floor($memoirePc * 0.75))GB"
        Write-Host "puis redémarrez le PC et relancez ce script (remettez IA_MODELE=qwen3.5:9b dans .env)."
    }
}
if ($memoireDocker -gt 0 -and $memoireDocker -lt 10) {
    $contenuEnv = $contenuEnv -replace '(?m)^IA_WHISPER=large-v3-turbo', 'IA_WHISPER=small'
}
$gpu = (Lire-Variable $contenuEnv "COMPOSE_FILE") -match 'gpu'
if (-not $gpu -and (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
    # Une carte NVIDIA ne suffit pas : Docker doit pouvoir l'utiliser (pilote récent, moteur WSL 2).
    Write-Host "Carte graphique NVIDIA détectée : vérification de son accès depuis Docker…"
    docker pull ollama/ollama:0.40.15 | Out-Null
    docker run --rm --gpus all --entrypoint /bin/true ollama/ollama:0.40.15 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $gpu = $true
        Write-Host "La carte graphique sera utilisée par l'assistant."
    } else {
        Write-Host "Docker ne peut pas utiliser la carte graphique (pilote NVIDIA à mettre à jour ?) : l'assistant utilisera le processeur."
    }
}

Ecrire-Etape "GED de chantier : accès des entreprises par Internet (facultatif)"
foreach ($nom in @("URL_APPLICATION", "DOSSIER_ARCHIVES_PC", "GED_URL_PUBLIQUE", "TUNNEL_TOKEN")) {
    if ($contenuEnv -notmatch "(?m)^$nom=") { $contenuEnv = Definir-Variable $contenuEnv $nom "" }
}
$modeGed = Lire-Variable $contenuEnv "GED_INTERNET"
if ($modeGed -in @("ip", "tunnel")) {
    Write-Host "Déjà ouverte sur Internet ($modeGed) : $(Lire-Variable $contenuEnv 'GED_URL_PUBLIQUE')"
    Write-Host "(Pour la fermer : mettez GED_INTERNET=aucun dans .env puis relancez ce script.)"
} elseif ($modeGed -eq "aucun") {
    Write-Host "GED réservée au réseau du cabinet."
    Write-Host "(Pour l'ouvrir aux entreprises : videz la ligne GED_INTERNET= du fichier .env, puis relancez ce script et répondez O.)"
} else {
    Write-Host "Sans cette option, la GED n'est accessible que sur le réseau du cabinet."
    Write-Host "Avec elle, les entreprises s'y connectent depuis le chantier avec leur code d'accès."
    $reponse = Read-Host "Ouvrir la GED aux entreprises sur Internet ? (O/N, N par défaut)"
    # « aucun » n'est écrit qu'en cas de refus : après un essai raté, la question revient.
    if ($reponse -match '^\s*[oO]') {
        Write-Host ""
        Write-Host "Deux solutions gratuites :"
        Write-Host "  1 = adresse IP fixe de la box du cabinet (recommandé : rien ne transite par un tiers)"
        Write-Host "  2 = Cloudflare Tunnel (box sans IP fixe ; nom de domaine géré chez Cloudflare ; 100 Mo par fichier)"
        $choix = Read-Host "Votre choix (1 ou 2)"
        $nomGed = (Read-Host "Nom de la GED, sur le domaine du cabinet (par exemple ged.cabinet.fr)").Trim().ToLower()
        $nomGed = ($nomGed -replace '^https?://', '' -replace '/.*$', '')
        if ($nomGed -notmatch '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$') {
            Write-Host "Nom invalide : la GED reste réservée au réseau du cabinet. Relancez le script pour réessayer." -ForegroundColor Yellow
        } elseif ($choix -eq "1") {
            $ipBox = ""
            try { $ipBox = (Resolve-DnsName -Name myip.opendns.com -Server resolver1.opendns.com -Type A -ErrorAction Stop | Where-Object { $_.Type -eq 'A' } | Select-Object -First 1).IPAddress } catch { }
            $ipNom = ""
            try { $ipNom = (Resolve-DnsName -Name $nomGed -Server 1.1.1.1 -Type A -DnsOnly -ErrorAction Stop | Where-Object { $_.Type -eq 'A' } | Select-Object -First 1).IPAddress } catch { }
            Write-Host "Adresse publique de la box : $(if ($ipBox) { $ipBox } else { 'inconnue' }) ; $nomGed pointe vers : $(if ($ipNom) { $ipNom } else { 'aucune adresse' })"
            $continuer = $true
            if (-not $ipNom -or ($ipBox -and $ipNom -ne $ipBox)) {
                Write-Host "Chez le gestionnaire du nom de domaine, créez un enregistrement A : $nomGed -> $ipBox" -ForegroundColor Yellow
                Write-Host "(Une adresse qui change chaque jour ne convient pas : demandez une IP fixe à votre opérateur, ou choisissez 2.)" -ForegroundColor Yellow
                $continuer = (Read-Host "Continuer quand même (le certificat sera obtenu dès que le nom pointera vers la box) ? (O/N)") -match '^\s*[oO]'
            }
            if ($continuer) {
                $portPc = "443"
                if (Get-NetTCPConnection -LocalPort 443 -State Listen -ErrorAction SilentlyContinue) {
                    $portPc = "8443"
                    Write-Host "Le port 443 de ce PC est déjà utilisé : la GED écoutera sur le port 8443." -ForegroundColor Yellow
                }
                # Adresse de ce PC sur le réseau du cabinet : carte reliée à la box (passerelle par défaut).
                $ipPc = (Get-NetIPConfiguration -ErrorAction SilentlyContinue | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } | Select-Object -First 1).IPv4Address.IPAddress
                if (-not $ipPc) { $ipPc = "(adresse IP de ce PC)" }
                $contenuEnv = Definir-Variable $contenuEnv "GED_PORT_HTTPS" $portPc
                $contenuEnv = Definir-Variable $contenuEnv "GED_URL_PUBLIQUE" "https://$nomGed"
                $contenuEnv = Definir-Variable $contenuEnv "GED_INTERNET" "ip"
                $modeGed = "ip"
                Write-Host ""
                Write-Host "À régler dans l'interface de la box (redirection de port / NAT) :" -ForegroundColor Cyan
                Write-Host "  port externe TCP 443  ->  $ipPc, port $portPc" -ForegroundColor Cyan
                Write-Host "  et, si possible, réservez l'adresse $ipPc à ce PC (bail DHCP permanent)." -ForegroundColor Cyan
                Write-Host "  Le port 80 n'a pas besoin d'être ouvert."
            } else {
                Write-Host "La GED reste réservée au réseau du cabinet. Relancez le script quand le nom pointera vers la box." -ForegroundColor Yellow
            }
        } elseif ($choix -eq "2") {
            Write-Host ""
            Write-Host "Dans Cloudflare (gratuit) : Zero Trust > Networks > Tunnels > Create a tunnel (Cloudflared)," -ForegroundColor Cyan
            Write-Host "puis « Public hostname » : $nomGed  ->  Service HTTP  web:8081" -ForegroundColor Cyan
            Write-Host "Copiez le jeton affiché dans la commande d'installation (la longue suite après --token)." -ForegroundColor Cyan
            $jeton = (Read-Host "Jeton du tunnel").Trim()
            if ($jeton -match '^[A-Za-z0-9_+/=\-]{40,}$') {
                $contenuEnv = Definir-Variable $contenuEnv "TUNNEL_TOKEN" $jeton
                $contenuEnv = Definir-Variable $contenuEnv "GED_URL_PUBLIQUE" "https://$nomGed"
                $contenuEnv = Definir-Variable $contenuEnv "GED_INTERNET" "tunnel"
                $modeGed = "tunnel"
            } else {
                Write-Host "Jeton non reconnu : la GED reste réservée au réseau du cabinet. Relancez le script pour réessayer." -ForegroundColor Yellow
            }
        } else {
            Write-Host "Choix non reconnu : la GED reste réservée au réseau du cabinet. Relancez le script pour réessayer." -ForegroundColor Yellow
        }
        # IP fixe ou tunnel : le PC doit rester joignable.
        if ($modeGed -in @("ip", "tunnel")) {
            if ((Read-Host "Empêcher la mise en veille de ce PC lorsqu'il est branché (la GED reste joignable) ? (O/N)") -match '^\s*[oO]') {
                powercfg /change standby-timeout-ac 0
                powercfg /change hibernate-timeout-ac 0
                Write-Host "Mise en veille désactivée sur secteur."
            }
        }
    } else {
        $contenuEnv = Definir-Variable $contenuEnv "GED_INTERNET" "aucun"
    }
}
if ($modeGed -notin @("ip", "tunnel")) { $modeGed = "" }
# GED refermée : plus d'adresse Internet dans les courriels ni à l'écran (redemandée à la réouverture).
if (-not $modeGed) { $contenuEnv = Definir-Variable $contenuEnv "GED_URL_PUBLIQUE" "" }

Ecrire-Etape "Stockage sur le serveur de l’agence (recommandé)"
if ($contenuEnv -notmatch '(?m)^STOCKAGE=') {
    # Fichier .env d'une version précédente : ajout des réglages du stockage et de la sauvegarde.
    $contenuEnv = $contenuEnv.TrimEnd() + "`n`n# Stockage sur le serveur de l'agence et sauvegarde de chaque nuit (explications : .env.example)`n"
}
foreach ($nom in @("STOCKAGE", "SERVEUR_CHEMIN_AFFICHE", "SERVEUR_ADRESSE", "SERVEUR_PARTAGE", "SERVEUR_UTILISATEUR", "SERVEUR_MOT_DE_PASSE", "SERVEUR_DOMAINE", "VOLUME_FICHIERS", "VOLUME_ARCHIVES", "DOSSIER_SAUVEGARDES_PC")) {
    if ($contenuEnv -notmatch "(?m)^$nom=") { $contenuEnv = Definir-Variable $contenuEnv $nom "" }
}
foreach ($reglage in @(@("SAUVEGARDE_HEURE", "2:30"), @("SAUVEGARDE_JOURS", "14"), @("SAUVEGARDE_MOIS", "6"))) {
    if ($contenuEnv -notmatch "(?m)^$($reglage[0])=") { $contenuEnv = Definir-Variable $contenuEnv $reglage[0] $reglage[1] }
}
$stockage = (Lire-Variable $contenuEnv "STOCKAGE").ToLower()
# Emplacement réellement utilisé jusqu'ici (volumes du serveur montés ou non) et dossier du serveur.
$serveurAvant = (Lire-Variable $contenuEnv "COMPOSE_FILE") -match 'serveur'
$dossierAvant = Lire-Variable $contenuEnv "SERVEUR_CHEMIN_AFFICHE"
$modeServeur = $false
if ($stockage -eq "serveur") {
    # L'adresse du serveur peut avoir changé (nouveau serveur, réseau renuméroté) : elle est recherchée à nouveau.
    $nomServeur = ((Lire-Variable $contenuEnv "SERVEUR_CHEMIN_AFFICHE").TrimStart('\') -split '\\')[0]
    $adresse = Lire-Variable $contenuEnv "SERVEUR_ADRESSE"
    if ($nomServeur) {
        $nouvelle = Adresse-Serveur $nomServeur
        if ($nouvelle -and $nouvelle -ne $adresse) {
            Write-Host "Le serveur $nomServeur a changé d’adresse : $nouvelle (au lieu de $adresse)."
            $adresse = $nouvelle
            $contenuEnv = Definir-Variable $contenuEnv "SERVEUR_ADRESSE" $adresse
        }
    }
    $partage = Lire-Variable $contenuEnv "SERVEUR_PARTAGE"
    $utilisateur = Lire-Variable $contenuEnv "SERVEUR_UTILISATEUR"
    if (-not $adresse -or -not $partage -or -not $utilisateur) {
        $erreur = "Réglages du serveur incomplets dans .env (lignes SERVEUR_…)."
    } else {
        Write-Host "Vérification de l’accès au dossier $(Lire-Variable $contenuEnv 'SERVEUR_CHEMIN_AFFICHE')…"
        $erreur = Tester-Partage-Docker $adresse $partage (Options-Partage $adresse $utilisateur (Lire-Variable $contenuEnv "SERVEUR_MOT_DE_PASSE") (Lire-Variable $contenuEnv "SERVEUR_DOMAINE"))
    }
    if ($erreur) {
        Write-Host $erreur -ForegroundColor Yellow
        if ((Read-Host "Indiquer à nouveau le dossier partagé et le compte ? (O/N)") -match '^\s*[oO]' -and (Configurer-Serveur)) {
            $modeServeur = $true
        } else {
            Arreter ("Les fichiers de l’application sont sur le serveur de l’agence : elle ne peut pas démarrer sans lui.`n" +
                "Vérifiez que le serveur est allumé et que le compte fonctionne, puis relancez ce script.")
        }
    } else {
        $modeServeur = $true
    }
} elseif ($stockage -ne "pc") {
    Write-Host "Recommandé : les fichiers de l’application, les archives de fin de chantier et les sauvegardes de"
    Write-Host "chaque nuit sont enregistrés dans un dossier partagé du serveur de l’agence, déjà sauvegardé."
    Write-Host "Si ce PC tombe en panne, rien n’est perdu. La base de données reste sur ce PC ; sa copie vérifiée"
    Write-Host "part chaque nuit sur le serveur."
    $reponse = Read-Host "Enregistrer les fichiers et les sauvegardes sur le serveur de l’agence ? (O/N, O par défaut)"
    # « pc » n'est écrit qu'en cas de refus : après un essai raté, la question revient.
    if ($reponse -match '^\s*[nN]') {
        $contenuEnv = Definir-Variable $contenuEnv "STOCKAGE" "pc"
        $stockage = "pc"
    } else {
        for ($essai = 1; $essai -le 3 -and -not $modeServeur; $essai++) {
            if (Configurer-Serveur) {
                $modeServeur = $true
            } elseif ($essai -lt 3 -and (Read-Host "Réessayer ? (O/N)") -notmatch '^\s*[oO]') {
                break
            }
        }
        if (-not $modeServeur) {
            if ($serveurAvant) {
                Arreter "Le dossier du serveur n’est pas accessible : l’application, qui y range ses fichiers, ne peut pas démarrer."
            }
            Write-Host "Les fichiers restent sur ce PC pour l’instant : la question reviendra au prochain lancement de installer.ps1." -ForegroundColor Yellow
        }
    }
}

if ($modeServeur) {
    $contenuEnv = Definir-Variable $contenuEnv "STOCKAGE" "serveur"
    # Volumes du serveur pour tous les services, y compris « ged » (fichiers internet et tunnel).
    $contenuEnv = Definir-Variable $contenuEnv "VOLUME_FICHIERS" "serveur_fichiers"
    $contenuEnv = Definir-Variable $contenuEnv "VOLUME_ARCHIVES" "serveur_archives"
    if ($serveurAvant -and $dossierAvant -and (Lire-Variable $contenuEnv "SERVEUR_CHEMIN_AFFICHE") -ne $dossierAvant) {
        Write-Host "Nouveau dossier partagé : les fichiers de l’ancien dossier ne sont pas déplacés automatiquement." -ForegroundColor Yellow
        Write-Host "Copiez ses sous-dossiers fichiers et archives dans le nouveau avant de continuer." -ForegroundColor Yellow
        if ((Read-Host "Continuer ? (O/N)") -notmatch '^\s*[oO]') { Arreter "Rien n’a été modifié." }
    }
    if (-not $serveurAvant) {
        # Passage du PC au serveur : les fichiers déjà enregistrés sur ce PC sont d'abord copiés sur le serveur.
        $sourceFichiers = Join-Path $PSScriptRoot "donnees\fichiers"
        $archivesPc = Lire-Variable $contenuEnv "DOSSIER_ARCHIVES_PC"
        $sourceArchives = Chemin-Pc $archivesPc "donnees\archives"
        if ((Contient-Fichiers $sourceFichiers) -or (Contient-Fichiers $sourceArchives)) {
            Write-Host "Des fichiers sont déjà enregistrés sur ce PC : ils sont copiés sur le serveur avant le démarrage."
            $dossierServeur = Connecter-Partage-Env
            if (-not $dossierServeur) { Arreter "Copie impossible : le dossier du serveur n’est pas accessible. Rien n’a été modifié." }
            Arreter-Application
            if (-not (Copier-Dossier $sourceFichiers (Join-Path $dossierServeur "fichiers")) -or
                -not (Copier-Dossier $sourceArchives (Join-Path $dossierServeur "archives"))) {
                Arreter "La copie des fichiers sur le serveur a échoué : l’application reste configurée sur ce PC. Relancez ce script."
            }
            # Les dossiers du PC, désormais inutilisés, sont renommés : on ne les confond plus avec ceux du serveur.
            $aRenommer = @($sourceFichiers)
            if (-not $archivesPc) { $aRenommer += $sourceArchives }
            foreach ($dossier in $aRenommer) {
                if (-not (Test-Path -LiteralPath $dossier)) { continue }
                $nouveauNom = (Split-Path $dossier -Leaf) + "-copie-avant-serveur-" + (Get-Date -Format "yyyy-MM-dd_HHmm")
                try {
                    Rename-Item -LiteralPath $dossier -NewName $nouveauNom -ErrorAction Stop
                    Write-Host "Ancien dossier du PC conservé sous donnees\$nouveauNom (à supprimer quand tout sera vérifié)."
                } catch {
                    Write-Host "Le dossier $dossier n’a pas pu être renommé ; il n’est plus utilisé par l’application." -ForegroundColor Yellow
                }
            }
            if ($archivesPc) { Write-Host "Le dossier $archivesPc n’est plus utilisé : les archives sont désormais sur le serveur." }
        }
    }
    Write-Host "Fichiers, archives et sauvegardes sur le serveur : $(Lire-Variable $contenuEnv 'SERVEUR_CHEMIN_AFFICHE')" -ForegroundColor Green
} else {
    $contenuEnv = Definir-Variable $contenuEnv "VOLUME_FICHIERS" ""
    $contenuEnv = Definir-Variable $contenuEnv "VOLUME_ARCHIVES" ""
    if ($serveurAvant) {
        # Retour du serveur au PC : les fichiers du serveur sont d'abord recopiés sur ce PC.
        Write-Host "Retour des fichiers sur ce PC : copie depuis le dossier du serveur…"
        $dossierServeur = Connecter-Partage-Env
        if (-not $dossierServeur) { Arreter "Copie impossible : le dossier du serveur n’est pas accessible. Remettez STOCKAGE=serveur dans .env ou réessayez." }
        Arreter-Application
        if (-not (Copier-Dossier (Join-Path $dossierServeur "fichiers") (Join-Path $PSScriptRoot "donnees\fichiers")) -or
            -not (Copier-Dossier (Join-Path $dossierServeur "archives") (Chemin-Pc (Lire-Variable $contenuEnv "DOSSIER_ARCHIVES_PC") "donnees\archives"))) {
            Arreter "La copie depuis le serveur a échoué : remettez STOCKAGE=serveur dans .env, ou réessayez."
        }
        # Le mot de passe du compte du serveur n'est plus utile.
        $contenuEnv = Definir-Variable $contenuEnv "SERVEUR_MOT_DE_PASSE" ""
        Write-Host "Fichiers recopiés sur ce PC. Les sauvegardes déjà faites restent sur le serveur."
    }
    if ($stockage -eq "pc") {
        $sauvegardesPc = Lire-Variable $contenuEnv "DOSSIER_SAUVEGARDES_PC"
        Write-Host "Fichiers sur ce PC (dossier donnees\fichiers). Sauvegardes de chaque nuit : $(if ($sauvegardesPc) { $sauvegardesPc } else { 'donnees\sauvegardes' })."
        $disque = [System.IO.Path]::GetPathRoot((Chemin-Pc $sauvegardesPc "donnees\sauvegardes")).ToUpper()
        if ($disque -eq [System.IO.Path]::GetPathRoot($PSScriptRoot).ToUpper() -or $disque -eq "C:\") {
            Write-Host "Attention : les sauvegardes sont sur le même disque que l’application ; une panne du PC emporterait tout." -ForegroundColor Yellow
            Write-Host "Pour les mettre sur le serveur de l’agence : videz la ligne STOCKAGE= du fichier .env, puis relancez ce script." -ForegroundColor Yellow
            Write-Host "Ou sur un disque externe toujours branché : ligne DOSSIER_SAUVEGARDES_PC= (par exemple E:\Sauvegardes DAplomb)." -ForegroundColor Yellow
        }
        Write-Host "(Pour passer au serveur de l’agence plus tard : videz la ligne STOCKAGE= du fichier .env, puis relancez ce script.)"
    }
}
Deconnecter-Partage

$fichiers = Fichiers-Compose $gpu $modeGed $modeServeur
$contenuEnv = Ligne-Compose $contenuEnv $fichiers
$env:COMPOSE_FILE = $fichiers
Enregistrer-Env $contenuEnv

if ($modeServeur) {
    # Les réglages d'un volume du serveur (adresse, compte, mot de passe) sont fixés à sa création : s'ils ne
    # correspondent plus à .env, le volume est recréé. Les fichiers du serveur ne sont pas touchés.
    $configuration = docker compose config --format json 2>$null
    if ($LASTEXITCODE -eq 0) {
        try { $modele = (Texte-Sortie $configuration) | ConvertFrom-Json } catch { $modele = $null }
        foreach ($nom in @("serveur_fichiers", "serveur_archives", "serveur_sauvegardes")) {
            if (-not $modele -or -not $modele.volumes.$nom) { continue }
            $attendu = $modele.volumes.$nom.driver_opts
            $volume = "application-ao_$nom"
            $actuel = docker volume inspect $volume --format "{{json .Options}}" 2>$null
            if ($LASTEXITCODE -ne 0 -or -not (Texte-Sortie $actuel)) { continue }
            $options = (Texte-Sortie $actuel) | ConvertFrom-Json
            if ($options.o -ne "$($attendu.o)".Replace('$$', '$') -or $options.device -ne "$($attendu.device)".Replace('$$', '$')) {
                Write-Host "Réglages du serveur modifiés : le volume $nom est recréé (les fichiers du serveur ne sont pas touchés)."
                $conteneurs = @(docker ps -aq --filter "volume=$volume")
                if ($conteneurs.Count -gt 0) { docker rm -f $conteneurs | Out-Null }
                docker volume rm $volume 2>&1 | Out-Null
            }
        }
    }
}

Ecrire-Etape "Construction et démarrage (le premier lancement peut prendre 5 à 10 minutes)"
docker compose up -d --build --remove-orphans
if ($LASTEXITCODE -ne 0 -and $gpu) {
    # La carte graphique n'est plus accessible (pilote, réglage de Docker) : on repart sans elle.
    Write-Host "Démarrage impossible avec la carte graphique : nouvel essai sans elle." -ForegroundColor Yellow
    $gpu = $false
    $fichiers = Fichiers-Compose $gpu $modeGed $modeServeur
    $contenuEnv = Ligne-Compose $contenuEnv $fichiers
    Enregistrer-Env $contenuEnv
    $env:COMPOSE_FILE = $fichiers
    docker compose up -d --build --remove-orphans
}
if ($LASTEXITCODE -ne 0) {
    if ($modeServeur) {
        Write-Host "Si le message parle du montage d’un volume (« mounting volume »), Docker n’accède pas au dossier du serveur :" -ForegroundColor Yellow
        Write-Host "vérifiez que le serveur est allumé et que le compte dédié fonctionne, puis relancez ce script." -ForegroundColor Yellow
    }
    Arreter "Le démarrage a échoué. Consultez les messages ci-dessus, ou lancez : docker compose logs"
}

Ecrire-Etape "Préparation de la base de données"
$pret = $false
for ($essai = 0; $essai -lt 90; $essai++) {
    docker compose exec -T backend python manage.py migrate --check 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $pret = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $pret) {
    Arreter "La base de données ne répond pas. Consultez : docker compose logs backend"
}
Write-Host "Base de données prête."

$administrateurExiste = docker compose exec -T backend python manage.py shell -c "from comptes.models import Utilisateur; print(Utilisateur.objects.filter(is_superuser=True).exists())" 2>$null
if ("$administrateurExiste".Trim() -ne "True") {
    Ecrire-Etape "Création de votre compte administrateur"
    Write-Host "Choisissez un identifiant puis un mot de passe d'au moins 12 caractères."
    Write-Host "(L'adresse e-mail est facultative : appuyez sur Entrée pour la passer.)"
    docker compose exec backend python manage.py createsuperuser
}

Ecrire-Etape "Assistant IA : téléchargement des modèles gratuits (une seule fois, environ 8 Go)"
docker compose exec -T backend python manage.py preparer_assistant
if ($LASTEXITCODE -ne 0) {
    Write-Host "Les modèles de l'assistant n'ont pas pu être téléchargés (connexion Internet ?)." -ForegroundColor Yellow
    Write-Host "Le reste de l'application fonctionne. Relancez installer.ps1 plus tard pour terminer." -ForegroundColor Yellow
}

$port = "8080"
$ligne = Select-String -LiteralPath $cheminEnv -Pattern '^APP_PORT=(\d+)' | Select-Object -First 1
if ($ligne) { $port = $ligne.Matches[0].Groups[1].Value }

if ($modeGed) {
    $urlGed = Lire-Variable $contenuEnv "GED_URL_PUBLIQUE"
    Ecrire-Etape "GED sur Internet : $urlGed/ged"
    if ($modeGed -eq "ip") {
        Write-Host "Obtention du certificat HTTPS gratuit (jusqu'à 2 minutes)…"
        $hote = $urlGed -replace '^https://', ''
        $certificat = $false
        for ($essai = 0; $essai -lt 24 -and -not $certificat; $essai++) {
            $trouve = docker compose exec -T web find /data/caddy/certificates -name "$hote.crt" 2>$null
            if ("$trouve".Trim()) { $certificat = $true } else { Start-Sleep -Seconds 5 }
        }
        if ($certificat) {
            Write-Host "Certificat HTTPS obtenu." -ForegroundColor Green
        } else {
            Write-Host "Certificat pas encore obtenu : vérifiez la redirection du port 443 de la box et l'enregistrement DNS." -ForegroundColor Yellow
            Write-Host "Il sera obtenu automatiquement dès que la GED sera joignable (détail : docker compose logs web)." -ForegroundColor Yellow
        }
    }
    Write-Host "Test conseillé : sur un téléphone en 4G (Wi-Fi coupé), ouvrez $urlGed/ged" -ForegroundColor Cyan
    Write-Host "La page « Accès des intervenants » doit s'afficher, avec le cadenas HTTPS." -ForegroundColor Cyan
}

$heureSauvegarde = Lire-Variable $contenuEnv "SAUVEGARDE_HEURE"
if (-not $heureSauvegarde) { $heureSauvegarde = "2:30" }
if ($modeServeur) {
    $destination = (Lire-Variable $contenuEnv "SERVEUR_CHEMIN_AFFICHE").TrimEnd('\') + "\sauvegardes"
} else {
    $destination = Lire-Variable $contenuEnv "DOSSIER_SAUVEGARDES_PC"
    if (-not $destination) { $destination = "donnees\sauvegardes" }
}
Ecrire-Etape "Sauvegarde de contrôle : base de données vérifiée, configuration$(if (-not $modeServeur) { ' et fichiers' })"
Write-Host "Destination : $destination (la première peut prendre plusieurs minutes)."
$sortie = docker compose exec -T worker python manage.py sauvegarder 2>&1
$code = $LASTEXITCODE
$texte = Texte-Sortie $sortie
if ($texte) { Write-Host $texte }
if ($code -eq 0) {
    Write-Host "Sauvegarde réussie dans $destination." -ForegroundColor Green
} elseif ($texte -match 'en cours') {
    # Sauvegarde de la nuit manquée, rattrapée au démarrage de l'application.
    Write-Host "Une sauvegarde est déjà en cours (celle de la nuit, rattrapée au démarrage) : son résultat s’affichera dans l’application." -ForegroundColor Yellow
} else {
    Write-Host "La sauvegarde n’a pas abouti (détail ci-dessus). L’application fonctionne, mais vos données ne sont pas" -ForegroundColor Yellow
    Write-Host "encore protégées : corrigez la cause, puis relancez ce script (ou : docker compose exec worker python manage.py sauvegarder)." -ForegroundColor Yellow
}
Write-Host "Ensuite, une sauvegarde est faite chaque nuit à $heureSauvegarde : laissez le PC allumé et la session Windows ouverte"
Write-Host "(si le PC était éteint, elle est faite à son démarrage). Restauration : restaurer.ps1."

Write-Host ""
Write-Host "D’Aplomb est prêt : http://localhost:$port" -ForegroundColor Green
Start-Process "http://localhost:$port"
Read-Host "Appuyez sur Entrée pour fermer"
