# Generate rsshelp_light.png and rsshelp_dark.png for astrbot_plugin_rsshub
# Usage:
#   .\gen_rsshelp.ps1
#   .\gen_rsshelp.ps1 --theme light
#   .\gen_rsshelp.ps1 --theme dark

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PluginDir = Split-Path -Parent $ScriptDir

Push-Location $PluginDir

if ($args.Length -eq 0) {
    Write-Host "Generating rsshelp_light.png and rsshelp_dark.png..."
} else {
    Write-Host "Generating rsshelp image..."
}
python3 scripts/generate_rsshelp_image.py @args

Pop-Location
