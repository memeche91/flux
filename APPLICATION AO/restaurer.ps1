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
# Volumes du serveur recréés avant la restauration : les services qui les utilisaient ont été supprimés.
$script:servicesSupprimes = $false

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

# Fenêtre gardée ouverte en fin de script ; lancé par double-clic sur le fichier .cmd, c'est lui qui la garde ouverte.
function Pause-Fin {
    if (-not $env:DAPLOMB_LANCEUR) { Read-Host "Appuyez sur Entrée pour fermer" | Out-Null }
}

function Arreter([string]$message) {
    Deconnecter-Partage
    if ($script:servicesSupprimes) {
        $message += "`nL’application a été arrêtée pour renouveler son accès au serveur : relancez installer.ps1 pour la redémarrer."
    }
    Write-Host ""
    Write-Host $message -ForegroundColor Red
    Pause-Fin
    exit 1
}

# Lecture et écriture d'une ligne NOM=valeur du fichier .env (mêmes règles que installer.ps1).
function Lire-Variable([string]$contenu, [string]$nom) {
    # Ligne présente plusieurs fois : Docker Compose garde la dernière, ce script aussi.
    $trouves = [regex]::Matches($contenu, "(?m)^$nom=([^\r\n]*)")
    if ($trouves.Count -gt 0) {
        $valeur = $trouves[$trouves.Count - 1].Groups[1].Value.Trim()
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

# Fichiers sur le PC : le service worker lit les sauvegardes dans le dossier que Docker monte (ligne
# DOSSIER_SAUVEGARDES_PC de .env, sinon donnees\sauvegardes). Le dossier indiqué devient ce dossier ; un
# dossier ou un lecteur réseau, que Docker ne peut pas monter, ou un chemin avec apostrophe, que Docker ne
# sait pas lire dans .env, est d'abord recopié dans donnees\sauvegardes.
function Utiliser-Dossier-Sauvegardes([string]$dossier) {
    if (-not (Test-Path -LiteralPath (Join-Path $dossier "base"))) {
        Write-Host "Sous-dossier base introuvable dans $dossier." -ForegroundColor Yellow
        return
    }
    $dossierLocal = Join-Path $PSScriptRoot "donnees\sauvegardes"
    # Chemin complet (écrit tel quel dans .env) : l'apostrophe peut venir du dossier de l'application.
    if ((Est-Reseau $dossier) -or ((Chemin-Complet $dossier).Contains("'") -and (Chemin-Complet $dossier) -ne (Chemin-Complet $dossierLocal))) {
        Write-Host "Copie des sauvegardes de $dossier dans $dossierLocal (Docker ne peut pas lire un dossier ou un lecteur réseau, ni un chemin avec apostrophe)…"
        robocopy $dossier $dossierLocal /E /XO /R:2 /W:5 /NP /NFL /NDL /NJH | Out-Host
        if ($LASTEXITCODE -ge 8) { Arreter "La copie des sauvegardes a échoué (code robocopy $LASTEXITCODE)." }
        # Le .env doit être celui des sauvegardes indiquées, même plus ancien (/XO garderait celui de la sauvegarde
        # de contrôle d'installer.ps1, avec sa nouvelle clé : la différence de clé ne serait pas signalée).
        $envSource = Join-Path $dossier "configuration\.env"
        if (Test-Path -LiteralPath $envSource) {
            try {
                Copy-Item -LiteralPath $envSource -Destination (Join-Path $dossierLocal "configuration\.env") -Force -ErrorAction Stop
            } catch {
                Arreter "Copie du fichier configuration\.env des sauvegardes impossible : $($_.Exception.Message)"
            }
        }
        $dossier = $dossierLocal
    }
    $monte = Lire-Variable $script:contenuEnv "DOSSIER_SAUVEGARDES_PC"
    if (-not $monte) { $monte = $dossierLocal }
    $lisible = [System.IO.Path]::IsPathRooted($monte) -or $monte.StartsWith('.')
    if ($lisible -and (Chemin-Complet $monte) -eq (Chemin-Complet $dossier)) { return }
    # Chemin complet : un chemin relatif tapé sans « .\ » n'est pas lisible par Docker.
    $complet = Chemin-Complet $dossier
    $probleme = ""
    if ($complet -ne (Chemin-Complet $dossierLocal)) { $probleme = Probleme-Dossier $complet }
    # Archives et sauvegardes : deux dossiers distincts, aucun dans l'autre.
    $archivesPc = Lire-Variable $script:contenuEnv "DOSSIER_ARCHIVES_PC"
    if (-not $archivesPc) { $archivesPc = "donnees\archives" }
    $a = (Chemin-Complet $archivesPc) + '\'
    $c = $complet + '\'
    if (-not $probleme -and ($a.StartsWith($c, [System.StringComparison]::OrdinalIgnoreCase) -or $c.StartsWith($a, [System.StringComparison]::OrdinalIgnoreCase))) {
        $probleme = "ne doit être ni le dossier des archives (DOSSIER_ARCHIVES_PC), ni dedans, ni le contenir"
    }
    if ($probleme) {
        Arreter ("Dossier des sauvegardes « $complet » : il $probleme ; $(Abandon)`n" +
            "Recopiez les sauvegardes dans un dossier comme E:\Sauvegardes DAplomb, puis relancez ce script.")
    }
    $valeur = "'" + $complet + "'"
    if ($complet -eq (Chemin-Complet $dossierLocal)) { $valeur = "" }
    $script:contenuEnv = Definir-Variable $script:contenuEnv "DOSSIER_SAUVEGARDES_PC" $valeur
    Enregistrer-Env $script:contenuEnv
    if (-not $script:noteEnv) { $script:noteEnv = " (.env a été mis à jour)" }
    Write-Host "Dossier des sauvegardes de l’application désormais : $complet (ligne DOSSIER_SAUVEGARDES_PC de .env, au lieu de $monte)." -ForegroundColor Cyan
}

# Fin des messages d'abandon : .env a pu être repris de la sauvegarde ou modifié avant la confirmation.
function Abandon {
    if ($script:noteEnv -or $script:servicesSupprimes) { return "la base n’a pas été modifiée$($script:noteEnv)." }
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
# Nouveau PC : l'application n'y a jamais été démarrée en entier (par installer.ps1, ou après une restauration
# réussie). Le volume des modèles de l'assistant n'est créé que par ce démarrage complet : après une tentative de
# restauration ratée, qui a créé le volume de la base, le passage suivant se termine donc encore par installer.ps1.
docker volume inspect application-ao_modeles_ia 2>&1 | Out-Null
$nouveauPc = (-not $baseExistait) -or ($LASTEXITCODE -ne 0)

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
if (-not $serveur) {
    # Dossiers du PC écrits à la main dans .env : vérifiés (jamais réécrits), comme par installer.ps1.
    foreach ($nomDossier in @("DOSSIER_SAUVEGARDES_PC", "DOSSIER_ARCHIVES_PC")) {
        $cheminLu = Lire-Variable $contenuEnv $nomDossier
        $probleme = Probleme-Dossier $cheminLu
        if ($probleme) {
            Arreter ("Ligne $nomDossier de .env (« $cheminLu ») : le dossier $probleme ; $(Abandon)`n" +
                "Corrigez cette ligne avec le Bloc-notes (exemple : $nomDossier=$(@{ DOSSIER_SAUVEGARDES_PC = 'E:\Sauvegardes DAplomb'; DOSSIER_ARCHIVES_PC = 'D:\Archives chantiers' }[$nomDossier]), ou videz-la), puis relancez ce script.")
        }
    }
    # Archives sur un dossier ou un lecteur réseau, que Docker ne sait pas ouvrir : la restauration ne pourrait pas
    # démarrer, ou recopierait les archives hors d'atteinte (installer.ps1 refuse aussi ce réglage).
    $archivesPc = Lire-Variable $contenuEnv "DOSSIER_ARCHIVES_PC"
    if ($archivesPc -and (Est-Reseau $archivesPc)) {
        Arreter ("DOSSIER_ARCHIVES_PC ($archivesPc) est un dossier ou un lecteur réseau, que Docker ne sait pas ouvrir : $(Abandon)`n" +
            "Indiquez dans .env un dossier d’un disque du PC (par exemple DOSSIER_ARCHIVES_PC='D:\Archives chantiers'), ou videz la ligne, puis relancez ce script.")
    }
}
# Fichiers sur le PC : la liste et la restauration lisent le dossier monté par Docker, qui doit être celui
# indiqué ci-dessus (disque externe qui a changé de lettre, sauvegardes recopiées ailleurs…).
if ($dossier -and -not $serveur) { Utiliser-Dossier-Sauvegardes $dossier }
Deconnecter-Partage
if ($serveur) {
    # L'adresse du serveur peut avoir changé depuis la sauvegarde : elle est mise à jour dans .env.
    $nomServeur = ((Lire-Variable $contenuEnv "SERVEUR_CHEMIN_AFFICHE").TrimStart('\') -split '\\')[0]
    $adresse = Lire-Variable $contenuEnv "SERVEUR_ADRESSE"
    $nouvelle = ""
    if ($nomServeur) { $nouvelle = Adresse-Serveur $nomServeur }
    if ($nouvelle -and $nouvelle -ne $adresse) {
        Write-Host "Le serveur $nomServeur a changé d’adresse : $nouvelle (au lieu de $adresse)."
        $contenuEnv = Definir-Variable $contenuEnv "SERVEUR_ADRESSE" $nouvelle
        Enregistrer-Env $contenuEnv
        if (-not $noteEnv) { $noteEnv = " (.env a été mis à jour)" }
    }
    # Les réglages d'un volume du serveur (adresse, compte, mot de passe) sont fixés à sa création : s'ils ne
    # correspondent plus à .env (adresse ci-dessus, mot de passe corrigé dans .env…), le volume est recréé, comme
    # par installer.ps1. Sinon Docker Compose demanderait s'il faut le recréer, sans que la question s'affiche,
    # et le script resterait bloqué. Les fichiers du serveur ne sont pas touchés.
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
                if ($conteneurs.Count -gt 0) {
                    docker rm -f $conteneurs | Out-Null
                    # Application arrêtée : les messages d'abandon disent comment la redémarrer (pas sur un nouveau
                    # PC, où installer.ps1 ne doit être lancé qu'après la restauration).
                    if (-not $nouveauPc) { $servicesSupprimes = $true }
                }
                docker volume rm $volume 2>&1 | Out-Null
            }
        }
    }
}

Ecrire-Etape "Préparation (construction de l’application au premier lancement : 5 à 10 minutes)"
docker compose build worker
if ($LASTEXITCODE -ne 0) { Arreter "La construction de l’application a échoué. Consultez les messages ci-dessus." }

Ecrire-Etape "Choix de la sauvegarde"
# Liste lue par le service worker : il voit le dossier des sauvegardes comme la sauvegarde de chaque nuit
# (dossier du PC ou partage du serveur), sans autre réglage.
# Fichiers sur le PC avec un .env déjà présent : le dossier monté n'est pas forcément celui des sauvegardes à
# restaurer (nouveau PC où installer.ps1 a été lancé avant ce script, disque externe qui a changé de lettre…).
# Il est indiqué avant la liste, et un autre dossier peut être choisi.
$demander = (-not $serveur) -and (-not $dossier)
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
    if ($serveur -or ($copies.Count -gt 0 -and -not $demander)) { break }
    $monte = Lire-Variable $contenuEnv "DOSSIER_SAUVEGARDES_PC"
    if (-not $monte) { $monte = "donnees\sauvegardes" }
    if ($copies.Count -gt 0) {
        $recente = $copies | Where-Object { $_.Datee } | Sort-Object Nom -Descending | Select-Object -First 1
        $precision = ""
        if ($recente) { $precision = ", la plus récente du $(Libelle-Copie $recente.Nom)" }
        Write-Host "Sauvegardes lues dans $monte (ligne DOSSIER_SAUVEGARDES_PC de .env) : $($copies.Count) copie(s)$precision."
        Write-Host "Si les sauvegardes à restaurer sont ailleurs (nouveau PC où installer.ps1 a déjà été lancé, disque externe…),"
        Write-Host "indiquez leur dossier : il devient le dossier des sauvegardes de l’application."
        $autre = (Read-Host "Autre dossier des sauvegardes (Entrée : garder celui-ci)").Trim().Trim('"').TrimEnd('\')
    } else {
        # Dossier monté vide ou absent (disque externe qui a changé de lettre, .env neuf…).
        Write-Host "Aucune sauvegarde trouvée dans le dossier des sauvegardes du PC ($monte, sous-dossier base)." -ForegroundColor Yellow
        if (Est-Reseau $monte) {
            Write-Host "Ce dossier est un dossier ou un lecteur réseau, que Docker ne sait pas ouvrir : indiquez-le ci-dessous, ses sauvegardes seront recopiées sur ce PC." -ForegroundColor Yellow
        }
        $autre = (Read-Host "Dossier qui contient les sauvegardes (sous-dossiers base et configuration ; Entrée pour abandonner)").Trim().Trim('"').TrimEnd('\')
    }
    if (-not $autre) { break }
    $autre = Connecter-Dossier $autre "base"
    if (Test-Path -LiteralPath (Join-Path $autre "base")) {
        Utiliser-Dossier-Sauvegardes $autre
        $demander = $false
    } else {
        Write-Host "Sous-dossier base introuvable dans $autre : indiquez le dossier qui contient les sous-dossiers base et configuration." -ForegroundColor Yellow
    }
    Deconnecter-Partage
}
# Les plus récentes d'abord ; les copies faites avant une restauration ensuite.
$copies = @(@($copies | Where-Object { $_.Datee } | Sort-Object Nom -Descending) + @($copies | Where-Object { -not $_.Datee } | Sort-Object Nom -Descending))
if ($copies.Count -eq 0) {
    $ou = "le dossier des sauvegardes du PC"
    if ($serveur) { $ou = "$(Lire-Variable $contenuEnv 'SERVEUR_CHEMIN_AFFICHE')\sauvegardes" }
    $conseil = "Vérifiez que le dossier est accessible (message de Docker éventuel ci-dessus)."
    if ($serveur) {
        $conseil = "Vérifiez que le serveur est allumé et que le compte dédié (lignes SERVEUR_… de .env) a toujours accès au dossier (message de Docker éventuel ci-dessus)."
        if ($nouveauPc) {
            $conseil += "`nSi son mot de passe a changé : corrigez la ligne SERVEUR_MOT_DE_PASSE= de .env (entre apostrophes droites : SERVEUR_MOT_DE_PASSE='…' ; mot de passe sans virgule, guillemet ni apostrophe, qui ne se termine pas par \), puis relancez ce script."
        } else {
            $conseil += "`nSi son mot de passe a changé : relancez d’abord installer.ps1, qui le redemande, puis relancez ce script."
        }
    }
    if ($nouveauPc) {
        # Nouveau PC : installer.ps1 créerait une base vide, dont la sauvegarde de contrôle serait ensuite la copie la plus récente.
        $conseil += "`nNe lancez pas installer.ps1 avant d’avoir restauré : il créerait une base vide."
    } else {
        $conseil += "`nSi aucune sauvegarde n’a encore été faite, lancez d’abord installer.ps1."
    }
    Arreter "Aucune sauvegarde trouvée dans $ou (sous-dossier base). $conseil"
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
    Write-Host "Si ce .env a été créé par installer.ps1 sur ce PC, les copies faites depuis (sauvegarde de contrôle comprise)" -ForegroundColor Yellow
    Write-Host "sont celles de sa base neuve : la copie choisie (du $libelle) doit être plus ancienne, sinon annulez et relancez ce script." -ForegroundColor Yellow
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
# Désormais, l'application est arrêtée pour la restauration : les messages qui suivent disent quoi faire.
$servicesSupprimes = $false
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
    # Base remplacée mais pas à jour : l'application, qui applique migrate au démarrage, échouerait en boucle.
    $conseil = ""
    if (-not $nouveauPc) { $conseil = " (par exemple « avant-restauration_… », la base d’avant)" }
    Arreter ("La base a été remplacée, mais sa mise à jour de structure a échoué (détail ci-dessus) : l’application n’est pas redémarrée.`n" +
        "Relancez restaurer.ps1 et choisissez une autre copie$conseil.")
}
if ($codeRestauration -eq 3) {
    # Base restaurée, recopie des fichiers incomplète : pas de reprise du travail avant la fin de la recopie.
    Arreter ("La base a été restaurée, mais la recopie des fichiers est incomplète (détail ci-dessus) : l’application n’est pas redémarrée.`n" +
        "Corrigez la cause indiquée, puis relancez restaurer.ps1 avec la même copie ($libelle : $($choix.Nom)) et acceptez la recopie des fichiers (rien n’est effacé).`n" +
        "Si la cause ne peut pas être corrigée, installer.ps1 démarre l’application sans les fichiers non recopiés.")
}
if (-not $restauree) {
    if ($nouveauPc) {
        # Nouveau PC : démarrer l'application sur la base vide ferait croire l'installation terminée.
        Arreter ("La restauration a échoué (détail ci-dessus) : l’application n’est pas démarrée.`n" +
            "Relancez restaurer.ps1 (choisissez une autre copie si besoin) : il lancera ensuite installer.ps1 pour terminer la mise en place.")
    }
    Write-Host "La restauration a échoué (détail ci-dessus) : la base est restée telle qu’elle était." -ForegroundColor Red
}

Ecrire-Etape "Redémarrage de l’application"
if ($restauree -and $nouveauPc) {
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
Pause-Fin
