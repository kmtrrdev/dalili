# (Re)creates the Dalili Container App with its whole configuration: ingress, registry, scale, secrets, env vars.
# For when the app is lost or broken (its configuration wiped). The database, the registry and the environment are
# left as they are; the database keeps its data.
#
#   powershell -File scripts\azure_app.ps1
#
# The API keys come from .env (never printed). The database password exists only in Azure, so it is reset here to a
# new random one (never printed or saved) and given to the app; nothing else uses it. Then the app runs the latest
# image the Deploy workflow pushed, and the script waits until /api/health answers.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$rg = "dalili"; $app = "dalili"; $envName = "dalili-env"; $acr = "daliliacrkixdm4"; $pg = "dalili-db-kixdm4"

$keys = @{}
Get-Content (Join-Path $root ".env") | Where-Object { $_ -match "^\s*([A-Z_]+)\s*=\s*(.*)\s*$" } | ForEach-Object {
    $k, $v = $_ -split "=", 2; if ($v.Trim()) { $keys[$k.Trim()] = $v.Trim() }
}
foreach ($k in "AZURE_AI_KEY", "AZURE_AI_ENDPOINT") {
    if (-not $keys.ContainsKey($k)) { throw "$k is missing from .env" }
}

# A new database password: letters and digits only (safe in a URL), 32 characters.
$abc = [char[]]"ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$pw = -join ($bytes | ForEach-Object { $abc[$_ % $abc.Length] })
"Resetting the database admin password..."
az postgres flexible-server update -g $rg -n $pg --admin-password $pw --only-show-errors -o none
if ($LASTEXITCODE) { throw "Could not reset the database password" }
$admin = az postgres flexible-server show -g $rg -n $pg --query administratorLogin -o tsv
$pgHost = az postgres flexible-server show -g $rg -n $pg --query fullyQualifiedDomainName -o tsv

$secretMap = [ordered]@{ "SERPAPI_API_KEY" = "serpapi"; "ORS_API_KEY" = "ors"; "OPENTRIPMAP_API_KEY" = "opentripmap";
                         "GEOAPIFY_API_KEY" = "geoapify"; "AZURE_AI_KEY" = "azure-ai-key" }
$secrets = @("database-url=postgresql://${admin}:$pw@${pgHost}:5432/dalili?sslmode=require")
$envVars = @("DATABASE_URL=secretref:database-url")
foreach ($k in $secretMap.Keys) {
    if ($keys.ContainsKey($k)) { $secrets += "$($secretMap[$k])=$($keys[$k])"; $envVars += "$k=secretref:$($secretMap[$k])" }
}
foreach ($k in "AZURE_AI_ENDPOINT", "AZURE_AI_MODEL", "AZURE_AI_REASONING_EFFORT") {
    if ($keys.ContainsKey($k)) { $envVars += "$k=$($keys[$k])" }
}
# Public values (the site serves them anyway): the site's own address, search-engine verification and IndexNow.
$domain = az containerapp env show -g $rg -n $envName --query properties.defaultDomain -o tsv
$envVars += "PUBLIC_URL=https://$app.$domain"
$envVars += "GOOGLE_SITE_VERIFICATION=3gSSrIgPc5565d_NTDngWOCqggQxiqbkV1m7NySd25Y"
$indexNow = gh variable get INDEXNOW_KEY 2>$null
if ($indexNow) { $envVars += "INDEXNOW_KEY=$indexNow" }

$acrPw = az acr credential show -n $acr --query "passwords[0].value" -o tsv
"Creating the app..."
az containerapp create -g $rg -n $app --environment $envName `
    --image "$acr.azurecr.io/dalili:latest" `
    --registry-server "$acr.azurecr.io" --registry-username $acr --registry-password $acrPw `
    --target-port 8000 --ingress external --cpu 0.5 --memory 1.0Gi --min-replicas 1 --max-replicas 3 `
    --secrets $secrets --env-vars $envVars --only-show-errors -o none
if ($LASTEXITCODE) { throw "az containerapp create failed" }

$url = "https://" + (az containerapp show -g $rg -n $app --query properties.configuration.ingress.fqdn -o tsv)
for ($i = 0; $i -lt 40; $i++) {
    try { if ((Invoke-WebRequest "$url/api/health" -UseBasicParsing -TimeoutSec 15).StatusCode -eq 200) { "Live: $url"; exit 0 } } catch {}
    Start-Sleep 10
}
throw "The app did not answer at $url/api/health"
