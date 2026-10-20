# Instala a skill context-vault (versão {{VERSION}}) a partir deste pacote, sem marketplace.
# Uso: .\install.ps1 -Agent <claude-code|codex|gemini|devin|agents|all> [-Project DIR] [-Force]
param(
    [Parameter(Mandatory = $true)][string]$Agent,
    [string]$Project = "",
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Skill = Join-Path $Here "context-vault"
if (-not (Test-Path (Join-Path $Skill "SKILL.md"))) {
    Write-Error "Pasta context-vault\SKILL.md não encontrada ao lado deste script."
    exit 1
}

$cli = Get-Command context-vault -ErrorAction SilentlyContinue
if ($cli) {
    $cvArgs = @("--output", "text", "install-skill", "--agent", $Agent, "--source", $Skill)
    if ($Project) { $cvArgs += @("--scope", "project", "--project-dir", $Project) }
    if ($Force) { $cvArgs += "--force" }
    & context-vault @cvArgs
    exit $LASTEXITCODE
}

function Get-Root([string]$name) {
    if ($Project) {
        switch ($name) {
            "claude-code" { return Join-Path $Project ".claude\skills" }
            { $_ -in "codex", "gemini", "devin", "agents" } { return Join-Path $Project ".agents\skills" }
        }
    } else {
        switch ($name) {
            "claude-code" { return Join-Path $HOME ".claude\skills" }
            { $_ -in "codex", "gemini", "devin", "agents" } { return Join-Path $HOME ".agents\skills" }
        }
    }
    throw "Agente desconhecido: $name"
}

$agents = if ($Agent -eq "all") { @("claude-code", "agents") } else { @($Agent) }
foreach ($name in $agents) {
    $root = Get-Root $name
    $dest = Join-Path $root "context-vault"
    if ((Test-Path $dest) -and -not $Force) {
        Write-Error "$dest já existe; use -Force para substituir."
        exit 11
    }
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    Copy-Item -Recurse $Skill $dest
    Write-Output "Skill instalada para $name em $dest"
}

Write-Output ""
Write-Output "Atenção: a CLI context-vault não foi encontrada no PATH. A skill depende dela."
$wheel = Get-ChildItem -Path (Join-Path $Here "wheels") -Filter *.whl -ErrorAction SilentlyContinue | Select-Object -First 1
if ($wheel) { Write-Output "Instale com: uv tool install $($wheel.FullName)   (ou pipx install ...)" }
else { Write-Output "Instale a partir do código-fonte: uv tool install <checkout do ContextVault>" }
