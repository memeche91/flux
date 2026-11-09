<#
  Application AO - installation et démarrage sous Windows

  Utilisation : clic droit sur ce fichier > « Exécuter avec PowerShell »
  ou, dans PowerShell :  powershell -ExecutionPolicy Bypass -File .\installer.ps1

  Le script peut être relancé sans risque : il conserve la configuration
  et les données existantes, et met à jour l'application.
#>

Set-Location -LiteralPath $PSScriptRoot

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
if ((Get-Command nvidia-smi -ErrorAction SilentlyContinue) -and $contenuEnv -notmatch '(?m)^COMPOSE_FILE=') {
    # Une carte NVIDIA ne suffit pas : Docker doit pouvoir l'utiliser (pilote récent, moteur WSL 2).
    Write-Host "Carte graphique NVIDIA détectée : vérification de son accès depuis Docker…"
    docker pull ollama/ollama:0.40.15 | Out-Null
    docker run --rm --gpus all --entrypoint /bin/true ollama/ollama:0.40.15 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $contenuEnv = $contenuEnv.TrimEnd() + "`nCOMPOSE_FILE=docker-compose.yml;docker-compose.gpu.yml`n"
        Write-Host "La carte graphique sera utilisée par l'assistant."
    } else {
        Write-Host "Docker ne peut pas utiliser la carte graphique (pilote NVIDIA à mettre à jour ?) : l'assistant utilisera le processeur."
    }
}
[System.IO.File]::WriteAllText($cheminEnv, $contenuEnv, (New-Object System.Text.UTF8Encoding($false)))

Ecrire-Etape "Construction et démarrage (le premier lancement peut prendre 5 à 10 minutes)"
docker compose up -d --build
if ($LASTEXITCODE -ne 0 -and (Select-String -LiteralPath $cheminEnv -Pattern '^COMPOSE_FILE=' -Quiet)) {
    # La carte graphique n'est plus accessible (pilote, réglage de Docker) : on repart sans elle.
    Write-Host "Démarrage impossible avec la carte graphique : nouvel essai sans elle." -ForegroundColor Yellow
    $sansGpu = (Get-Content -LiteralPath $cheminEnv -Encoding UTF8 | Where-Object { $_ -notmatch '^COMPOSE_FILE=' }) -join "`n"
    [System.IO.File]::WriteAllText($cheminEnv, $sansGpu + "`n", (New-Object System.Text.UTF8Encoding($false)))
    $env:COMPOSE_FILE = "docker-compose.yml"
    docker compose up -d --build
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

Write-Host ""
Write-Host "Application AO est prête : http://localhost:$port" -ForegroundColor Green
Start-Process "http://localhost:$port"
Read-Host "Appuyez sur Entrée pour fermer"
