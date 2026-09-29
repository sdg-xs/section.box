param(
    [string]$KitRoot = 'C:\kit-app-template\_build\windows-x86_64\release\kit'
)
$ErrorActionPreference = 'Stop'
$output = Join-Path $PSScriptRoot 'verification'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$cache = Join-Path (Split-Path $KitRoot -Parent) 'extscache'
& (Join-Path $KitRoot 'kit.exe') (Join-Path $PSScriptRoot 'tests\section_box_test.kit') `
    --ext-folder $cache --ext-folder (Split-Path $PSScriptRoot -Parent) `
    --enable omni.kit.ui_test `
    --exec (Join-Path $PSScriptRoot 'tests\verify_pointer.py') `
    "--/app/settings/persistent=false" "--/app/userConfigPath=$output/pointer-user.config.json" `
    "--/app/cachePath=$output/pointer-cache" "--/app/dataPath=$output/pointer-data"
exit $LASTEXITCODE
