param(
  [string]$PublishDir
)

# Build a WEB-ONLY publish directory for cadclaw.io from docs/.
#
# This is an allowlist build with fail-closed checks for destination scope,
# publication boundaries, machine-readable contracts, internal references,
# security policy, claim drift, and source/output integrity. It does not deploy.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $ScriptDir ".."))
$SiteRoot = Join-Path $RepoRoot "docs"
$ExpectedTarget = Join-Path (Join-Path (Join-Path $RepoRoot ".cloudflare") "pages") "cadclaw"
$ExpectedTarget = [System.IO.Path]::GetFullPath($ExpectedTarget)

if ([string]::IsNullOrWhiteSpace($PublishDir)) {
  $Target = $ExpectedTarget
} elseif ([System.IO.Path]::IsPathRooted($PublishDir)) {
  $Target = [System.IO.Path]::GetFullPath($PublishDir)
} else {
  $Target = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $PublishDir))
}

if (-not [string]::Equals($Target, $ExpectedTarget, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "Refusing alternate publish destination; expected .cloudflare/pages/cadclaw"
}

function Get-RelativePublishPath {
  param([string]$FullName)
  return $FullName.Substring($Target.Length).TrimStart([char[]]@('\', '/'))
}

function Assert-NoReparseAncestor {
  param([string]$Path)
  $current = [System.IO.DirectoryInfo](Split-Path -Parent $Path)
  while ($null -ne $current) {
    if ($current.Exists -and (($current.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)) {
      throw "Refusing publish destination beneath a reparse point"
    }
    if ([string]::Equals($current.FullName, $RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) { break }
    if (-not $current.FullName.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "Publish destination escaped the repository root"
    }
    $current = $current.Parent
  }
}

Assert-NoReparseAncestor $Target
if (Test-Path -LiteralPath $Target) {
  $targetItem = Get-Item -LiteralPath $Target -Force
  if (($targetItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "Refusing to clear a reparse-point publish destination"
  }
  Remove-Item -LiteralPath $Target -Recurse -Force
}
New-Item -ItemType Directory -Path $Target -Force | Out-Null

function Copy-PublicFile {
  param([string]$RelativePath)
  $Source = Join-Path $SiteRoot $RelativePath
  if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "Missing required public file: docs/$RelativePath"
  }
  $Dest = Join-Path $Target $RelativePath
  New-Item -ItemType Directory -Path (Split-Path -Parent $Dest) -Force | Out-Null
  Copy-Item -LiteralPath $Source -Destination $Dest -Force
}

function Copy-PublicDirectory {
  param([string]$RelativePath)
  $Source = Join-Path $SiteRoot $RelativePath
  if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
    throw "Missing required public directory: docs/$RelativePath"
  }
  $Dest = Join-Path $Target $RelativePath
  New-Item -ItemType Directory -Path $Dest -Force | Out-Null
  Get-ChildItem -LiteralPath $Source -Force | Copy-Item -Destination $Dest -Recurse -Force
}

# Paths are relative to docs/. Keep this list narrow and review additions.
$rootFiles = @(
  "index.html", "404.html", "styles.css", "_headers",
  "robots.txt", "sitemap.xml", "llms.txt",
  "CADCLAW_logo.jpg", "M3_FEA_LOAD_CASES.md",
  "_redirects",
  "dc64666f8b365e677b9a887307e73b38.txt"
)
foreach ($file in $rootFiles) { Copy-PublicFile $file }

$publicDirs = @("media", "ci-for-cad", ".well-known")
foreach ($directory in $publicDirs) { Copy-PublicDirectory $directory }

$publishFiles = @(Get-ChildItem -LiteralPath $Target -Recurse -File -Force)
if ($publishFiles.Count -eq 0) { throw "Publish output is empty" }

# No internal/build trees, CAD payloads, or files over the Pages asset cap.
$blockedPathPattern = '(^|[\\/])(fonts|publication|__pycache__|\.git)([\\/]|$)'
$blockedPaths = @($publishFiles | Where-Object { (Get-RelativePublishPath $_.FullName) -match $blockedPathPattern })
if ($blockedPaths.Count -gt 0) {
  throw "Blocked path reached publish output: $((@($blockedPaths | ForEach-Object { Get-RelativePublishPath $_.FullName }) | Sort-Object -Unique) -join ', ')"
}

# OS/editor junk must never ship. Thumbs.db in particular embeds thumbnails of
# every image that was in its folder, including ones since deleted, so serving
# it from a public origin discloses more than the folder's current contents.
# Git ignores these, but this build copies from the working tree, not from git.
$junkFilePattern = '(?i)^(Thumbs\.db|ehthumbs\.db|desktop\.ini|\.DS_Store)$'
$junkFiles = @($publishFiles | Where-Object { $_.Name -match $junkFilePattern })
if ($junkFiles.Count -gt 0) {
  throw "OS junk file reached publish output; delete it from docs/ and rebuild: $((@($junkFiles | ForEach-Object { Get-RelativePublishPath $_.FullName })) -join ', ')"
}

$cadExtensions = @(".stl", ".step", ".stp", ".3mf", ".f3d", ".f3z", ".sldprt", ".sldasm", ".ipt", ".iam", ".iges", ".igs", ".x_t", ".x_b", ".dwg", ".dxf")
$cadFiles = @($publishFiles | Where-Object { $cadExtensions -contains $_.Extension.ToLowerInvariant() })
if ($cadFiles.Count -gt 0) {
  throw "CAD file reached publish output: $((@($cadFiles | ForEach-Object { Get-RelativePublishPath $_.FullName })) -join ', ')"
}
$oversize = @($publishFiles | Where-Object { $_.Length -gt 25MB })
if ($oversize.Count -gt 0) {
  throw "File exceeds the 25 MiB asset limit: $((@($oversize | ForEach-Object { Get-RelativePublishPath $_.FullName })) -join ', ')"
}

# Scan likely-text surfaces. Report filenames only; never print matching content.
$textExtensions = @(".html", ".js", ".mjs", ".css", ".json", ".jsonl", ".txt", ".xml", ".svg", ".md")
$secretPatterns = @(
  'AKIA[0-9A-Z]{16}',
  'AIza[0-9A-Za-z_-]{30,}',
  '-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----',
  'gh[pousr]_[A-Za-z0-9_]{20,}',
  'glpat-[A-Za-z0-9_-]{20,}',
  'xox[baprs]-[A-Za-z0-9-]{20,}',
  'sk_live_[A-Za-z0-9]{20,}',
  'rk_live_[A-Za-z0-9]{20,}',
  'sk-(proj-)?[A-Za-z0-9_-]{32,}',
  '(?i)["'']?(api[_-]?key|client[_-]?secret|access[_-]?token|password)["'']?\s*[:=]\s*["''][^"''\r\n]{12,}["'']'
)
$secretHitFiles = @()
foreach ($file in ($publishFiles | Where-Object { $textExtensions -contains $_.Extension.ToLowerInvariant() })) {
  $content = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 -ErrorAction Stop
  $scan = [regex]::Replace($content, 'data:font/[^;]+;base64,[A-Za-z0-9+/=]+', 'data:font/stripped;base64,')
  foreach ($pattern in $secretPatterns) {
    if ($scan -cmatch $pattern) {
      $secretHitFiles += (Get-RelativePublishPath $file.FullName)
      break
    }
  }
}
if ($secretHitFiles.Count -gt 0) {
  throw "Secret-like pattern found; inspect these files without printing values: $((@($secretHitFiles) | Sort-Object -Unique) -join ', ')"
}

# Parse every JSON document before any higher-level contract checks.
$jsonFiles = @($publishFiles | Where-Object { $_.Extension.ToLowerInvariant() -eq ".json" })
foreach ($file in $jsonFiles) {
  try {
    $null = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch {
    throw "Invalid JSON: $(Get-RelativePublishPath $file.FullName)"
  }
}

# Parse sitemap and require the two locally published HTML routes.
try {
  [xml]$sitemapXml = Get-Content -LiteralPath (Join-Path $Target "sitemap.xml") -Raw -Encoding UTF8
} catch {
  throw "Invalid sitemap.xml"
}
$sitemapUrls = @($sitemapXml.SelectNodes("//*[local-name()='url']/*[local-name()='loc']") | ForEach-Object { $_.InnerText })
$requiredSitemapUrls = @("https://cadclaw.io/", "https://cadclaw.io/ci-for-cad/")
foreach ($requiredUrl in $requiredSitemapUrls) {
  if ($sitemapUrls -notcontains $requiredUrl) { throw "Sitemap is missing required URL: $requiredUrl" }
}
if ($sitemapUrls.Count -ne $requiredSitemapUrls.Count) {
  throw "Sitemap must enumerate exactly the two local HTML routes"
}

function Get-Sha256Base64 {
  param([string]$Text)
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try { $hash = $sha.ComputeHash($bytes) } finally { $sha.Dispose() }
  return [Convert]::ToBase64String($hash)
}

function Resolve-PublishReference {
  param(
    [System.IO.FileInfo]$HtmlFile,
    [string]$Reference
  )
  if ([string]::IsNullOrWhiteSpace($Reference)) { return $null }
  if ($Reference -match '^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)') { return $null }
  if ($Reference.StartsWith('#')) { return $null }

  $clean = [regex]::Split($Reference, '[?#]')[0]
  if ([string]::IsNullOrWhiteSpace($clean)) { return $null }
  $nativeClean = $clean.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
  if ($clean.StartsWith('/')) {
    $nativeClean = $nativeClean.TrimStart([char[]]@('\', '/'))
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $Target $nativeClean))
  } else {
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $HtmlFile.DirectoryName $nativeClean))
  }

  $targetPrefix = $Target.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
  if (-not [string]::Equals($candidate, $Target, [System.StringComparison]::OrdinalIgnoreCase) -and
      -not $candidate.StartsWith($targetPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Local reference escapes publish output in $(Get-RelativePublishPath $HtmlFile.FullName)"
  }

  if ($clean.EndsWith('/') -or (Test-Path -LiteralPath $candidate -PathType Container)) {
    $candidate = Join-Path $candidate "index.html"
  }
  return $candidate
}

# Validate HTML, same-document anchors, local file references, JSON-LD, and CSP hashes.
$headersText = Get-Content -LiteralPath (Join-Path $Target "_headers") -Raw -Encoding UTF8
$htmlFiles = @($publishFiles | Where-Object { $_.Extension.ToLowerInvariant() -eq ".html" })
$linkCount = 0
$jsonLdCount = 0
$jsonLdHashes = @()
$attributePattern = '(?i)\b(?:href|src)\s*=\s*["'']([^"'']+)["'']'
$jsonLdPattern = '(?is)<script\s+type=["'']application/ld\+json["'']>([\s\S]*?)</script>'
foreach ($htmlFile in $htmlFiles) {
  $raw = Get-Content -LiteralPath $htmlFile.FullName -Raw -Encoding UTF8
  if ($raw -match '(?i)\son[a-z]+\s*=') {
    throw "Inline event handler is forbidden: $(Get-RelativePublishPath $htmlFile.FullName)"
  }
  if ($raw -match '(?i)javascript:') {
    throw "javascript: reference is forbidden: $(Get-RelativePublishPath $htmlFile.FullName)"
  }

  $ids = @{}
  foreach ($idMatch in [regex]::Matches($raw, '(?i)\bid\s*=\s*["'']([^"'']+)["'']')) {
    $ids[$idMatch.Groups[1].Value] = $true
  }
  foreach ($attrMatch in [regex]::Matches($raw, $attributePattern)) {
    $reference = $attrMatch.Groups[1].Value
    $linkCount += 1
    if ($reference.StartsWith('#') -and $reference.Length -gt 1) {
      $anchor = $reference.Substring(1)
      if (-not $ids.ContainsKey($anchor)) {
        throw "Missing same-page anchor in $(Get-RelativePublishPath $htmlFile.FullName): #$anchor"
      }
      continue
    }
    $resolved = Resolve-PublishReference -HtmlFile $htmlFile -Reference $reference
    if ($null -ne $resolved -and -not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
      throw "Broken local reference in $(Get-RelativePublishPath $htmlFile.FullName): $reference"
    }
  }

  $allScriptCount = [regex]::Matches($raw, '(?is)<script\b').Count
  $jsonLdMatches = [regex]::Matches($raw, $jsonLdPattern)
  if ($allScriptCount -ne $jsonLdMatches.Count) {
    throw "Only application/ld+json script blocks are permitted: $(Get-RelativePublishPath $htmlFile.FullName)"
  }
  foreach ($jsonLdMatch in $jsonLdMatches) {
    $jsonLd = $jsonLdMatch.Groups[1].Value
    try { $null = $jsonLd | ConvertFrom-Json } catch {
      throw "Invalid embedded JSON-LD: $(Get-RelativePublishPath $htmlFile.FullName)"
    }
    $canonicalJsonLd = $jsonLd -replace "`r`n", "`n" -replace "`r", "`n"
    $hashToken = "sha256-$(Get-Sha256Base64 $canonicalJsonLd)"
    if ($headersText -notmatch [regex]::Escape("'$hashToken'")) {
      throw "CSP is missing a JSON-LD hash for $(Get-RelativePublishPath $htmlFile.FullName)"
    }
    $jsonLdHashes += $hashToken
    $jsonLdCount += 1
  }
}

if ($jsonLdCount -lt 1) { throw "No JSON-LD found in published HTML" }
if ($headersText -match "script-src\s+'none'" -or $headersText -match "script-src[^;]*'unsafe-inline'" -or $headersText -match "script-src[^;]*'unsafe-eval'") {
  throw "CSP script policy must allow only reviewed JSON-LD hashes"
}
$cspHashMatches = @([regex]::Matches($headersText, "'sha256-[A-Za-z0-9+/=]+'") | ForEach-Object { $_.Value.Trim("'") } | Sort-Object -Unique)
$expectedHashes = @($jsonLdHashes | Sort-Object -Unique)
if ($cspHashMatches.Count -ne $expectedHashes.Count) { throw "CSP contains stale or missing script hashes" }
foreach ($hash in $expectedHashes) {
  if ($cspHashMatches -notcontains $hash) { throw "CSP hash set does not match embedded JSON-LD" }
}

if ((Get-Content -LiteralPath (Join-Path $Target "styles.css") -Raw -Encoding UTF8) -match '(?i)fonts\.googleapis\.com|fonts\.gstatic\.com') {
  throw "Third-party Google Fonts reference is not permitted"
}

# Keep package/version/tool declarations derived from source and mutually consistent.
$projectText = Get-Content -LiteralPath (Join-Path $RepoRoot "pyproject.toml") -Raw -Encoding UTF8
$versionMatch = [regex]::Match($projectText, '(?m)^version\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) { throw "Could not derive package version from pyproject.toml" }
$packageVersion = $versionMatch.Groups[1].Value
$homeText = Get-Content -LiteralPath (Join-Path $Target "index.html") -Raw -Encoding UTF8
$articleText = Get-Content -LiteralPath (Join-Path $Target "ci-for-cad/index.html") -Raw -Encoding UTF8
$llmsText = Get-Content -LiteralPath (Join-Path $Target "llms.txt") -Raw -Encoding UTF8
$manifestPath = Join-Path $Target ".well-known/mcp-manifest.json"
$manifestText = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8
$manifest = $manifestText | ConvertFrom-Json

if ($homeText -notmatch [regex]::Escape('"softwareVersion": "' + $packageVersion + '"')) { throw "Homepage softwareVersion is stale" }
if ($articleText -notmatch [regex]::Escape('"softwareVersion": "' + $packageVersion + '"')) { throw "Article softwareVersion is stale" }
if ($articleText -notmatch [regex]::Escape('published package version is ' + $packageVersion)) { throw "Article narrative version is stale" }
if ($llmsText -notmatch [regex]::Escape('Current published version: ' + $packageVersion)) { throw "llms.txt version is stale" }
$packageRecord = @($manifest.related_packages | Where-Object { $_.name -eq "cadclaw" })
if ($packageRecord.Count -ne 1 -or $packageRecord[0].version -ne $packageVersion) { throw "MCP discovery package version is stale" }

$serverText = Get-Content -LiteralPath (Join-Path $RepoRoot "cadclaw_mcp/server.py") -Raw -Encoding UTF8
$definitionNames = @([regex]::Matches($serverText, '(?m)^\s{8}"name":\s*"([^"]+)"') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
$handlerNames = @([regex]::Matches($serverText, '(?m)^\s{4}"([^"]+)":\s*lambda\s+args:') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
if ($definitionNames.Count -ne 24 -or $handlerNames.Count -ne 24) { throw "Expected 24 declared MCP tools and 24 handlers" }
if (($definitionNames -join "`n") -ne ($handlerNames -join "`n")) { throw "MCP tool declarations and handlers differ" }
$assembleCount = @($handlerNames | Where-Object { $_.StartsWith("assemble_") }).Count
if ($assembleCount -ne 6) { throw "Expected six assemble_* MCP tools" }
foreach ($surface in @($homeText, $articleText, $llmsText, $manifestText)) {
  if ($surface -notmatch '\b24\b') { throw "A public agent surface is missing the derived 24-tool declaration" }
}

if ($manifest.status -ne "experimental-nonstandard-static-discovery") { throw "MCP discovery status must remain experimental and non-standard" }
if (@($manifest.tools).Count -ne 0) { throw "Static site must not advertise hosted MCP tools" }
if ($manifestText -notmatch 'not a security sandbox') { throw "MCP discovery must disclose the local permission boundary" }

# AI-use policy, security metadata, native 404, and stale-claim tripwires.
$robotsText = Get-Content -LiteralPath (Join-Path $Target "robots.txt") -Raw -Encoding UTF8
if ([regex]::Matches($robotsText, '(?im)^User-agent:\s*\*$').Count -ne 1) { throw "robots.txt must contain one global crawler group" }
if ($robotsText -notmatch '(?im)^Content-Signal:\s*search=yes,\s*ai-input=yes,\s*ai-train=no\s*$') { throw "robots.txt Content-Signal policy is missing or inconsistent" }
if ($headersText -notmatch '(?im)^\s*Content-Signal:\s*search=yes,\s*ai-input=yes,\s*ai-train=no\s*$') { throw "Origin Content-Signal header policy is missing or inconsistent" }
$requiredHeaders = @("X-Content-Type-Options", "Referrer-Policy", "X-Frame-Options", "Permissions-Policy", "Strict-Transport-Security", "Content-Security-Policy")
foreach ($headerName in $requiredHeaders) {
  if ($headersText -notmatch ("(?im)^\s*" + [regex]::Escape($headerName) + ":")) { throw "Missing required security header: $headerName" }
}

$securityText = Get-Content -LiteralPath (Join-Path $Target ".well-known/security.txt") -Raw -Encoding UTF8
$expiresMatch = [regex]::Match($securityText, '(?im)^Expires:\s*(\S+)\s*$')
if (-not $expiresMatch.Success) { throw "security.txt is missing Expires" }
try { $securityExpiry = [DateTimeOffset]::Parse($expiresMatch.Groups[1].Value) } catch { throw "security.txt Expires is invalid" }
if ($securityExpiry -le [DateTimeOffset]::UtcNow.AddDays(30)) { throw "security.txt expires in 30 days or less" }

$notFoundText = Get-Content -LiteralPath (Join-Path $Target "404.html") -Raw -Encoding UTF8
if ($notFoundText -notmatch '(?i)<meta\s+name="robots"\s+content="noindex') { throw "404.html must be noindex" }
$redirectsText = Get-Content -LiteralPath (Join-Path $Target "_redirects") -Raw -Encoding UTF8
if ($redirectsText -match '(?m)^\s*/\*\s+') { throw "Catch-all redirect would defeat native 404 behavior" }

$claimSurfaces = $homeText + "`n" + $articleText + "`n" + $llmsText + "`n" + $manifestText
$blockedClaimPatterns = @(
  '(?i)first tool-independent benchmark',
  '(?i)from one picture',
  '(?i)caught\s+53\s+solid-solid',
  '(?i)70\s*(?:MB|&nbsp;MB)\s+to\s+13\s*(?:MB|&nbsp;MB)',
  '(?i)validated\s+150\+',
  '(?i)that single finding paid for',
  '(?i)positive expected value',
  '(?i)test runner is sandboxed',
  '(?i)every CAD pull request triggers'
)
foreach ($pattern in $blockedClaimPatterns) {
  if ($claimSurfaces -match $pattern) { throw "Blocked stale public-claim pattern remains" }
}

# Verify every published byte matches its allowlisted source byte.
$hashCount = 0
foreach ($outputFile in $publishFiles) {
  $relative = Get-RelativePublishPath $outputFile.FullName
  $sourceFile = Join-Path $SiteRoot $relative
  if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) { throw "Output lacks a source counterpart: $relative" }
  $sourceHash = (Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256).Hash
  $outputHash = (Get-FileHash -LiteralPath $outputFile.FullName -Algorithm SHA256).Hash
  if ($sourceHash -ne $outputHash) { throw "Source/output hash mismatch: $relative" }
  $hashCount += 1
}

$bytes = ($publishFiles | Measure-Object -Property Length -Sum).Sum
Write-Output "cadclaw publish dir ready: $Target"
Write-Output "Files: $($publishFiles.Count)"
Write-Output "Bytes: $bytes"
Write-Output "HTML: $($htmlFiles.Count)"
Write-Output "JSON: $($jsonFiles.Count)"
Write-Output "JSON-LD: $jsonLdCount"
Write-Output "Links checked: $linkCount"
Write-Output "Sitemap URLs: $($sitemapUrls.Count)"
Write-Output "MCP tools: $($handlerNames.Count) (assemble_*: $assembleCount)"
Write-Output "Version: $packageVersion"
Write-Output "Source/output hashes: $hashCount/$($publishFiles.Count)"
