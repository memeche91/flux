<#
  D’Aplomb - installation et démarrage sous Windows
  Vos projets d’aplomb, de l’appel d’offres à la réception.

  Utilisation : clic droit sur ce fichier > « Exécuter avec PowerShell »
  ou, dans PowerShell :  powershell -ExecutionPolicy Bypass -File .\installer.ps1

  Le script peut être relancé sans risque : il conserve la configuration
  et les données existantes, et met à jour l'application.
#>

Set-Location -LiteralPath $PSScriptRoot

Write-Host "D’Aplomb - installation et démarrage" -ForegroundColor Cyan
Write-Host "Vos projets d’aplomb, de l’appel d’offres à la réception."

function Ecrire-Etape([string]$texte) {
    Write-Host ""
    Write-Host "==> $texte" -ForegroundColor Yellow
}

function Arreter([string]$message) {
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
    if ($trouve.Success) { return $trouve.Groups[1].Value.Trim() }
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

# Fichiers Docker Compose à utiliser : carte graphique, GED sur Internet (ligne COMPOSE_FILE).
function Fichiers-Compose([bool]$gpu, [string]$modeGed) {
    $liste = @("docker-compose.yml")
    if ($gpu) { $liste += "docker-compose.gpu.yml" }
    if ($modeGed -eq "ip") { $liste += "docker-compose.internet.yml" }
    if ($modeGed -eq "tunnel") { $liste += "docker-compose.tunnel.yml" }
    return ($liste -join ";")
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

$fichiers = Fichiers-Compose $gpu $modeGed
if ($fichiers -eq "docker-compose.yml") {
    $contenuEnv = (($contenuEnv -split "`r?`n") | Where-Object { $_ -notmatch '^COMPOSE_FILE=' }) -join "`n"
} else {
    $contenuEnv = Definir-Variable $contenuEnv "COMPOSE_FILE" $fichiers
}
$env:COMPOSE_FILE = $fichiers
Enregistrer-Env $contenuEnv

Ecrire-Etape "Construction et démarrage (le premier lancement peut prendre 5 à 10 minutes)"
docker compose up -d --build --remove-orphans
if ($LASTEXITCODE -ne 0 -and $gpu) {
    # La carte graphique n'est plus accessible (pilote, réglage de Docker) : on repart sans elle.
    Write-Host "Démarrage impossible avec la carte graphique : nouvel essai sans elle." -ForegroundColor Yellow
    $gpu = $false
    $fichiers = Fichiers-Compose $gpu $modeGed
    if ($fichiers -eq "docker-compose.yml") {
        $contenuEnv = (($contenuEnv -split "`r?`n") | Where-Object { $_ -notmatch '^COMPOSE_FILE=' }) -join "`n"
    } else {
        $contenuEnv = Definir-Variable $contenuEnv "COMPOSE_FILE" $fichiers
    }
    Enregistrer-Env $contenuEnv
    $env:COMPOSE_FILE = $fichiers
    docker compose up -d --build --remove-orphans
}
if ($LASTEXITCODE -ne 0) {
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

Write-Host ""
Write-Host "D’Aplomb est prêt : http://localhost:$port" -ForegroundColor Green
Start-Process "http://localhost:$port"
Read-Host "Appuyez sur Entrée pour fermer"
