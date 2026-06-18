param(
  [string]$PublishDir
)

# Build a WEB-ONLY publish directory for cadclaw.io from docs/.
#
# Allowlist, not denylist: only the files/dirs named below (under docs/) are
# copied, with the docs/ prefix stripped so index.html serves at the site root.
# Licensed display fonts (docs/fonts/) and internal editorial notes
# (docs/publication/) are gitignored and never referenced here, so they cannot
# reach the deploy. The fail-loud checks abort the build if a blocked dir, CAD
# file, oversized file, or secret-looking string ever lands in the publish dir.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = [System.IO.Path]::GetFullPath((Join-Path $ScriptDir ".."))
$SiteRoot  = Join-Path $RepoRoot "docs"

if ([string]::IsNullOrWhiteSpace($PublishDir)) {
  $PublishDir = Join-Path $RepoRoot ".cloudflare\pages\cadclaw"
}
$Target = [System.IO.Path]::GetFullPath($PublishDir)
if (-not $Target.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "Refusing to write outside project root: $Target"
}
if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Recurse -Force }
New-Item -ItemType Directory -Path $Target -Force | Out-Null

function Copy-PublicFile {
  param([string]$RelativePath)   # relative to docs/
  $Source = Join-Path $SiteRoot $RelativePath
  if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { throw "Missing public file: docs/$RelativePath" }
  $Dest = Join-Path $Target $RelativePath
  New-Item -ItemType Directory -Path (Split-Path -Parent $Dest) -Force | Out-Null
  Copy-Item -LiteralPath $Source -Destination $Dest -Force
}

function Copy-PublicDirectory {
  param([string]$RelativePath)   # relative to docs/
  $Source = Join-Path $SiteRoot $RelativePath
  if (-not (Test-Path -LiteralPath $Source -PathType Container)) { throw "Missing public directory: docs/$RelativePath" }
  $Dest = Join-Path $Target $RelativePath
  New-Item -ItemType Directory -Path $Dest -Force | Out-Null
  Copy-Item -Path (Join-Path $Source "*") -Destination $Dest -Recurse -Force
}

# --- ALLOWLIST (paths relative to docs/) ----------------------------------
$rootFiles = @(
  "index.html", "styles.css",
  "robots.txt", "sitemap.xml", "llms.txt",
  "CADCLAW_logo.jpg", "M3_FEA_LOAD_CASES.md",
  "_redirects",                            # /benchmark/* -> marb.cadclaw.io 301s
  "dc64666f8b365e677b9a887307e73b38.txt"   # IndexNow / site-verification key
)
foreach ($f in $rootFiles) { Copy-PublicFile $f }

$publicDirs = @("media", "ci-for-cad", ".well-known")
foreach ($d in $publicDirs) { Copy-PublicDirectory $d }

# --- FAIL-LOUD TRIPWIRES ---------------------------------------------------
$publishFiles = Get-ChildItem -LiteralPath $Target -Recurse -File

# 1. No licensed/internal/build dirs in the output.
$blocked = @("fonts", "publication", "__pycache__", ".git")
foreach ($b in $blocked) {
  if (Test-Path -LiteralPath (Join-Path $Target $b)) { throw "Blocked path reached publish dir: $b" }
}

# 2. No CAD, nothing over Cloudflare's 25 MiB cap.
$cadExt = @(".stl",".step",".stp",".3mf",".f3d",".f3z",".sldprt",".sldasm",".ipt",".iam",".iges",".igs",".x_t",".x_b",".dwg",".dxf")
$cad = $publishFiles | Where-Object { $cadExt -contains $_.Extension.ToLower() }
if ($cad) { throw "CAD file(s) reached the publish dir: $($cad.FullName -join ', ')" }
$big = $publishFiles | Where-Object { $_.Length -gt 25MB }
if ($big) { throw "File(s) over Cloudflare's 25 MiB limit: $(($big | ForEach-Object { $_.Name }) -join ', ')" }

# 3. No secret-looking strings (scan text files; strip base64 font data URIs first).
$textExt = @(".html",".js",".mjs",".css",".json",".jsonl",".txt",".xml",".svg",".md")
$secretPatterns = @(
  "AKIA[0-9A-Z]{16}",
  "-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----",
  "ghp_[A-Za-z0-9_]{20,}",
  "xox[baprs]-[A-Za-z0-9-]{20,}",
  "sk_live_[A-Za-z0-9]{20,}",
  "sk-[A-Za-z0-9]{32,}"
)
$hits = @()
foreach ($file in ($publishFiles | Where-Object { $textExt -contains $_.Extension.ToLower() })) {
  $content = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction SilentlyContinue
  if ($null -eq $content) { continue }
  $scan = [regex]::Replace($content, "data:font/[^;]+;base64,[A-Za-z0-9+/=]+", "data:font/stripped;base64,")
  foreach ($p in $secretPatterns) { if ($scan -match $p) { $hits += $file.FullName; break } }
}
if ($hits.Count -gt 0) { throw "Secret-like pattern(s) found in: $(($hits | Sort-Object -Unique) -join ', ')" }

# --- REPORT ----------------------------------------------------------------
$bytes = ($publishFiles | Measure-Object -Property Length -Sum).Sum
Write-Output "cadclaw publish dir ready: $Target"
Write-Output "Files: $($publishFiles.Count)"
Write-Output "Bytes: $bytes"
