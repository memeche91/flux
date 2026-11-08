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

$port = "8080"
$ligne = Select-String -LiteralPath $cheminEnv -Pattern '^APP_PORT=(\d+)' | Select-Object -First 1
if ($ligne) { $port = $ligne.Matches[0].Groups[1].Value }

Write-Host ""
Write-Host "Application AO est prête : http://localhost:$port" -ForegroundColor Green
Start-Process "http://localhost:$port"
Read-Host "Appuyez sur Entrée pour fermer"
