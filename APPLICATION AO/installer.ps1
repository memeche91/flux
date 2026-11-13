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

# Fenêtre gardée ouverte en fin de script ; lancé par double-clic sur le fichier .cmd, c'est lui qui la garde ouverte.
function Pause-Fin {
    if (-not $env:DAPLOMB_LANCEUR) { Read-Host "Appuyez sur Entrée pour fermer" | Out-Null }
}

function Arreter([string]$message) {
    # Connexion au partage du serveur ouverte par ce script : fermée avant de quitter.
    if ($script:connexionPartage) { net use $script:connexionPartage /delete /y 2>&1 | Out-Null }
    Write-Host ""
    Write-Host $message -ForegroundColor Red
    Pause-Fin
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
    # Ligne présente plusieurs fois : Docker Compose garde la dernière, ce script aussi.
    $trouves = [regex]::Matches($contenu, "(?m)^$nom=([^\r\n]*)")
    if ($trouves.Count -gt 0) {
        $valeur = $trouves[$trouves.Count - 1].Groups[1].Value.Trim()
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
    return $options + "vers=3.0,uid=0,gid=0,file_mode=0660,dir_mode=0770,nounix,noserverino,iocharset=utf8"
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

# Montage du sous-dossier « sauvegardes » par Docker, exactement comme le feront les services. Avec le
# chemin Windows du dossier (connexion ouverte) : vérifie aussi qu'un nom accentué écrit par Docker
# arrive intact sur le serveur (Plan_façade.pdf doit rester Plan_façade.pdf).
function Tester-Partage-Docker([string]$adresse, [string]$partage, [string]$options, [string]$dossierWindows = "") {
    $volume = "application-ao-essai-serveur"
    docker pull valkey/valkey:8-alpine 2>&1 | Out-Null
    docker volume rm -f $volume 2>&1 | Out-Null
    $sortie = docker volume create --driver local --opt type=cifs --opt "device=//$adresse/$partage/sauvegardes" --opt "o=$options" $volume 2>&1
    if ($LASTEXITCODE -ne 0) { return "Docker ne peut pas préparer l’accès au serveur : $(Texte-Sortie $sortie)" }
    $sortie = docker run --rm -v "${volume}:/essai" --entrypoint sh valkey/valkey:8-alpine -c "echo essai > /essai/essai-docker.tmp && rm -f /essai/essai-docker.tmp" 2>&1
    $code = $LASTEXITCODE
    $nomIntact = $true
    if ($code -eq 0 -and $dossierWindows) {
        docker run --rm -v "${volume}:/essai" --entrypoint sh valkey/valkey:8-alpine -c "echo essai > /essai/essai-é.tmp" 2>&1 | Out-Null
        # Quelques secondes de patience : Windows garde un moment en mémoire le contenu des dossiers partagés.
        $nomIntact = $false
        for ($attente = 0; $attente -lt 6 -and -not $nomIntact; $attente++) {
            if ($attente -gt 0) { Start-Sleep -Seconds 2 }
            $nomIntact = Test-Path -LiteralPath (Join-Path $dossierWindows "sauvegardes\essai-é.tmp")
        }
        docker run --rm -v "${volume}:/essai" --entrypoint sh valkey/valkey:8-alpine -c "rm -f /essai/essai-é.tmp" 2>&1 | Out-Null
    }
    docker volume rm -f $volume 2>&1 | Out-Null
    if ($code -eq 0 -and -not $nomIntact) {
        return "Docker écrit dans le dossier partagé, mais les noms de fichiers accentués y arrivent déformés (essai-é.tmp) :`nles documents aux noms accentués seraient introuvables. Mettez à jour Docker Desktop, puis réessayez."
    }
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
    if ($chemin.Contains("'")) {
        # Valeur-Env l'écrirait entre apostrophes : .env deviendrait illisible pour Docker Compose.
        Write-Host "Ce chemin contient une apostrophe ('), que Docker ne sait pas lire dans .env : partagez le dossier de D’Aplomb" -ForegroundColor Yellow
        Write-Host "sous un nom sans apostrophe (par exemple \\SERVEUR\DAplomb), puis recommencez." -ForegroundColor Yellow
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
    if ($motDePasse -match "[,'`"]" -or $motDePasse.EndsWith('\')) {
        Write-Host "Ce mot de passe contient une virgule, un guillemet ou une apostrophe, ou se termine par \, ce que D’Aplomb ne sait pas enregistrer pour Docker :" -ForegroundColor Yellow
        Write-Host "donnez au compte dédié un mot de passe sans virgule, guillemet ni apostrophe, qui ne se termine pas par \, puis recommencez." -ForegroundColor Yellow
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
        $erreur = Tester-Partage-Docker $adresse $partage (Options-Partage $adresse $utilisateur $motDePasse $domaine) $dossierWindows
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
    Write-Host "Sur le serveur, réservez les sous-dossiers sauvegardes et fichiers au compte dédié et aux administrateurs :" -ForegroundColor Cyan
    Write-Host "sauvegardes contient une copie de .env (clés de l’application) et des copies complètes de la base." -ForegroundColor Cyan
    Write-Host "Pour d’autres personnes, la lecture du seul sous-dossier archives suffit." -ForegroundColor Cyan
    return $true
}

# Dossier du PC indiqué dans .env : chemin complet, ou relatif au dossier de l'application.
function Chemin-Pc([string]$valeur, [string]$defaut) {
    if (-not $valeur) { $valeur = $defaut }
    $valeur = $valeur.Replace('/', '\')
    if ([System.IO.Path]::IsPathRooted($valeur)) { return $valeur }
    return (Join-Path $PSScriptRoot ($valeur -replace '^\.\\', ''))
}

# Dossier du PC indiqué dans .env (DOSSIER_SAUVEGARDES_PC, DOSSIER_ARCHIVES_PC) : jamais transformé par les scripts,
# seulement vérifié (restaurer.ps1 n'y écrit que le dossier des sauvegardes choisi, après cette même vérification). Docker ne lit comme dossier qu'un chemin complet (E:\Sauvegardes DAplomb) ou commençant par .\ ;
# une apostrophe, un guillemet, un # (commentaire) ou un \ final seraient mal lus par Docker. Message vide si correct.
function Probleme-Dossier([string]$valeur) {
    if (-not $valeur) { return "" }
    if ($valeur -match '^(\\\\|//)') { return "ne peut pas être un dossier réseau (\\NAS\…) : Docker ne sait pas l’ouvrir ; choisissez un disque du PC (E:\…), ou le stockage sur le serveur de l’agence (videz la ligne STOCKAGE=)" }
    if ($valeur -match "['`"#`$]") { return "ne doit contenir ni apostrophe, ni guillemet, ni #, ni `$ (pas de commentaire sur la ligne)" }
    if ($valeur -notmatch '^([A-Za-z]:\\[^\\/]|\.\\[^\\/])') { return "doit être un dossier complet, par exemple E:\Dossier (pas la racine d’un disque), ou commencer par .\" }
    if ($valeur -match '[\\/]$') { return "ne doit pas se terminer par \" }
    return ""
}

# Dossier réseau (\\NAS\…) ou lecteur réseau (S:\…, vu par la session Windows mais pas par Docker Desktop), même
# déconnecté ou invisible depuis une fenêtre d'administrateur (lecteur mémorisé dans HKCU:\Network).
function Est-Reseau([string]$chemin) {
    if ($chemin.StartsWith('\\') -or $chemin.StartsWith('//')) { return $true }
    try {
        $racine = [System.IO.Path]::GetPathRoot($chemin)
        if ($racine -match '^[A-Za-z]:') {
            $lettre = $racine.Substring(0, 1)
            $type = (New-Object System.IO.DriveInfo ($lettre)).DriveType
            if ($type -eq [System.IO.DriveType]::Network) { return $true }
            if ($type -eq [System.IO.DriveType]::NoRootDirectory -and (Test-Path -LiteralPath "HKCU:\Network\$lettre")) { return $true }
        }
    } catch { }
    return $false
}

function Contient-Fichiers([string]$dossier) {
    if (-not (Test-Path -LiteralPath $dossier)) { return $false }
    return [bool](Get-ChildItem -LiteralPath $dossier -Recurse -File -Force -ErrorAction SilentlyContinue | Select-Object -First 1)
}

# Arrêt de tous les services de l'application (aucun fichier ne doit changer pendant une copie).
$script:conteneursArretes = @()
function Arreter-Application {
    $script:conteneursArretes = @(docker ps -q --filter "label=com.docker.compose.project=application-ao")
    if ($script:conteneursArretes.Count -gt 0) {
        Write-Host "Arrêt de l’application pendant la copie des fichiers…"
        docker stop $script:conteneursArretes | Out-Null
    }
}

# Après une copie ratée : l'application repart telle qu'elle était (mêmes conteneurs ; .env n'a pas encore été modifié).
# Renvoie « relancee », « echec » (par exemple, serveur de l'agence injoignable pour des conteneurs qui l'utilisent) ou
# « arretee » (elle ne tournait pas avant la copie : rien à relancer).
function Relancer-Application {
    if ($script:conteneursArretes.Count -eq 0) { return "arretee" }
    Write-Host "Redémarrage de l’application, comme avant…"
    docker start $script:conteneursArretes 2>&1 | Out-Null
    $etat = if ($LASTEXITCODE -eq 0) { "relancee" } else { "echec" }
    $script:conteneursArretes = @()
    return $etat
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

# Nombre de copies de la base (*.dump) d'un dossier ; 0 s'il est absent (Get-ChildItem -File échouerait sur un
# lecteur absent, par exemple un disque externe débranché).
function Nombre-Copies-Base([string]$dossier) {
    if (-not $dossier -or -not (Test-Path -LiteralPath $dossier)) { return 0 }
    return @(Get-ChildItem -LiteralPath $dossier -Filter "*.dump" -File -ErrorAction SilentlyContinue).Count
}

# Avant de passer du PC au serveur : les dossiers du PC réglés dans .env (DOSSIER_ARCHIVES_PC, DOSSIER_SAUVEGARDES_PC)
# doivent être accessibles, sinon leur contenu ne serait pas recopié sur le serveur. Vérifié une seule fois, avant les
# questions sur le serveur (rien n'est à ressaisir après avoir rebranché un disque).
$script:dossiersPcVerifies = $false
function Verifier-Dossiers-Pc {
    if ($script:dossiersPcVerifies) { return }
    $script:dossiersPcVerifies = $true
    # Première installation (aucune base) : rien n'a encore été enregistré sur ce PC, rien à recopier.
    docker volume inspect application-ao_base_donnees 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { return }
    foreach ($nom in @("DOSSIER_ARCHIVES_PC", "DOSSIER_SAUVEGARDES_PC")) {
        $valeur = Lire-Variable $script:contenuEnv $nom
        if (-not $valeur -or (Test-Path -LiteralPath (Chemin-Pc $valeur ""))) { continue }
        $cause = if ($valeur -match '^[A-Za-z]:') { "disque débranché, ou lettre du disque changée ?" } else { "dossier déplacé ou renommé ?" }
        $remede = "Rebranchez le disque ou remettez le dossier en place, ou corrigez la ligne $nom de .env avec le Bloc-notes, puis relancez ce script."
        if ($nom -eq "DOSSIER_ARCHIVES_PC") {
            Arreter ("Le dossier des archives $valeur (ligne $nom de .env) est introuvable ($cause) :`n" +
                "ses archives ne seraient pas recopiées sur le serveur. $remede`n" +
                "S’il n’y a encore aucune archive, videz plutôt cette ligne. Rien n’a été modifié.")
        }
        Write-Host "Le dossier des sauvegardes $valeur (ligne $nom de .env) est introuvable ($cause) :" -ForegroundColor Yellow
        Write-Host "les sauvegardes qu’il contient ne seront pas recopiées sur le serveur, et restaurer.ps1 ne les proposera plus." -ForegroundColor Yellow
        if ((Read-Host "Continuer sans elles ? (O/N, N par défaut)") -notmatch '^\s*[oO]') {
            Arreter "$remede Rien n’a été modifié."
        }
    }
}

# Copies de la base faites chaque nuit sur ce PC (fichiers .dump du sous-dossier base) : recopiées telles quelles,
# sans le miroir des fichiers ni configuration\.env, que la première sauvegarde sur le serveur écrit elle-même.
function Copier-Copies-Base([string]$source, [string]$destination) {
    if ((Nombre-Copies-Base $source) -eq 0) { return $true }
    Write-Host "Copie des sauvegardes de la base de « $source » vers « $destination »…"
    robocopy $source $destination "*.dump" /XO /R:2 /W:5 /NP /NFL /NDL /NJH | Out-Host
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
            "  - Fichier .env perdu : recopiez le fichier configuration\.env du dossier des sauvegardes (par exemple`n" +
            "    \\SERVEUR\DAplomb\sauvegardes\configuration\.env) dans ce dossier, puis relancez ce script.`n" +
            "    restaurer.ps1 sert seulement à revenir à une sauvegarde de la base.")
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
# Dossiers du PC écrits à la main dans .env : vérifiés (jamais réécrits) pour que Docker et ce script lisent le même dossier.
foreach ($nomDossier in @("DOSSIER_SAUVEGARDES_PC", "DOSSIER_ARCHIVES_PC")) {
    $cheminLu = Lire-Variable $contenuEnv $nomDossier
    $probleme = Probleme-Dossier $cheminLu
    if ($probleme) {
        Arreter ("Ligne $nomDossier de .env (« $cheminLu ») : le dossier $probleme.`n" +
            "Corrigez cette ligne avec le Bloc-notes (exemple : $nomDossier=$(@{ DOSSIER_SAUVEGARDES_PC = 'E:\Sauvegardes DAplomb'; DOSSIER_ARCHIVES_PC = 'D:\Archives chantiers' }[$nomDossier]), ou videz-la), puis relancez ce script.")
    }
}
# Archives et sauvegardes : deux dossiers distincts, aucun dans l'autre (sinon chaque sauvegarde recopierait les
# précédentes dans les archives, avec les clés de .env, et le disque se remplirait).
$dossierArchivesPc = [System.IO.Path]::GetFullPath((Chemin-Pc (Lire-Variable $contenuEnv "DOSSIER_ARCHIVES_PC") "donnees\archives")).TrimEnd('\') + '\'
$dossierSauvegardesPc = [System.IO.Path]::GetFullPath((Chemin-Pc (Lire-Variable $contenuEnv "DOSSIER_SAUVEGARDES_PC") "donnees\sauvegardes")).TrimEnd('\') + '\'
if ($dossierArchivesPc.StartsWith($dossierSauvegardesPc, [System.StringComparison]::OrdinalIgnoreCase) -or
    $dossierSauvegardesPc.StartsWith($dossierArchivesPc, [System.StringComparison]::OrdinalIgnoreCase)) {
    Arreter ("DOSSIER_ARCHIVES_PC et DOSSIER_SAUVEGARDES_PC doivent être deux dossiers distincts, aucun dans l’autre`n" +
        "(par exemple D:\Archives chantiers et E:\Sauvegardes DAplomb) : corrigez .env avec le Bloc-notes, puis relancez ce script.")
}
$stockage = (Lire-Variable $contenuEnv "STOCKAGE").ToLower()
# Emplacement réellement utilisé jusqu'ici (volumes du serveur montés ou non) et dossier du serveur.
$serveurAvant = (Lire-Variable $contenuEnv "COMPOSE_FILE") -match 'serveur'
$dossierAvant = Lire-Variable $contenuEnv "SERVEUR_CHEMIN_AFFICHE"
$modeServeur = $false
if ($stockage -eq "serveur") {
    if (-not $serveurAvant) { Verifier-Dossiers-Pc }
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
        } elseif (-not $serveurAvant) {
            Arreter ("Le dossier du serveur n’est pas accessible. Rien n’a été modifié : les fichiers de l’application sont encore sur ce PC.`n" +
                "Vérifiez le serveur et le compte, puis relancez ce script ; ou, pour rester sur ce PC, mettez STOCKAGE=pc dans .env`n" +
                "avec le Bloc-notes, puis relancez-le.")
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
        if (-not $serveurAvant) { Verifier-Dossiers-Pc }
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
        # Passage du PC au serveur : les fichiers déjà enregistrés sur ce PC, les archives et les copies de la base
        # faites chaque nuit sont d'abord copiés sur le serveur (restaurer.ps1 ne lit ensuite plus que le serveur).
        Verifier-Dossiers-Pc
        $sourceFichiers = Join-Path $PSScriptRoot "donnees\fichiers"
        $archivesPc = Lire-Variable $contenuEnv "DOSSIER_ARCHIVES_PC"
        $sauvegardesPcAvant = Lire-Variable $contenuEnv "DOSSIER_SAUVEGARDES_PC"
        # Dossiers par défaut ET dossiers réglés dans .env : Docker peut encore utiliser l'un alors que .env désigne
        # l'autre (ligne modifiée sans redémarrage). robocopy /XO les réunit sans rien écraser. Combine, et non
        # Join-Path, qui échoue sur un lecteur absent.
        $sourcesArchives = @(@((Join-Path $PSScriptRoot "donnees\archives"), (Chemin-Pc $archivesPc "donnees\archives")) | Sort-Object -Unique)
        $sourcesBase = @(@((Join-Path $PSScriptRoot "donnees\sauvegardes\base"),
            [System.IO.Path]::Combine((Chemin-Pc $sauvegardesPcAvant "donnees\sauvegardes"), "base")) | Sort-Object -Unique)
        $avecFichiers = Contient-Fichiers $sourceFichiers
        $avecArchives = @($sourcesArchives | Where-Object { Contient-Fichiers $_ }).Count -gt 0
        $copiesBase = 0
        foreach ($source in $sourcesBase) { $copiesBase += Nombre-Copies-Base $source }
        if ($avecFichiers -or $avecArchives -or $copiesBase -gt 0) {
            $quoi = @()
            if ($avecFichiers) { $quoi += "les fichiers" }
            if ($avecArchives) { $quoi += "les archives" }
            if ($copiesBase -gt 0) { $quoi += "les sauvegardes de la base" }
            $liste = if ($quoi.Count -gt 1) { ($quoi[0..($quoi.Count - 2)] -join ", ") + " et " + $quoi[-1] } else { $quoi[0] }
            Write-Host "Copie sur le serveur, avant le démarrage, de ce qui est déjà enregistré sur ce PC : $liste."
            $dossierServeur = Connecter-Partage-Env
            if (-not $dossierServeur) { Arreter "Copie impossible : le dossier du serveur n’est pas accessible. Rien n’a été modifié." }
            Arreter-Application
            $copieReussie = Copier-Dossier $sourceFichiers (Join-Path $dossierServeur "fichiers")
            foreach ($source in $sourcesArchives) {
                if ($copieReussie) { $copieReussie = Copier-Dossier $source (Join-Path $dossierServeur "archives") }
            }
            foreach ($source in $sourcesBase) {
                if ($copieReussie) { $copieReussie = Copier-Copies-Base $source (Join-Path $dossierServeur "sauvegardes\base") }
            }
            if (-not $copieReussie) {
                if ((Relancer-Application) -eq "relancee") {
                    Arreter ("La copie sur le serveur a échoué : l’application continue sur ce PC, comme avant (rien n’a été modifié).`n" +
                        "Vérifiez que le serveur est allumé et qu’il lui reste de la place, puis relancez ce script pour réessayer.")
                }
                Arreter ("La copie sur le serveur a échoué (rien n’a été modifié), et l’application est arrêtée.`n" +
                    "Vérifiez que le serveur est allumé et qu’il lui reste de la place, puis relancez ce script pour réessayer.`n" +
                    "Pour rester sur ce PC : mettez STOCKAGE=pc dans .env avec le Bloc-notes, puis relancez ce script.")
            }
            if ($copiesBase -eq 1) {
                Write-Host "La sauvegarde de la base faite sur ce PC a été recopiée sur le serveur : restaurer.ps1 la propose."
            } elseif ($copiesBase -gt 1) {
                Write-Host "Les $copiesBase sauvegardes de la base faites sur ce PC ont été recopiées sur le serveur : restaurer.ps1 les propose."
            }
            # Les dossiers du PC, désormais inutilisés, sont renommés : on ne les confond plus avec ceux du serveur.
            foreach ($nomDossier in @("fichiers", "archives", "sauvegardes")) {
                $dossier = Join-Path $PSScriptRoot "donnees\$nomDossier"
                if (-not (Test-Path -LiteralPath $dossier)) { continue }
                $nouveauNom = "$nomDossier-copie-avant-serveur-" + (Get-Date -Format "yyyy-MM-dd_HHmm")
                try {
                    Rename-Item -LiteralPath $dossier -NewName $nouveauNom -ErrorAction Stop
                    Write-Host "Ancien dossier du PC conservé sous donnees\$nouveauNom (à supprimer quand tout sera vérifié)."
                } catch {
                    Write-Host "Le dossier $dossier n’a pas pu être renommé ; il n’est plus utilisé par l’application." -ForegroundColor Yellow
                }
            }
            # Dossiers réglés sur un autre disque : laissés en place, plus utilisés.
            if ($archivesPc -and (Contient-Fichiers (Chemin-Pc $archivesPc ""))) {
                Write-Host "Le dossier $archivesPc n’est plus utilisé : ses archives ont été recopiées sur le serveur (à supprimer quand tout sera vérifié)."
            }
            if ($sauvegardesPcAvant -and (Nombre-Copies-Base ([System.IO.Path]::Combine((Chemin-Pc $sauvegardesPcAvant ""), "base"))) -gt 0) {
                Write-Host "Le dossier $sauvegardesPcAvant n’est plus utilisé : ses sauvegardes de la base ont été recopiées sur le serveur (à supprimer quand tout sera vérifié)."
            }
        }
    }
    Write-Host "Fichiers, archives et sauvegardes sur le serveur : $(Lire-Variable $contenuEnv 'SERVEUR_CHEMIN_AFFICHE')" -ForegroundColor Green
} else {
    $contenuEnv = Definir-Variable $contenuEnv "VOLUME_FICHIERS" ""
    $contenuEnv = Definir-Variable $contenuEnv "VOLUME_ARCHIVES" ""
    $sauvegardesPc = Lire-Variable $contenuEnv "DOSSIER_SAUVEGARDES_PC"
    # Docker Desktop ne sait pas monter un dossier réseau (\\NAS\Sauvegardes) ni un lecteur réseau (S:\…).
    if ($sauvegardesPc -and (Est-Reseau (Chemin-Pc $sauvegardesPc "donnees\sauvegardes"))) {
        Arreter ("DOSSIER_SAUVEGARDES_PC ($sauvegardesPc) ne peut pas être un dossier réseau (\\NAS\…) ni un lecteur réseau (S:\…) :`n" +
            "Docker ne sait pas l’ouvrir. Choisissez le stockage sur le serveur (videz la ligne STOCKAGE= du fichier .env),`n" +
            "ou un disque local ou externe (E:\…), puis relancez ce script.")
    }
    $archivesPc = Lire-Variable $contenuEnv "DOSSIER_ARCHIVES_PC"
    if ($archivesPc -and (Est-Reseau (Chemin-Pc $archivesPc "donnees\archives"))) {
        Arreter ("DOSSIER_ARCHIVES_PC ($archivesPc) ne peut pas être un dossier réseau (\\NAS\…) ni un lecteur réseau (S:\…) :`n" +
            "Docker ne sait pas l’ouvrir. Choisissez le stockage sur le serveur (videz la ligne STOCKAGE= du fichier .env),`n" +
            "ou un disque local ou externe (D:\…), puis relancez ce script.")
    }
    if ($serveurAvant) {
        # Retour du serveur au PC : les fichiers du serveur sont d'abord recopiés sur ce PC.
        Write-Host "Retour des fichiers sur ce PC : copie depuis le dossier du serveur…"
        $dossierServeur = Connecter-Partage-Env
        if (-not $dossierServeur) { Arreter "Copie impossible : le dossier du serveur n’est pas accessible. Remettez STOCKAGE=serveur dans .env ou réessayez." }
        Arreter-Application
        if (-not (Copier-Dossier (Join-Path $dossierServeur "fichiers") (Join-Path $PSScriptRoot "donnees\fichiers")) -or
            -not (Copier-Dossier (Join-Path $dossierServeur "archives") (Chemin-Pc (Lire-Variable $contenuEnv "DOSSIER_ARCHIVES_PC") "donnees\archives"))) {
            if ((Relancer-Application) -eq "relancee") {
                Arreter ("La copie depuis le serveur a échoué : l’application continue comme avant, avec les fichiers du serveur.`n" +
                    "Relancez ce script pour réessayer, ou remettez STOCKAGE=serveur dans .env pour rester sur le serveur.")
            }
            Arreter ("La copie depuis le serveur a échoué, et l’application est arrêtée (le serveur ne répond pas ?).`n" +
                "Une fois le serveur revenu, relancez ce script pour réessayer, ou remettez STOCKAGE=serveur dans .env puis relancez-le.")
        }
        # Le mot de passe du compte du serveur n'est plus utile.
        $contenuEnv = Definir-Variable $contenuEnv "SERVEUR_MOT_DE_PASSE" ""
        Write-Host "Fichiers recopiés sur ce PC. Les sauvegardes déjà faites restent sur le serveur."
    }
    if ($stockage -eq "pc") {
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
            # -cne : un mot de passe qui ne change que par des majuscules ou minuscules doit aussi recréer le volume.
            if ($options.o -cne "$($attendu.o)".Replace('$$', '$') -or $options.device -cne "$($attendu.device)".Replace('$$', '$')) {
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

# Fichiers sur le serveur : si le serveur ne répond pas encore quand Docker Desktop démarre (ouverture de
# session, Wi-Fi lent, serveur qui redémarre), les services ne démarrent pas et Docker ne réessaie pas.
# Une tâche planifiée relance « docker compose up -d » à chaque ouverture de session, jusqu'à ce que le
# serveur réponde (un essai par minute pendant 20 minutes). Sans droits d'administrateur.
# Elle ne vérifie pas les réglages des volumes du serveur (comparaison plus haut) : toute modification des
# lignes SERVEUR_ de .env passe par ce script (README, .env.example), sinon Docker Compose demanderait, dans
# sa fenêtre cachée, s'il faut recréer ces volumes.
$tacheDemarrage = "D’Aplomb - démarrage"
if ($modeServeur) {
    try {
        $commande = 'for($i=0;$i -lt 60;$i++){docker info *>$null; if($LASTEXITCODE -eq 0){break}; Start-Sleep 10}; if(-not (docker compose ps -a -q)){exit}; for($i=0;$i -lt 20;$i++){docker compose up -d; if($LASTEXITCODE -eq 0){break}; Start-Sleep 60}'
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $PSScriptRoot -Argument "-NoProfile -WindowStyle Hidden -Command `"$commande`""
        $declencheur = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
        $declencheur.Delay = "PT2M"
        $reglages = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName $tacheDemarrage -Action $action -Trigger $declencheur -Settings $reglages -Force -ErrorAction Stop | Out-Null
        Write-Host "Tâche « $tacheDemarrage » : à chaque ouverture de session, l’application est relancée dès que le serveur répond."
    } catch {
        Write-Host "La tâche de démarrage n’a pas pu être créée ($($_.Exception.Message))." -ForegroundColor Yellow
        Write-Host "Si le serveur était éteint au démarrage du PC, relancez installer.ps1 (ou docker compose up -d) une fois le serveur revenu." -ForegroundColor Yellow
    }
} else {
    if (Get-ScheduledTask -TaskName $tacheDemarrage -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $tacheDemarrage -Confirm:$false -ErrorAction SilentlyContinue
    }
    # Fichiers sur ce PC : les volumes du serveur d'un stockage précédent sont supprimés, car leurs réglages
    # contiennent le mot de passe du compte dédié (les fichiers du serveur ne sont pas touchés).
    docker volume rm application-ao_serveur_fichiers application-ao_serveur_archives application-ao_serveur_sauvegardes 2>&1 | Out-Null
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

$administrateurExiste = docker compose exec -T backend python manage.py shell --no-imports -c "from comptes.models import Utilisateur; print(Utilisateur.objects.filter(is_superuser=True).exists())" 2>$null
if ((Texte-Sortie $administrateurExiste) -notmatch '(?m)^True$') {
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

# Port publié par Docker : dernière ligne APP_PORT de .env, comme Docker Compose.
$port = Lire-Variable $contenuEnv "APP_PORT"
if ($port -notmatch '^\d+$') { $port = "8080" }

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
# Python écrit en UTF-8 : décodage UTF-8 pour cette seule commande (robocopy, plus haut, écrit dans la
# page de codes de la console).
$encodage = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$sortie = docker compose exec -T worker python manage.py sauvegarder 2>&1
$code = $LASTEXITCODE
[Console]::OutputEncoding = $encodage
$texte = Texte-Sortie $sortie
if ($texte) { Write-Host $texte }
if ($code -eq 0) {
    # La commande réussit aussi quand la restauration d'essai de la copie a échoué : vérification de l'état.
    $verifiee = docker compose exec -T worker python manage.py shell --no-imports -c "from sauvegardes.models import Sauvegarde as S; s = S.objects.order_by('-debut').first(); print('OUI' if s and s.verifiee else 'NON')" 2>$null
    if ((Texte-Sortie $verifiee) -match '(?m)^OUI$') {
        Write-Host "Sauvegarde réussie dans $destination." -ForegroundColor Green
    } else {
        Write-Host "Sauvegarde faite, mais la restauration d’essai n’a pas réussi : voir le détail ci-dessus et l’état dans l’application." -ForegroundColor Yellow
    }
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
Pause-Fin
