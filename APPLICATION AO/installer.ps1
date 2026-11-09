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
    $contenuEnv = $contenuEnv.TrimEnd() + "`n`n# Assistant IA local`nIA_MODELE=qwen3.5:9b`n"
}
$memoireGo = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
if ($memoireGo -lt 16 -and $contenuEnv -match '(?m)^IA_MODELE=qwen3\.5:9b') {
    $contenuEnv = $contenuEnv -replace '(?m)^IA_MODELE=qwen3\.5:9b', 'IA_MODELE=qwen3.5:4b'
    Write-Host "Mémoire : $memoireGo Go. Modèle léger choisi pour l'assistant (qwen3.5:4b)."
} else {
    Write-Host "Mémoire : $memoireGo Go."
}
if ((Get-Command nvidia-smi -ErrorAction SilentlyContinue) -and $contenuEnv -notmatch '(?m)^COMPOSE_FILE=') {
    $contenuEnv = $contenuEnv.TrimEnd() + "`nCOMPOSE_FILE=docker-compose.yml;docker-compose.gpu.yml`n"
    Write-Host "Carte graphique NVIDIA détectée : l'assistant l'utilisera."
}
[System.IO.File]::WriteAllText($cheminEnv, $contenuEnv, (New-Object System.Text.UTF8Encoding($false)))

Ecrire-Etape "Construction et démarrage (le premier lancement peut prendre 5 à 10 minutes)"
docker compose up -d --build
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
