<#
  D’Aplomb - restauration d’une sauvegarde sous Windows
  Vos projets d’aplomb, de l’appel d’offres à la réception.

  Remet en place une copie de la base de données faite par la sauvegarde de chaque nuit
  (sous-dossier « sauvegardes » du dossier partagé du serveur de l'agence, ou dossier des
  sauvegardes du PC). La base actuelle est d'abord copiée (base\avant-restauration_…).

  Utilisation : clic droit sur ce fichier > « Exécuter avec PowerShell »
  ou, dans PowerShell :  powershell -ExecutionPolicy Bypass -File .\restaurer.ps1
  Option : -Sauvegarde 2026-11-08_0230.dump (sinon la liste des sauvegardes est proposée).

  Nouveau PC après une panne : installez Docker Desktop, récupérez le dossier de l'application,
  puis lancez directement ce script : il reprend le fichier .env enregistré avec les sauvegardes,
  restaure la base, puis lance installer.ps1 pour terminer.
#>
param([string]$Sauvegarde = "")

Set-Location -LiteralPath $PSScriptRoot

Write-Host "D’Aplomb - restauration d’une sauvegarde" -ForegroundColor Cyan

$script:connexionPartage = ""

function Ecrire-Etape([string]$texte) {
    Write-Host ""
    Write-Host "==> $texte" -ForegroundColor Yellow
}

function Deconnecter-Partage {
    if ($script:connexionPartage) {
        net use $script:connexionPartage /delete /y 2>&1 | Out-Null
        $script:connexionPartage = ""
    }
}

function Arreter([string]$message) {
    Deconnecter-Partage
    Write-Host ""
    Write-Host $message -ForegroundColor Red
    Read-Host "Appuyez sur Entrée pour fermer"
    exit 1
}

# Lecture et écriture d'une ligne NOM=valeur du fichier .env (mêmes règles que installer.ps1).
function Lire-Variable([string]$contenu, [string]$nom) {
    $trouve = [regex]::Match($contenu, "(?m)^$nom=([^\r\n]*)")
    if ($trouve.Success) {
        $valeur = $trouve.Groups[1].Value.Trim()
        if ($valeur.Length -ge 2 -and $valeur.StartsWith("'") -and $valeur.EndsWith("'")) { $valeur = $valeur.Substring(1, $valeur.Length - 2) }
        return $valeur
    }
    return ""
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

function Texte-Sortie($sortie) {
    return ((@($sortie) | ForEach-Object { "$_" }) -join "`n").Trim()
}

function Contient-Fichiers([string]$dossier) {
    if (-not (Test-Path -LiteralPath $dossier)) { return $false }
    return [bool](Get-ChildItem -LiteralPath $dossier -Recurse -File -Force -ErrorAction SilentlyContinue | Select-Object -First 1)
}

# Adresse IPv4 du serveur de l'agence (Docker ne connaît pas les noms du réseau Windows).
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

# Dossier des sauvegardes sur le serveur, souvent ouvert au seul compte dédié à D’Aplomb : connexion avec
# ce compte par l'adresse IP du serveur, comme installer.ps1 (une connexion déjà ouverte au nom du serveur
# avec le compte de la session ne gêne pas). Renvoie le chemin à utiliser ensuite.
function Connecter-Dossier([string]$dossier, [string]$attendu) {
    if (-not $dossier.StartsWith('\\') -or (Test-Path -LiteralPath (Join-Path $dossier $attendu))) { return $dossier }
    Write-Host "Ce dossier n’est pas accessible avec votre session Windows : indiquez le compte dédié à D’Aplomb."
    $compte = (Read-Host "Compte (DOMAINE\utilisateur, ou SERVEUR\utilisateur)").Trim()
    $secret = Read-Host "Mot de passe de ce compte" -AsSecureString
    $motDePasse = (New-Object System.Management.Automation.PSCredential("compte", $secret)).GetNetworkCredential().Password
    $parties = @($dossier.TrimStart('\').Split('\') | Where-Object { $_ })
    if (-not $compte -or $parties.Count -lt 2) { return $dossier }
    $racine = "\\" + $parties[0] + "\" + $parties[1]
    $ip = Adresse-Serveur $parties[0]
    if ($ip) {
        $racine = "\\$ip\" + $parties[1]
        $dossier = "\\$ip\" + (($parties[1..($parties.Count - 1)]) -join '\')
    }
    Deconnecter-Partage
    $sortie = net use $racine $motDePasse "/user:$compte" /persistent:no 2>&1
    if ($LASTEXITCODE -eq 0) {
        $script:connexionPartage = $racine
    } else {
        $texte = Texte-Sortie $sortie
        if ($texte -match '1219') {
            $texte += "`nUne connexion à $racine est déjà ouverte avec un autre compte : fermez-la (net use $racine /delete) ou redémarrez le PC, puis relancez ce script."
        }
        Write-Host $texte -ForegroundColor Yellow
    }
    return $dossier
}

function Chemin-Complet([string]$chemin) {
    if (-not [System.IO.Path]::IsPathRooted($chemin)) { $chemin = Join-Path $PSScriptRoot $chemin }
    return [System.IO.Path]::GetFullPath($chemin).TrimEnd('\')
}

# Fichiers sur le PC : le service worker lit les sauvegardes dans le dossier que Docker monte (ligne
# DOSSIER_SAUVEGARDES_PC de .env, sinon donnees\sauvegardes). Le dossier indiqué devient ce dossier ; un
# dossier réseau, que Docker ne peut pas monter, est d'abord recopié dans donnees\sauvegardes.
function Utiliser-Dossier-Sauvegardes([string]$dossier) {
    if (-not (Test-Path -LiteralPath (Join-Path $dossier "base"))) {
        Write-Host "Sous-dossier base introuvable dans $dossier." -ForegroundColor Yellow
        return
    }
    $dossierLocal = Join-Path $PSScriptRoot "donnees\sauvegardes"
    if ($dossier.StartsWith('\\')) {
        Write-Host "Copie des sauvegardes de $dossier dans $dossierLocal (Docker ne peut pas lire un dossier réseau)…"
        robocopy $dossier $dossierLocal /E /XO /R:2 /W:5 /NP /NFL /NDL /NJH | Out-Host
        if ($LASTEXITCODE -ge 8) { Arreter "La copie des sauvegardes a échoué (code robocopy $LASTEXITCODE)." }
        $dossier = $dossierLocal
    }
    $monte = (Lire-Variable $script:contenuEnv "DOSSIER_SAUVEGARDES_PC").Trim('"')
    if (-not $monte) { $monte = $dossierLocal }
    if ((Chemin-Complet $monte) -eq (Chemin-Complet $dossier)) { return }
    $valeur = "'" + $dossier + "'"
    if ((Chemin-Complet $dossier) -eq (Chemin-Complet $dossierLocal)) { $valeur = "" }
    $script:contenuEnv = Definir-Variable $script:contenuEnv "DOSSIER_SAUVEGARDES_PC" $valeur
    Enregistrer-Env $script:contenuEnv
    if (-not $script:noteEnv) { $script:noteEnv = " (.env a été mis à jour)" }
    Write-Host "Dossier des sauvegardes de l’application désormais : $dossier (ligne DOSSIER_SAUVEGARDES_PC de .env, au lieu de $monte)." -ForegroundColor Cyan
}

# Fin des messages d'abandon : .env a pu être repris de la sauvegarde ou modifié avant la confirmation.
function Abandon {
    if ($script:noteEnv) { return "la base n’a pas été modifiée$($script:noteEnv)." }
    return "rien n’a été modifié."
}

# « 2026-11-08_0230.dump » -> « 08/11/2026 à 02:30 ».
function Libelle-Copie([string]$nom) {
    if ($nom -match '^avant-restauration_(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})') {
        return "copie faite avant la restauration du $($Matches[3])/$($Matches[2])/$($Matches[1]) à $($Matches[4]):$($Matches[5])"
    }
    if ($nom -match '^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})') {
        return "$($Matches[3])/$($Matches[2])/$($Matches[1]) à $($Matches[4]):$($Matches[5])"
    }
    return $nom
}

Ecrire-Etape "Vérification de Docker Desktop"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Arreter "Docker Desktop n’est pas installé. Téléchargez-le sur https://www.docker.com/products/docker-desktop/ puis relancez ce script."
}
docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Arreter "Docker Desktop n’est pas démarré. Ouvrez-le, attendez qu’il indique « Engine running », puis relancez ce script."
}
Write-Host "Docker Desktop est prêt."
docker volume inspect application-ao_base_donnees 2>&1 | Out-Null
$baseExistait = ($LASTEXITCODE -eq 0)

Ecrire-Etape "Configuration de l’application (.env)"
$cheminEnv = Join-Path $PSScriptRoot ".env"
$dossier = ""
# Précision ajoutée aux messages d'abandon quand .env a déjà été repris ou modifié.
$noteEnv = ""
if (Test-Path -LiteralPath $cheminEnv) {
    Write-Host "Le fichier .env de ce dossier est conservé."
} else {
    Write-Host "Le fichier .env est absent : il est repris de la sauvegarde. Il contient la clé des codes d’accès"
    Write-Host "des entreprises à la GED, le mot de passe de la base et les réglages du serveur et de la messagerie."
    $proposition = ""
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot "donnees\sauvegardes\configuration\.env")) { $proposition = Join-Path $PSScriptRoot "donnees\sauvegardes" }
    Write-Host "Dossier des sauvegardes : sur le serveur de l’agence, par exemple \\SERVEUR\DAplomb\sauvegardes ;"
    Write-Host "sinon le dossier choisi pour les sauvegardes (ligne DOSSIER_SAUVEGARDES_PC, disque externe…)."
    $invite = "Dossier des sauvegardes"
    if ($proposition) { $invite += " (Entrée : $proposition)" }
    $dossier = (Read-Host $invite).Trim().Trim('"').TrimEnd('\')
    if (-not $dossier) { $dossier = $proposition }
    if (-not $dossier) { Arreter "Aucun dossier indiqué : rien n’a été modifié." }
    $dossier = Connecter-Dossier $dossier "configuration\.env"
    $envSauvegarde = Join-Path $dossier "configuration\.env"
    if (-not (Test-Path -LiteralPath $envSauvegarde)) {
        Arreter "Fichier introuvable : $envSauvegarde`nIndiquez le dossier qui contient les sous-dossiers « base » et « configuration »."
    }
    try {
        Copy-Item -LiteralPath $envSauvegarde -Destination $cheminEnv -ErrorAction Stop
    } catch {
        Arreter "Copie du fichier .env impossible : $($_.Exception.Message)"
    }
    $noteEnv = " (.env a été repris de la sauvegarde)"
    Write-Host "Fichier .env repris de la sauvegarde." -ForegroundColor Green
}
$contenuEnv = [System.IO.File]::ReadAllText($cheminEnv)
$serveur = (Lire-Variable $contenuEnv "COMPOSE_FILE") -match 'serveur'
# Fichiers sur le PC : la liste et la restauration lisent le dossier monté par Docker, qui doit être celui
# indiqué ci-dessus (disque externe qui a changé de lettre, sauvegardes recopiées ailleurs…).
if ($dossier -and -not $serveur) { Utiliser-Dossier-Sauvegardes $dossier }
Deconnecter-Partage
if ($serveur) {
    # L'adresse du serveur peut avoir changé depuis la sauvegarde : les volumes du serveur sont alors recréés.
    $nomServeur = ((Lire-Variable $contenuEnv "SERVEUR_CHEMIN_AFFICHE").TrimStart('\') -split '\\')[0]
    $adresse = Lire-Variable $contenuEnv "SERVEUR_ADRESSE"
    $nouvelle = ""
    if ($nomServeur) { $nouvelle = Adresse-Serveur $nomServeur }
    if ($nouvelle -and $nouvelle -ne $adresse) {
        Write-Host "Le serveur $nomServeur a changé d’adresse : $nouvelle (au lieu de $adresse)."
        $contenuEnv = Definir-Variable $contenuEnv "SERVEUR_ADRESSE" $nouvelle
        Enregistrer-Env $contenuEnv
        if (-not $noteEnv) { $noteEnv = " (.env a été mis à jour)" }
        foreach ($nom in @("fichiers", "archives", "sauvegardes")) {
            $volume = "application-ao_serveur_$nom"
            $conteneurs = @(docker ps -aq --filter "volume=$volume")
            if ($conteneurs.Count -gt 0) { docker rm -f $conteneurs | Out-Null }
            docker volume rm $volume 2>&1 | Out-Null
        }
    }
}

Ecrire-Etape "Préparation (construction de l’application au premier lancement : 5 à 10 minutes)"
docker compose build worker
if ($LASTEXITCODE -ne 0) { Arreter "La construction de l’application a échoué. Consultez les messages ci-dessus." }

Ecrire-Etape "Choix de la sauvegarde"
# Liste lue par le service worker : il voit le dossier des sauvegardes comme la sauvegarde de chaque nuit
# (dossier du PC ou partage du serveur), sans autre réglage.
while ($true) {
    $sortie = docker compose run --rm --no-deps -T worker sh -c 'cd /sauvegardes/base 2>/dev/null && stat -c %n:%s *.dump 2>/dev/null'
    $copies = @()
    foreach ($ligneCopie in @($sortie)) {
        if ("$ligneCopie" -match '^([^:/]+\.dump):(\d+)$') {
            $nomCopie = $Matches[1]
            $tailleCopie = [double]$Matches[2]
            $copies += New-Object PSObject -Property @{ Nom = $nomCopie; Taille = $tailleCopie; Datee = ($nomCopie -match '^\d{4}-\d{2}-\d{2}_\d{4}') }
        }
    }
    if ($copies.Count -gt 0 -or $serveur) { break }
    # Fichiers sur le PC : dossier monté vide ou absent (disque externe qui a changé de lettre, .env neuf…).
    $monte = Lire-Variable $contenuEnv "DOSSIER_SAUVEGARDES_PC"
    if (-not $monte) { $monte = "donnees\sauvegardes" }
    Write-Host "Aucune sauvegarde trouvée dans le dossier des sauvegardes du PC ($monte, sous-dossier base)." -ForegroundColor Yellow
    $autre = (Read-Host "Dossier qui contient les sauvegardes (sous-dossiers base et configuration ; Entrée pour abandonner)").Trim().Trim('"').TrimEnd('\')
    if (-not $autre) { break }
    Utiliser-Dossier-Sauvegardes (Connecter-Dossier $autre "base")
    Deconnecter-Partage
}
# Les plus récentes d'abord ; les copies faites avant une restauration ensuite.
$copies = @(@($copies | Where-Object { $_.Datee } | Sort-Object Nom -Descending) + @($copies | Where-Object { -not $_.Datee } | Sort-Object Nom -Descending))
if ($copies.Count -eq 0) {
    $ou = "le dossier des sauvegardes du PC"
    if ($serveur) { $ou = "$(Lire-Variable $contenuEnv 'SERVEUR_CHEMIN_AFFICHE')\sauvegardes" }
    Arreter "Aucune sauvegarde trouvée dans $ou (sous-dossier base). Vérifiez que le dossier est accessible, ou lancez d’abord installer.ps1."
}
$choix = $null
if ($Sauvegarde) {
    $nomDemande = Split-Path $Sauvegarde.Replace('/', '\') -Leaf
    $choix = $copies | Where-Object { $_.Nom -eq $nomDemande } | Select-Object -First 1
    if (-not $choix) { Arreter "Sauvegarde « $nomDemande » introuvable dans le sous-dossier base des sauvegardes." }
} else {
    $affichees = @($copies | Select-Object -First 20)
    for ($i = 0; $i -lt $affichees.Count; $i++) {
        Write-Host ("{0,4}. {1,-48} {2,10:N1} Mo" -f ($i + 1), (Libelle-Copie $affichees[$i].Nom), ($affichees[$i].Taille / 1MB))
    }
    if ($copies.Count -gt $affichees.Count) { Write-Host "  (et $($copies.Count - $affichees.Count) plus anciennes : option -Sauvegarde <nom>)" }
    $reponse = (Read-Host "Numéro de la sauvegarde à restaurer (Entrée : 1, la plus récente)").Trim()
    if (-not $reponse) { $reponse = "1" }
    if ($reponse -notmatch '^\d{1,3}$' -or [int]$reponse -lt 1 -or [int]$reponse -gt $affichees.Count) { Arreter "Choix non reconnu : $(Abandon)" }
    $choix = $affichees[[int]$reponse - 1]
}
$libelle = Libelle-Copie $choix.Nom
Write-Host "Sauvegarde choisie : $libelle ($($choix.Nom))."

# Clé des codes d'accès de la GED : celle de la sauvegarde, sinon les codes des entreprises ne marchent plus
# (cas d'un .env recréé par installer.ps1 sur un nouveau PC avant la restauration).
$envSauvegarde = docker compose run --rm --no-deps -T worker cat /sauvegardes/configuration/.env 2>$null
$cleSauvegardee = Lire-Variable (Texte-Sortie $envSauvegarde) "DJANGO_SECRET_KEY"
$cleActuelle = Lire-Variable $contenuEnv "DJANGO_SECRET_KEY"
if ($cleSauvegardee -and $cleSauvegardee -cne $cleActuelle) {
    Write-Host "La clé DJANGO_SECRET_KEY du fichier .env diffère de celle enregistrée avec les sauvegardes :" -ForegroundColor Yellow
    Write-Host "avec la clé actuelle, les codes d’accès des entreprises à la GED ne fonctionneraient plus." -ForegroundColor Yellow
    if ((Read-Host "Reprendre la clé de la sauvegarde dans .env ? (O/N, O par défaut)") -notmatch '^\s*[nN]') {
        $contenuEnv = Definir-Variable $contenuEnv "DJANGO_SECRET_KEY" $cleSauvegardee
        Enregistrer-Env $contenuEnv
        if (-not $noteEnv) { $noteEnv = " (.env a été mis à jour)" }
        Write-Host "Clé reprise. Comparez aussi vos autres réglages (messagerie, GED) avec le fichier configuration\.env des sauvegardes."
    }
}

$avecFichiers = $false
if (-not $serveur) {
    # Fichiers rangés sur ce PC : la sauvegarde en contient une copie (sous-dossiers fichiers et archives).
    $vide = -not (Contient-Fichiers (Join-Path $PSScriptRoot "donnees\fichiers"))
    $parDefaut = "N"
    if ($vide) { $parDefaut = "O" }
    $reponse = Read-Host "Recopier aussi les fichiers et les archives depuis la sauvegarde (fichiers absents ou différents, rien n’est effacé) ? (O/N, $parDefaut par défaut)"
    if ($vide) { $avecFichiers = $reponse -notmatch '^\s*[nN]' } else { $avecFichiers = $reponse -match '^\s*[oO]' }
}

Write-Host ""
Write-Host "La base de données actuelle va être REMPLACÉE par la sauvegarde du $libelle." -ForegroundColor Red
Write-Host "Tout ce qui a été saisi depuis sera perdu. Une copie de la base actuelle est faite juste avant."
if ((Read-Host "Tapez OUI pour confirmer") -ne "OUI") { Arreter "Restauration annulée : $(Abandon)" }

Ecrire-Etape "Arrêt de l’application et démarrage de la base de données"
$conteneurs = @(docker ps -q --filter "label=com.docker.compose.project=application-ao")
if ($conteneurs.Count -gt 0) { docker stop $conteneurs | Out-Null }
docker compose up -d base redis
if ($LASTEXITCODE -ne 0) { Arreter "La base de données ne démarre pas. Consultez : docker compose logs base" }
$pret = $false
for ($essai = 0; $essai -lt 60; $essai++) {
    docker compose exec -T base pg_isready -q 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $pret = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $pret) { Arreter "La base de données ne répond pas. Consultez : docker compose logs base" }

Ecrire-Etape "Restauration de la base de données (quelques minutes)"
$arguments = @("compose", "run", "--rm", "--no-deps", "-T", "worker", "python", "manage.py", "restaurer", "/sauvegardes/base/$($choix.Nom)", "--confirmer")
if ($avecFichiers) { $arguments += "--avec-fichiers" }
& docker @arguments
$codeRestauration = $LASTEXITCODE
$restauree = ($codeRestauration -eq 0)
if ($codeRestauration -eq 2) {
    Write-Host "La base a été remplacée, mais sa mise à jour de structure a échoué (détail ci-dessus)." -ForegroundColor Red
    Write-Host "Relancez restaurer.ps1 et choisissez la copie « avant-restauration_… » pour revenir à la base d’avant, ou une autre copie." -ForegroundColor Red
} elseif (-not $restauree) {
    Write-Host "La restauration a échoué (détail ci-dessus) : la base est restée telle qu’elle était." -ForegroundColor Red
}

Ecrire-Etape "Redémarrage de l’application"
if ($restauree -and -not $baseExistait) {
    # Nouveau PC : l'installateur termine la mise en place (carte graphique, modèles de l'assistant, sauvegarde).
    Write-Host "Nouveau PC : installer.ps1 termine la mise en place." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "installer.ps1")
    exit 0
}
docker compose up -d --build --remove-orphans
if ($LASTEXITCODE -ne 0) { Arreter "Le redémarrage a échoué : lancez installer.ps1." }
$pret = $false
for ($essai = 0; $essai -lt 90; $essai++) {
    docker compose exec -T backend python manage.py migrate --check 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $pret = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $pret) { Arreter "L’application ne répond pas. Consultez : docker compose logs backend" }
if (-not $restauree) { Arreter "L’application a redémarré avec sa base d’avant. Restauration non faite." }

$port = Lire-Variable $contenuEnv "APP_PORT"
if (-not $port) { $port = "8080" }
Write-Host ""
Write-Host "Restauration terminée : la base est celle du $libelle." -ForegroundColor Green
Write-Host "La base d’avant la restauration est conservée dans le sous-dossier base des sauvegardes (avant-restauration_…)."
Write-Host "D’Aplomb est prêt : http://localhost:$port" -ForegroundColor Green
Start-Process "http://localhost:$port"
Read-Host "Appuyez sur Entrée pour fermer"
