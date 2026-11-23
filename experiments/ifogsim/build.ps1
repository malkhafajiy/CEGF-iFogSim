# Compiles iFogSim2 (src/) into build/ using the JDK found on PATH or in Program Files.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$jdk = (Get-Command javac -ErrorAction SilentlyContinue)
if ($jdk) { $javac = $jdk.Source } else { $javac = (Get-ChildItem "C:\Program Files\Microsoft\jdk-*\bin\javac.exe" | Select-Object -First 1).FullName }
$out = Join-Path $PSScriptRoot "build"
New-Item -ItemType Directory -Force $out | Out-Null
$cp = (Get-ChildItem "$root\jars" -Recurse -Filter *.jar | ForEach-Object FullName) -join ";"
$files = Get-ChildItem "$root\src" -Recurse -Filter *.java | ForEach-Object { '"' + ($_.FullName -replace '\\', '/') + '"' }
Set-Content "$out\files.txt" $files
& $javac -nowarn -encoding UTF-8 -cp $cp -d $out "@$out\files.txt" 2>&1 | Where-Object { $_ -match "error" } | ForEach-Object { Write-Host $_ }
Write-Host "classes: $((Get-ChildItem $out -Recurse -Filter *.class).Count)"
