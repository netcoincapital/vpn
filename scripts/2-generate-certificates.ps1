# Generate OpenVPN server certificates with Easy-RSA - run as Administrator

$ErrorActionPreference = "Stop"
$openvpnBase = "C:\Program Files\OpenVPN"
$configPath = "$openvpnBase\config"
$projectEasyRsa = Join-Path $PSScriptRoot "..\easy-rsa"

$easyRsaPaths = @(
    "$openvpnBase\easy-rsa",
    "${env:ProgramFiles(x86)}\OpenVPN\easy-rsa",
    "$openvpnBase\sample-config\easy-rsa",
    "$openvpnBase\bin\easy-rsa",
    $projectEasyRsa
)
$easyRsaPath = $null
foreach ($p in $easyRsaPaths) {
    if (Test-Path $p) { $easyRsaPath = $p; break }
}
# Search under OpenVPN for easyrsa.bat or easyrsa
if (-not $easyRsaPath -and (Test-Path $openvpnBase)) {
    $found = Get-ChildItem -Path $openvpnBase -Recurse -Filter "easyrsa.bat" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $easyRsaPath = $found.DirectoryName }
    if (-not $found) {
        $found = Get-ChildItem -Path $openvpnBase -Recurse -Filter "easyrsa" -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { $easyRsaPath = $found.DirectoryName }
    }
}
# Also check project folder e:\config vpn\easy-rsa
if (-not $easyRsaPath -and (Test-Path $projectEasyRsa)) {
    $easyRsaPath = $projectEasyRsa
}

if (-not $easyRsaPath) {
    # Fallback: try OpenSSL (bundled with OpenVPN or in PATH)
    $openssl = $null
    if (Test-Path "$openvpnBase\bin\openssl.exe") { $openssl = "$openvpnBase\bin\openssl.exe" }
    elseif (Get-Command openssl -ErrorAction SilentlyContinue) { $openssl = "openssl" }
    if ($openssl -and (Test-Path $configPath)) {
        Write-Host "Using OpenSSL to generate certificates..."
        $workDir = Join-Path $env:TEMP "openvpn-certs"
        if (Test-Path $workDir) { Remove-Item $workDir -Recurse -Force }
        New-Item -ItemType Directory -Path $workDir -Force | Out-Null
        Push-Location $workDir
        try {
            & $openssl genrsa -out ca.key 2048 2>$null
            & $openssl req -new -x509 -days 3650 -key ca.key -out ca.crt -subj "/CN=OpenVPN-CA" 2>$null
            & $openssl genrsa -out server.key 2048 2>$null
            & $openssl req -new -key server.key -out server.csr -subj "/CN=server" 2>$null
            & $openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 3650 2>$null
            & $openssl dhparam -out dh.pem 2048 2>$null
            Copy-Item ca.crt, server.crt, server.key, dh.pem -Destination $configPath -Force
            Write-Host "Certificates saved to $configPath"
            Write-Host "Copy ca.crt to client folder for users."
        } finally {
            Pop-Location
            Remove-Item $workDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        exit 0
    }
    Write-Host "Easy-RSA not found and OpenSSL not available."
    Write-Host "Download Easy-RSA from: https://github.com/OpenVPN/easy-rsa/releases (e.g. EasyRSA-3.1.x-win64.zip)"
    Write-Host "Extract the contents to: e:\config vpn\easy-rsa"
    Write-Host "Then run this script again."
    exit 1
}

Push-Location $easyRsaPath

try {
    $easyrsaExe = $null
    $useBatch = $false
    if (Test-Path ".\EasyRSA-Start.bat") {
        $easyrsaExe = ".\EasyRSA-Start.bat"
        $useBatch = $true
    }
    elseif (Test-Path ".\easyrsa.bat") { $easyrsaExe = ".\easyrsa.bat" }
    elseif (Test-Path ".\easyrsa") { $easyrsaExe = ".\easyrsa" }
    if ($easyrsaExe) {
        Write-Host "Generating certificates with Easy-RSA 3..."
        if ($useBatch) { $env:EASYRSA_BATCH = "1" }
        & $easyrsaExe init-pki 2>&1 | Out-Null
        & $easyrsaExe build-ca nopass 2>&1 | Out-Null
        & $easyrsaExe gen-req server nopass 2>&1 | Out-Null
        & $easyrsaExe sign-req server server 2>&1 | Out-Null
        & $easyrsaExe gen-dh 2>&1 | Out-Null

        $pki = ".\pki"
        if (-not (Test-Path "$pki\ca.crt")) {
            Write-Host "Easy-RSA did not create pki files. Trying without suppressing output..."
            $env:EASYRSA_BATCH = "1"
            & $easyrsaExe init-pki
            & $easyrsaExe build-ca nopass
            & $easyrsaExe gen-req server nopass
            & $easyrsaExe sign-req server server
            & $easyrsaExe gen-dh
        }
        if (Test-Path "$pki\ca.crt") {
            Copy-Item "$pki\ca.crt" $configPath -Force
            Copy-Item "$pki\issued\server.crt" $configPath -Force
            Copy-Item "$pki\private\server.key" $configPath -Force
            Copy-Item "$pki\dh.pem" $configPath -Force
            Write-Host "Certificates saved to $configPath"
            Write-Host "Copy ca.crt to client folder for users."
        } else {
            Write-Host "pki folder or ca.crt still missing. Run Easy-RSA manually from: $easyRsaPath"
            Write-Host "Commands: EasyRSA-Start.bat init-pki, build-ca nopass, gen-req server nopass, sign-req server server, gen-dh"
        }
    }
    elseif (Test-Path "vars.bat") {
        Write-Host "Generating certificates (legacy format)..."
        cmd /c "vars.bat && clean-all && build-ca.bat nopass && build-key-server.bat server && build-dh.bat"
        Copy-Item "keys\ca.crt", "keys\server.crt", "keys\server.key", "keys\dh2048.pem" -Destination $configPath -Force
        Rename-Item (Join-Path $configPath "dh2048.pem") "dh.pem" -ErrorAction SilentlyContinue
        Write-Host "Certificates saved to $configPath"
    }
    else {
        Write-Host "Easy-RSA structure not recognized. Run manually in CMD:"
        Write-Host "  cd `"$easyRsaPath`""
        Write-Host "  .\easyrsa init-pki"
        Write-Host "  .\easyrsa build-ca nopass"
        Write-Host "  .\easyrsa gen-req server nopass"
        Write-Host "  .\easyrsa sign-req server server"
        Write-Host "  .\easyrsa gen-dh"
        Write-Host "Then copy pki\ca.crt, pki\issued\server.crt, pki\private\server.key, pki\dh.pem to $configPath"
    }
} finally {
    Pop-Location
}
