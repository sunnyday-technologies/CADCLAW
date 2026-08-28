[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CohortId,

    [Parameter()]
    [string]$TargetCommit,

    [Parameter()]
    [string]$PythonExecutable
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$qualificationManifestVersion = "nist-ap242-qualification-manifest.v1"
$qualificationReportSchemaVersion = "0.7"
$qualificationRulesSchemaVersion = "0.9"
$qualificationGateSpecVersion = "0.12.0"
$qualificationExpectedClasses = @(
    "dimensions",
    "geometric_tolerances",
    "datums"
)
$qualificationRepositoryUrl = "https://github.com/sunnyday-technologies/CADCLAW"

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    $qualificationUtf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $qualificationUtf8)
}

function Get-Sha256Lower {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-RequiredProperty {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Object,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    $qualificationProperty = $Object.PSObject.Properties[$Name]
    if ($null -eq $qualificationProperty) {
        throw "$Context is missing required property '$Name'"
    }
    return $qualificationProperty.Value
}

function Assert-Equal {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Actual,

        [Parameter(Mandatory = $true)]
        [object]$Expected,

        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    if ([string]$Actual -cne [string]$Expected) {
        throw "$Context expected '$Expected' but observed '$Actual'"
    }
}

function Assert-CleanExactMainPreflight {
    param(
        [Parameter(Mandatory = $true)]
        [string]$HeadCommit,

        [Parameter(Mandatory = $true)]
        [string]$OriginMainCommit,

        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$WorktreeStatus
    )

    if ($HeadCommit -cne $OriginMainCommit) {
        throw "caller HEAD must equal the freshly fetched origin/main commit"
    }
    if ($WorktreeStatus.Count -ne 0) {
        throw "caller worktree must be clean, including untracked non-ignored files"
    }
}

function Assert-NoReparsePointInExistingAncestors {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    $qualificationCandidate = [System.IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrEmpty($qualificationCandidate)) {
        if (Test-Path -LiteralPath $qualificationCandidate) {
            $qualificationItem = Get-Item -LiteralPath $qualificationCandidate -Force
            $qualificationIsReparse = (
                ($qualificationItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
            )
            $qualificationLinkType = $qualificationItem.PSObject.Properties["LinkType"]
            if (
                $qualificationIsReparse -or
                ($null -ne $qualificationLinkType -and -not [string]::IsNullOrEmpty([string]$qualificationLinkType.Value))
            ) {
                throw "$Context has a symlink or reparse point in its existing ancestors"
            }
        }
        $qualificationParent = [System.IO.Directory]::GetParent($qualificationCandidate)
        if ($null -eq $qualificationParent) {
            break
        }
        $qualificationCandidate = $qualificationParent.FullName
    }
}

function Test-ForbiddenEvidenceKeyName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $qualificationNormalizedName = [regex]::Replace(
        $Name,
        '([a-z0-9])([A-Z])',
        '$1_$2'
    ).ToLowerInvariant()
    $qualificationNormalizedName = [regex]::Replace(
        $qualificationNormalizedName,
        '[^a-z0-9]+',
        '_'
    ).Trim('_')
    $qualificationExactForbidden = @(
        "cwd",
        "env",
        "environment",
        "executable",
        "home",
        "host",
        "hostname",
        "user",
        "username",
        "working_directory"
    )
    if ($qualificationExactForbidden -ccontains $qualificationNormalizedName) {
        return $true
    }
    if (
        $qualificationNormalizedName -match '(^|_)(token|tokens|password|passwords|auth|authentication|authorization|credential|credentials|secret|secrets)(_|$)' -or
        $qualificationNormalizedName -match '(^|_)api_?key(_|$)' -or
        $qualificationNormalizedName -match '(^|_)private_?key(_|$)'
    ) {
        return $true
    }
    return $false
}

function Assert-SanitizedEvidenceValue {
    param(
        [AllowNull()]
        [object]$Value,

        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    if ($null -eq $Value) {
        return
    }
    if ($Value -is [string]) {
        $qualificationText = [string]$Value
        $qualificationWindowsAbsolute = '(?i)(?<![a-z0-9])[a-z]:[\\/]'
        $qualificationUncAbsolute = '(?<![\\])\\\\[^\\/\s]+[\\/][^\\/\s]+'
        $qualificationPosixAbsolute = '(?<![a-z0-9:/])/(?!/)(?:[^/\s]+(?:/|$))'
        if (
            $qualificationText -match '(?i)\bfile://' -or
            $qualificationText -match $qualificationWindowsAbsolute -or
            $qualificationText -match $qualificationUncAbsolute -or
            $qualificationText -match $qualificationPosixAbsolute
        ) {
            throw "$Context contains an absolute local path"
        }
        return
    }
    if ($Value -is [System.Collections.IDictionary]) {
        foreach ($qualificationKey in $Value.Keys) {
            $qualificationKeyText = [string]$qualificationKey
            if (Test-ForbiddenEvidenceKeyName $qualificationKeyText) {
                throw "$Context contains forbidden sensitive key name '$qualificationKeyText'"
            }
            Assert-SanitizedEvidenceValue -Value $Value[$qualificationKey] -Context "$Context.$qualificationKeyText"
        }
        return
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $qualificationIndex = 0
        foreach ($qualificationChild in $Value) {
            Assert-SanitizedEvidenceValue -Value $qualificationChild -Context "$Context[$qualificationIndex]"
            $qualificationIndex += 1
        }
        return
    }
    if ($Value -is [pscustomobject]) {
        foreach ($qualificationProperty in $Value.PSObject.Properties) {
            if (Test-ForbiddenEvidenceKeyName $qualificationProperty.Name) {
                throw "$Context contains forbidden sensitive key name '$($qualificationProperty.Name)'"
            }
            Assert-SanitizedEvidenceValue -Value $qualificationProperty.Value -Context "$Context.$($qualificationProperty.Name)"
        }
    }
}

function ConvertTo-SanitizedArgv {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$PathReplacements
    )

    $qualificationSanitized = @("<python-executable>")
    foreach ($qualificationArgument in $Arguments) {
        if ($PathReplacements.Contains($qualificationArgument)) {
            $qualificationSanitized += [string]$PathReplacements[$qualificationArgument]
        }
        else {
            $qualificationSanitized += $qualificationArgument
        }
    }
    Assert-SanitizedEvidenceValue -Value $qualificationSanitized -Context "sanitized argv"
    return $qualificationSanitized
}

function Assert-SafeRelativeArtifactPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    $qualificationNormalized = $Path.Replace("\", "/")
    if (
        [System.IO.Path]::IsPathRooted($Path) -or
        $qualificationNormalized.StartsWith("../") -or
        $qualificationNormalized.Contains("/../") -or
        $qualificationNormalized.Contains(":")
    ) {
        throw "$Context contains a non-portable or absolute path"
    }
}

function Read-ValidatedJsonReport {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Context did not produce a JSON report"
    }
    try {
        return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    }
    catch {
        throw "$Context report is not valid JSON"
    }
}

function Assert-NoSensitiveRuntimeFields {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Object,

        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    Assert-SanitizedEvidenceValue -Value $Object -Context $Context
}

function Assert-PmiReport {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Report,

        [Parameter(Mandatory = $true)]
        [string]$FixturePath,

        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$ExpectedCounts
    )

    Assert-Equal (Get-RequiredProperty $Report "schema_version" "PMI report") $qualificationReportSchemaVersion "PMI report schema"
    Assert-Equal (Get-RequiredProperty $Report "overall" "PMI report") "pass" "PMI report outcome"
    $qualificationMeta = Get-RequiredProperty $Report "meta" "PMI report"
    Assert-Equal (Get-RequiredProperty $qualificationMeta "gate" "PMI report meta") "PMI_PRESENT_SEMANTIC" "PMI gate"
    Assert-Equal (Get-RequiredProperty $qualificationMeta "applicability" "PMI report meta") "applicable" "PMI applicability"
    Assert-Equal (Get-RequiredProperty $qualificationMeta "scope" "PMI report meta") "semantic_only" "PMI scope"
    Assert-Equal (Get-RequiredProperty $qualificationMeta "gate_spec_version" "PMI report meta") $qualificationGateSpecVersion "PMI gate-spec version"

    $qualificationRecordedStep = [string](Get-RequiredProperty $qualificationMeta "step" "PMI report meta")
    Assert-SafeRelativeArtifactPath $qualificationRecordedStep "PMI input path"
    Assert-Equal $qualificationRecordedStep.Replace("\", "/") $FixturePath "PMI input path"

    $qualificationRecordedRules = [string](Get-RequiredProperty $qualificationMeta "rules" "PMI report meta")
    Assert-SafeRelativeArtifactPath $qualificationRecordedRules "PMI rules path"
    Assert-Equal $qualificationRecordedRules.Replace("\", "/") "tests/fixtures/pmi_semantic/cadclaw.yaml" "PMI rules path"

    $qualificationSchema = [string](Get-RequiredProperty $qualificationMeta "step_schema" "PMI report meta")
    if (-not $qualificationSchema.StartsWith("AP242", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "PMI report did not preserve an AP242 schema declaration"
    }

    $qualificationActualClasses = @{}
    foreach ($qualificationClassResult in @(Get-RequiredProperty $qualificationMeta "class_results" "PMI report meta")) {
        $qualificationClassName = [string](Get-RequiredProperty $qualificationClassResult "class" "PMI class result")
        $qualificationClassStatus = [string](Get-RequiredProperty $qualificationClassResult "status" "PMI class result")
        $qualificationClassCount = [int](Get-RequiredProperty $qualificationClassResult "count" "PMI class result")
        if ($qualificationExpectedClasses -cnotcontains $qualificationClassName) {
            throw "PMI report contained unexpected semantic class '$qualificationClassName'"
        }
        if ($qualificationActualClasses.ContainsKey($qualificationClassName)) {
            throw "PMI report repeated semantic class '$qualificationClassName'"
        }
        $qualificationExpectedCount = [int]$ExpectedCounts[$qualificationClassName]
        if ($qualificationClassStatus -cne "present" -or $qualificationClassCount -ne $qualificationExpectedCount) {
            throw "PMI class '$qualificationClassName' did not match its frozen expected count"
        }
        $qualificationActualClasses[$qualificationClassName] = $qualificationClassCount
    }
    foreach ($qualificationExpectedClass in $qualificationExpectedClasses) {
        if (-not $qualificationActualClasses.ContainsKey($qualificationExpectedClass)) {
            throw "PMI report omitted expected semantic class '$qualificationExpectedClass'"
        }
        Assert-Equal $qualificationActualClasses[$qualificationExpectedClass] $ExpectedCounts[$qualificationExpectedClass] "PMI frozen count for $qualificationExpectedClass"
    }
    if ($qualificationActualClasses.Count -ne $qualificationExpectedClasses.Count) {
        throw "PMI report contained an unexpected semantic class"
    }

    Assert-NoSensitiveRuntimeFields $Report "PMI report"
    return $qualificationActualClasses
}

function Assert-RoundtripReport {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Report,

        [Parameter(Mandatory = $true)]
        [string]$FixtureSha256,

        [Parameter(Mandatory = $true)]
        [string]$DerivativePath,

        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$ExpectedCounts
    )

    Assert-Equal (Get-RequiredProperty $Report "schema_version" "round-trip report") $qualificationReportSchemaVersion "round-trip report schema"
    Assert-Equal (Get-RequiredProperty $Report "overall" "round-trip report") "pass" "round-trip report outcome"
    $qualificationMeta = Get-RequiredProperty $Report "meta" "round-trip report"
    Assert-Equal (Get-RequiredProperty $qualificationMeta "gate" "round-trip report meta") "ROUNDTRIP_STEP" "round-trip gate"
    Assert-Equal (Get-RequiredProperty $qualificationMeta "applicability" "round-trip report meta") "applicable" "round-trip applicability"
    Assert-Equal (Get-RequiredProperty $qualificationMeta "gate_spec_version" "round-trip report meta") $qualificationGateSpecVersion "round-trip gate-spec version"

    $qualificationDerivative = Get-RequiredProperty $qualificationMeta "derivative" "round-trip report meta"
    Assert-Equal (Get-RequiredProperty $qualificationDerivative "source_sha256" "round-trip derivative") $FixtureSha256 "round-trip source hash"
    Assert-Equal (Get-RequiredProperty $qualificationDerivative "persisted" "round-trip derivative") "True" "round-trip derivative persistence"

    $qualificationOutputSchema = [string](Get-RequiredProperty $qualificationDerivative "output_schema" "round-trip derivative")
    if ($qualificationOutputSchema -notmatch "(?i)AP242") {
        throw "round-trip derivative did not declare AP242"
    }
    if (-not (Test-Path -LiteralPath $DerivativePath -PathType Leaf)) {
        throw "round-trip derivative was not retained locally"
    }
    $qualificationDerivativeSha = Get-Sha256Lower $DerivativePath
    Assert-Equal (Get-RequiredProperty $qualificationDerivative "output_sha256" "round-trip derivative") $qualificationDerivativeSha "round-trip derivative hash"

    $qualificationWriteStatus = [string](Get-RequiredProperty $qualificationDerivative "write_status" "round-trip derivative")
    $qualificationWriteDisposition = [string](Get-RequiredProperty $qualificationDerivative "write_disposition" "round-trip derivative")
    switch ($qualificationWriteStatus) {
        "IFSelect_RetDone" {
            Assert-Equal $qualificationWriteDisposition "ret_done" "round-trip RetDone disposition"
        }
        "IFSelect_RetError" {
            Assert-Equal $qualificationWriteDisposition "ret_error_provisionally_validated" "round-trip RetError disposition"
            $qualificationConfidenceBudget = Get-RequiredProperty $Report "confidence_budget" "round-trip report"
            $qualificationNotChecked = @(
                Get-RequiredProperty $qualificationConfidenceBudget "not_checked" "round-trip confidence budget"
            ) -join "`n"
            if ($qualificationNotChecked -notmatch "provisionally validated error-status recovery") {
                throw "RetError report omitted the mandatory provisional-recovery limitation"
            }
        }
        default {
            throw "unsupported round-trip writer status '$qualificationWriteStatus'"
        }
    }

    $qualificationComparison = Get-RequiredProperty $qualificationMeta "translation_comparison" "round-trip report meta"
    Assert-Equal (Get-RequiredProperty $qualificationComparison "status" "round-trip comparison") "pass" "round-trip comparison outcome"
    $qualificationPmiComparison = Get-RequiredProperty $qualificationComparison "supported_semantic_pmi_class_counts" "round-trip comparison"
    Assert-Equal (Get-RequiredProperty $qualificationPmiComparison "status" "round-trip PMI comparison") "compared" "round-trip PMI comparison status"
    Assert-Equal (Get-RequiredProperty $qualificationPmiComparison "scope" "round-trip PMI comparison") "supported_semantic_class_counts_only" "round-trip PMI comparison scope"
    $qualificationRoundtripClasses = @{}
    foreach ($qualificationPmiResult in @(Get-RequiredProperty $qualificationPmiComparison "results" "round-trip PMI comparison")) {
        $qualificationClassName = [string](Get-RequiredProperty $qualificationPmiResult "class" "round-trip PMI result")
        if ($qualificationExpectedClasses -cnotcontains $qualificationClassName) {
            throw "round-trip report contained unexpected PMI class '$qualificationClassName'"
        }
        if ($qualificationRoundtripClasses.ContainsKey($qualificationClassName)) {
            throw "round-trip report repeated PMI class '$qualificationClassName'"
        }
        Assert-Equal (Get-RequiredProperty $qualificationPmiResult "status" "round-trip PMI result") "preserved" "round-trip PMI class result"
        Assert-Equal (Get-RequiredProperty $qualificationPmiResult "before_count" "round-trip PMI result") $ExpectedCounts[$qualificationClassName] "round-trip source count for $qualificationClassName"
        Assert-Equal (Get-RequiredProperty $qualificationPmiResult "after_count" "round-trip PMI result") $ExpectedCounts[$qualificationClassName] "round-trip derivative count for $qualificationClassName"
        $qualificationRoundtripClasses[$qualificationClassName] = $true
    }
    foreach ($qualificationExpectedClass in $qualificationExpectedClasses) {
        if (-not $qualificationRoundtripClasses.ContainsKey($qualificationExpectedClass)) {
            throw "round-trip report omitted expected PMI class '$qualificationExpectedClass'"
        }
    }
    if ($qualificationRoundtripClasses.Count -ne $qualificationExpectedClasses.Count) {
        throw "round-trip report did not contain exactly the frozen semantic PMI classes"
    }

    Assert-NoSensitiveRuntimeFields $Report "round-trip report"
    return [ordered]@{
        output_sha256 = $qualificationDerivativeSha
        output_size_bytes = (Get-Item -LiteralPath $DerivativePath).Length
        output_schema = $qualificationOutputSchema
        write_status = $qualificationWriteStatus
        write_disposition = $qualificationWriteDisposition
    }
}

function Invoke-CadclawGate {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$SnapshotRoot
    )

    Push-Location $SnapshotRoot
    try {
        $qualificationCommandOutput = & $script:qualificationPython @Arguments 2>&1
        $qualificationCommandExit = $LASTEXITCODE
        if ($null -ne $qualificationCommandOutput) {
            Write-Verbose "CADCLAW gate emitted console output; the JSON report remains the qualification source of truth"
        }
        return $qualificationCommandExit
    }
    finally {
        Pop-Location
    }
}

if ($CohortId -notmatch '^[a-z0-9][a-z0-9._-]{5,79}$') {
    throw "CohortId must be 6-80 lowercase ASCII letters, digits, dots, underscores, or hyphens"
}
if ($CohortId.EndsWith(".", [System.StringComparison]::Ordinal) -or $CohortId.EndsWith(" ", [System.StringComparison]::Ordinal)) {
    throw "CohortId must not end with a dot or space"
}
$qualificationDeviceStem = $CohortId.Split(".")[0]
if ($qualificationDeviceStem -match '^(con|prn|aux|nul|com[1-9]|lpt[1-9])$') {
    throw "CohortId must not use a reserved Windows device-name stem"
}

$qualificationScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$qualificationRepoRoot = Split-Path -Parent $qualificationScriptRoot
$qualificationRepoRoot = (Resolve-Path -LiteralPath $qualificationRepoRoot).Path

Push-Location $qualificationRepoRoot
try {
    & git fetch --no-tags origin "refs/heads/main:refs/remotes/origin/main"
    if ($LASTEXITCODE -ne 0) {
        throw "git fetch origin main failed; qualification requires a fresh remote-main observation"
    }
    $qualificationOriginMain = (& git rev-parse --verify "origin/main^{commit}").Trim()
    if ($LASTEXITCODE -ne 0 -or $qualificationOriginMain -notmatch '^[0-9a-f]{40}$') {
        throw "could not resolve fetched origin/main to an exact commit"
    }
    $qualificationHead = (& git rev-parse --verify "HEAD^{commit}").Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $qualificationHead -notmatch '^[0-9a-f]{40}$') {
        throw "could not resolve caller HEAD to an exact commit"
    }
    $qualificationWorktreeStatus = @(& git status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) {
        throw "could not verify caller worktree cleanliness"
    }
    Assert-CleanExactMainPreflight -HeadCommit $qualificationHead -OriginMainCommit $qualificationOriginMain -WorktreeStatus $qualificationWorktreeStatus
    if ([string]::IsNullOrWhiteSpace($TargetCommit)) {
        $qualificationTarget = $qualificationOriginMain
    }
    else {
        if ($TargetCommit -notmatch '^[0-9a-fA-F]{40}$') {
            throw "TargetCommit must be an exact 40-character commit SHA"
        }
        $qualificationTarget = (& git rev-parse --verify "$TargetCommit^{commit}").Trim().ToLowerInvariant()
        if ($LASTEXITCODE -ne 0) {
            throw "TargetCommit does not resolve to a local commit after fetch"
        }
    }
    if ($qualificationTarget -cne $qualificationOriginMain) {
        throw "TargetCommit must equal the freshly fetched origin/main commit"
    }
    $qualificationTree = (& git rev-parse "$qualificationTarget^{tree}").Trim()
    if ($LASTEXITCODE -ne 0 -or $qualificationTree -notmatch '^[0-9a-f]{40}$') {
        throw "could not resolve the target commit tree"
    }
}
finally {
    Pop-Location
}

if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $qualificationVenvPython = Join-Path $qualificationRepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $qualificationVenvPython -PathType Leaf) {
        $script:qualificationPython = (Resolve-Path -LiteralPath $qualificationVenvPython).Path
    }
    else {
        $qualificationPythonCommand = Get-Command python -CommandType Application -ErrorAction Stop
        $script:qualificationPython = $qualificationPythonCommand.Source
    }
}
else {
    $qualificationPythonCommand = Get-Command $PythonExecutable -CommandType Application -ErrorAction Stop
    $script:qualificationPython = $qualificationPythonCommand.Source
}

$qualificationEvidenceRoot = Join-Path $qualificationRepoRoot "evidence\qualifications\nist-ap242"
$qualificationCohortRoot = Join-Path $qualificationEvidenceRoot $CohortId
$qualificationLocalRoot = Join-Path $qualificationRepoRoot ".qualification-temp\nist-ap242\$CohortId"
$qualificationDerivativeRoot = Join-Path $qualificationLocalRoot "derivatives"
$qualificationStagingRoot = Join-Path $qualificationLocalRoot "cohort-staging"
Assert-NoReparsePointInExistingAncestors -Path $qualificationCohortRoot -Context "tracked evidence output"
Assert-NoReparsePointInExistingAncestors -Path $qualificationLocalRoot -Context "local qualification output"
if (Test-Path -LiteralPath $qualificationCohortRoot) {
    throw "cohort '$CohortId' already exists; qualification evidence is immutable"
}
if (Test-Path -LiteralPath $qualificationLocalRoot) {
    throw "local qualification work for '$CohortId' already exists; choose a new cohort id"
}

New-Item -ItemType Directory -Path $qualificationDerivativeRoot | Out-Null
New-Item -ItemType Directory -Path $qualificationStagingRoot | Out-Null
Assert-NoReparsePointInExistingAncestors -Path $qualificationDerivativeRoot -Context "local derivative output"
Assert-NoReparsePointInExistingAncestors -Path $qualificationStagingRoot -Context "qualification staging output"

$qualificationSnapshotParent = Join-Path ([System.IO.Path]::GetTempPath()) ("cadclaw-nist-ap242-" + [guid]::NewGuid().ToString("N"))
$qualificationArchive = Join-Path $qualificationSnapshotParent "target.zip"
$qualificationSnapshotRoot = Join-Path $qualificationSnapshotParent "source"
Assert-NoReparsePointInExistingAncestors -Path $qualificationSnapshotParent -Context "temporary target snapshot"
New-Item -ItemType Directory -Path $qualificationSnapshotParent | Out-Null

$qualificationStartedUtc = [DateTime]::UtcNow.ToString("o")
$qualificationFixtureDefinitions = @(
    [ordered]@{
        id = "nist-ftc-11-ap242-e2"
        case = "Fully-Toleranced Test Case 11"
        ap242_edition = "e2"
        path = "tests/fixtures/pmi_semantic/nist_ftc_11_asme1_ap242-e2.stp"
        sha256 = "20a92edf514ae0989d556f9c7b9f065aed741cfbb361b7fe4cb7938a1eb5c232"
        expected_counts = [ordered]@{
            dimensions = 6
            geometric_tolerances = 4
            datums = 4
        }
        provenance_note = "The NIST archive member is AP242 e2, while its embedded Part 21 FILE_NAME reports AP242 e1; this cohort retains the archive-member e2 identity without normalization."
    },
    [ordered]@{
        id = "nist-stc-06-ap242-e3"
        case = "Simplified Test Case 06"
        ap242_edition = "e3"
        path = "tests/fixtures/pmi_semantic/nist_stc_06_asme1_ap242-e3.stp"
        sha256 = "71777c28da76da0e8a667e4cbe792d5f72c09b5c56440c9744d3d50ca96ecc8d"
        expected_counts = [ordered]@{
            dimensions = 17
            geometric_tolerances = 25
            datums = 51
        }
        provenance_note = "The NIST archive member and this cohort identify the fixture as AP242 e3."
    }
)

try {
    Push-Location $qualificationRepoRoot
    try {
        & git archive --format=zip --output=$qualificationArchive $qualificationTarget
        if ($LASTEXITCODE -ne 0) {
            throw "could not materialize the exact target commit"
        }
    }
    finally {
        Pop-Location
    }
    Expand-Archive -LiteralPath $qualificationArchive -DestinationPath $qualificationSnapshotRoot

    $qualificationSnapshotRunner = Join-Path $qualificationSnapshotRoot "scripts\run-nist-ap242-qualification.ps1"
    if (-not (Test-Path -LiteralPath $qualificationSnapshotRunner -PathType Leaf)) {
        throw "the exact target commit does not contain this qualification runner; merge the runner before creating evidence"
    }
    $qualificationExecutingRunnerSha = Get-Sha256Lower $MyInvocation.MyCommand.Path
    $qualificationSnapshotRunnerSha = Get-Sha256Lower $qualificationSnapshotRunner
    Assert-Equal $qualificationExecutingRunnerSha $qualificationSnapshotRunnerSha "qualification runner hash at target commit"

    $qualificationSnapshotIgnore = Join-Path $qualificationSnapshotRoot ".gitignore"
    $qualificationIgnoreLines = @(Get-Content -LiteralPath $qualificationSnapshotIgnore)
    if ($qualificationIgnoreLines -cnotcontains ".qualification-temp/") {
        throw "the exact target commit does not ignore the local qualification work root"
    }
    $qualificationRulesRelativePath = "tests/fixtures/pmi_semantic/cadclaw.yaml"
    $qualificationRulesPath = Join-Path $qualificationSnapshotRoot $qualificationRulesRelativePath
    $qualificationRulesSha = Get-Sha256Lower $qualificationRulesPath
    $qualificationRulesSize = (Get-Item -LiteralPath $qualificationRulesPath).Length
    $qualificationRulesText = Get-Content -Raw -LiteralPath $qualificationRulesPath
    $qualificationRulesSchemaMatch = [regex]::Match(
        $qualificationRulesText,
        '(?m)^\s*schema_version:\s*["'']?(0\.9)["'']?\s*(?:#.*)?$'
    )
    if (-not $qualificationRulesSchemaMatch.Success) {
        throw "qualification rules do not declare the required schema version"
    }
    $qualificationObservedRulesSchema = $qualificationRulesSchemaMatch.Groups[1].Value
    Assert-Equal $qualificationObservedRulesSchema $qualificationRulesSchemaVersion "qualification rules schema"

    $qualificationRuntimeCode = @'
import json
import platform
from pathlib import Path
import cadclaw
import cadquery
import OCP

source_root = Path.cwd().resolve()
module_path = Path(cadclaw.__file__).resolve()
if source_root not in module_path.parents:
    raise SystemExit("CADCLAW import did not come from the target snapshot")

print(json.dumps({
    "python": {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
    },
    "cadclaw_version": cadclaw.__version__,
    "cadquery_version": cadquery.__version__,
    "cadquery_ocp_version": OCP.__version__,
    "operating_system": {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
    },
}, sort_keys=True))
'@
    Push-Location $qualificationSnapshotRoot
    try {
        $qualificationRuntimeRaw = & $script:qualificationPython -c $qualificationRuntimeCode
        if ($LASTEXITCODE -ne 0) {
            throw "could not attest the target snapshot runtime"
        }
    }
    finally {
        Pop-Location
    }
    $qualificationRuntime = $qualificationRuntimeRaw | ConvertFrom-Json
    $qualificationRuntime | Add-Member -NotePropertyName powershell_version -NotePropertyValue $PSVersionTable.PSVersion.ToString()
    Assert-NoSensitiveRuntimeFields $qualificationRuntime "qualification runtime"

    $qualificationFixtureResults = @()
    $qualificationExpectedTrackedNames = @("README.md", "manifest.json")
    $qualificationSawRetError = $false
    foreach ($qualificationFixture in $qualificationFixtureDefinitions) {
        $qualificationFixturePath = Join-Path $qualificationSnapshotRoot $qualificationFixture.path
        $qualificationObservedFixtureSha = Get-Sha256Lower $qualificationFixturePath
        Assert-Equal $qualificationObservedFixtureSha $qualificationFixture.sha256 "$($qualificationFixture.id) source fixture hash"
        $qualificationFixtureSize = (Get-Item -LiteralPath $qualificationFixturePath).Length

        $qualificationPmiReportName = "$($qualificationFixture.id).pmi-present.json"
        $qualificationRoundtripReportName = "$($qualificationFixture.id).roundtrip-step.json"
        $qualificationExpectedTrackedNames += @($qualificationPmiReportName, $qualificationRoundtripReportName)
        $qualificationPmiReportPath = Join-Path $qualificationStagingRoot $qualificationPmiReportName
        $qualificationRoundtripReportPath = Join-Path $qualificationStagingRoot $qualificationRoundtripReportName
        $qualificationDerivativeName = "$($qualificationFixture.id).roundtrip.stp"
        $qualificationDerivativePath = Join-Path $qualificationDerivativeRoot $qualificationDerivativeName
        $qualificationPmiReportSanitizedPath = ".qualification-temp/nist-ap242/$CohortId/cohort-staging/$qualificationPmiReportName"
        $qualificationRoundtripReportSanitizedPath = ".qualification-temp/nist-ap242/$CohortId/cohort-staging/$qualificationRoundtripReportName"
        $qualificationDerivativeSanitizedPath = ".qualification-temp/nist-ap242/$CohortId/derivatives/$qualificationDerivativeName"

        $qualificationPmiArguments = @(
            "-m", "cadclaw_cli.main",
            "pmi-present",
            "--rules", $qualificationRulesRelativePath,
            "--step", $qualificationFixture.path,
            "--report-format", "json",
            "-o", $qualificationPmiReportPath
        )
        $qualificationPmiArgvSanitized = @(
            ConvertTo-SanitizedArgv -Arguments $qualificationPmiArguments -PathReplacements ([ordered]@{
                $qualificationPmiReportPath = $qualificationPmiReportSanitizedPath
            })
        )
        $qualificationPmiStarted = [DateTime]::UtcNow.ToString("o")
        $qualificationPmiExit = Invoke-CadclawGate -SnapshotRoot $qualificationSnapshotRoot -Arguments $qualificationPmiArguments
        $qualificationPmiCompleted = [DateTime]::UtcNow.ToString("o")
        $qualificationPmiReport = Read-ValidatedJsonReport $qualificationPmiReportPath "$($qualificationFixture.id) PMI gate"
        if ($qualificationPmiExit -ne 0) {
            throw "$($qualificationFixture.id) PMI gate exited $qualificationPmiExit"
        }
        $qualificationPmiCounts = Assert-PmiReport -Report $qualificationPmiReport -FixturePath $qualificationFixture.path -ExpectedCounts $qualificationFixture.expected_counts

        $qualificationRoundtripArguments = @(
            "-m", "cadclaw_cli.main",
            "roundtrip-step",
            "--rules", $qualificationRulesRelativePath,
            "--step", $qualificationFixture.path,
            "--roundtrip-out", $qualificationDerivativePath,
            "--report-format", "json",
            "-o", $qualificationRoundtripReportPath
        )
        $qualificationRoundtripArgvSanitized = @(
            ConvertTo-SanitizedArgv -Arguments $qualificationRoundtripArguments -PathReplacements ([ordered]@{
                $qualificationDerivativePath = $qualificationDerivativeSanitizedPath
                $qualificationRoundtripReportPath = $qualificationRoundtripReportSanitizedPath
            })
        )
        $qualificationRoundtripStarted = [DateTime]::UtcNow.ToString("o")
        $qualificationRoundtripExit = Invoke-CadclawGate -SnapshotRoot $qualificationSnapshotRoot -Arguments $qualificationRoundtripArguments
        $qualificationRoundtripCompleted = [DateTime]::UtcNow.ToString("o")
        $qualificationRoundtripReport = Read-ValidatedJsonReport $qualificationRoundtripReportPath "$($qualificationFixture.id) round-trip gate"
        if ($qualificationRoundtripExit -ne 0) {
            throw "$($qualificationFixture.id) round-trip gate exited $qualificationRoundtripExit"
        }
        $qualificationRoundtripArtifact = Assert-RoundtripReport -Report $qualificationRoundtripReport -FixtureSha256 $qualificationFixture.sha256 -DerivativePath $qualificationDerivativePath -ExpectedCounts $qualificationFixture.expected_counts
        if ($qualificationRoundtripArtifact.write_disposition -ceq "ret_error_provisionally_validated") {
            $qualificationSawRetError = $true
        }

        $qualificationCountRecord = [ordered]@{}
        foreach ($qualificationExpectedClass in $qualificationExpectedClasses) {
            $qualificationCountRecord[$qualificationExpectedClass] = [int]$qualificationPmiCounts[$qualificationExpectedClass]
        }
        $qualificationFixtureResults += [ordered]@{
            id = $qualificationFixture.id
            case = $qualificationFixture.case
            ap242_edition = $qualificationFixture.ap242_edition
            source_path = $qualificationFixture.path
            source_sha256 = $qualificationFixture.sha256
            source_size_bytes = $qualificationFixtureSize
            source_kind = "authored NIST AP242 single-product qualification fixture"
            provenance_note = $qualificationFixture.provenance_note
            pmi_present = [ordered]@{
                started_utc = $qualificationPmiStarted
                completed_utc = $qualificationPmiCompleted
                exit_code = $qualificationPmiExit
                outcome = [string]$qualificationPmiReport.overall
                report_schema_version = [string]$qualificationPmiReport.schema_version
                gate_spec_version = [string]$qualificationPmiReport.meta.gate_spec_version
                argv_sanitized = $qualificationPmiArgvSanitized
                semantic_class_counts = $qualificationCountRecord
                report = $qualificationPmiReportName
                report_sha256 = Get-Sha256Lower $qualificationPmiReportPath
                report_size_bytes = (Get-Item -LiteralPath $qualificationPmiReportPath).Length
            }
            roundtrip_step = [ordered]@{
                started_utc = $qualificationRoundtripStarted
                completed_utc = $qualificationRoundtripCompleted
                exit_code = $qualificationRoundtripExit
                outcome = [string]$qualificationRoundtripReport.overall
                report_schema_version = [string]$qualificationRoundtripReport.schema_version
                gate_spec_version = [string]$qualificationRoundtripReport.meta.gate_spec_version
                argv_sanitized = $qualificationRoundtripArgvSanitized
                write_status = $qualificationRoundtripArtifact.write_status
                write_disposition = $qualificationRoundtripArtifact.write_disposition
                derivative_sha256 = $qualificationRoundtripArtifact.output_sha256
                derivative_size_bytes = $qualificationRoundtripArtifact.output_size_bytes
                derivative_schema = $qualificationRoundtripArtifact.output_schema
                derivative_retention = "local_only_ignored"
                report = $qualificationRoundtripReportName
                report_sha256 = Get-Sha256Lower $qualificationRoundtripReportPath
                report_size_bytes = (Get-Item -LiteralPath $qualificationRoundtripReportPath).Length
            }
        }
    }

    $qualificationCompletedUtc = [DateTime]::UtcNow.ToString("o")
    $qualificationOutcome = if ($qualificationSawRetError) {
        "pass_with_provisional_writer_status"
    }
    else {
        "pass"
    }
    $qualificationManifest = [ordered]@{
        schema_version = $qualificationManifestVersion
        cohort_id = $CohortId
        qualification_kind = "software_qualification"
        classification = [ordered]@{
            type = "software_qualification"
            software_qualification = $true
            marb_benchmark = $false
            model_calls = 0
            cost = [ordered]@{
                status = "not_incurred"
                value = 0
                currency = "USD"
                scope = "model/provider API cost"
            }
        }
        outcome = $qualificationOutcome
        qualification_passed = $true
        started_utc = $qualificationStartedUtc
        completed_utc = $qualificationCompletedUtc
        repository = [ordered]@{
            url = $qualificationRepositoryUrl
            target_commit = $qualificationTarget
            target_tree = $qualificationTree
            fetched_origin_main_commit = $qualificationOriginMain
            caller_head_commit = $qualificationHead
            target_equals_fetched_origin_main = $true
            caller_head_equals_fetched_origin_main = $true
            caller_worktree_clean = $true
            execution_source = "clean git archive of the exact target commit"
            runner_sha256 = $qualificationSnapshotRunnerSha
        }
        contracts = [ordered]@{
            manifest_schema_version = $qualificationManifestVersion
            report_schema_version = $qualificationReportSchemaVersion
            rules_schema_version = $qualificationRulesSchemaVersion
            gate_spec_version = $qualificationGateSpecVersion
        }
        runtime = $qualificationRuntime
        fixture_source = [ordered]@{
            publisher = "National Institute of Standards and Technology"
            dataset = "MBE PMI Validation and Conformance Testing STEP files"
            source_page = "https://www.nist.gov/ctl/smart-connected-systems-division/smart-connected-manufacturing-systems-group/mbe-pmi-0"
            source_document = "https://www.nist.gov/document/nist-pmi-step-files"
            retrieved_date = "2026-08-27"
            acknowledgement = "NIST supplied the authored test-case STEP files; use does not imply NIST recommendation or endorsement."
        }
        rules = [ordered]@{
            path = $qualificationRulesRelativePath
            schema_version = $qualificationObservedRulesSchema
            sha256 = $qualificationRulesSha
            size_bytes = $qualificationRulesSize
        }
        declared_semantic_pmi_classes = $qualificationExpectedClasses
        fixtures = $qualificationFixtureResults
        derivative_policy = [ordered]@{
            tracked_derivatives = $false
            local_ignored_root = ".qualification-temp/nist-ap242/$CohortId/derivatives"
            retained_for_local_review = $true
            note = "Derivative STEP files are intentionally excluded from Git; hashes and raw writer status/disposition remain in tracked evidence."
        }
        scope = @(
            "semantic AP242 presence for dimensions, geometric tolerances, and datums",
            "AP242 export and XCAF reimport",
            "CADCLAW-deduplicated renderable-shape count and bounding geometry preservation",
            "source-present supported semantic PMI class-count preservation"
        )
        limitations = @(
            "The two official NIST inputs are authored single-product qualification fixtures, not a blind assembly or model-performance benchmark.",
            "Graphical PMI presentation, saved views, materials, process data, and general notes are outside this qualification.",
            "Semantic PMI values, associations, construction correctness, and standards conformance are not certified.",
            "Native CAD source models and independent-kernel translation were not supplied or established.",
            "IFSelect_RetError, when observed, remains explicitly provisional after CADCLAW's bounded artifact, AP242-schema, and XCAF-reimport checks; writer-internal reference integrity and graphical PMI remain unchecked.",
            "NIST publication of the fixtures does not imply recommendation, endorsement, or error-free conformance reference status.",
            "No model, provider, token, cost, or paid benchmark work is part of this cohort."
        )
    }
    Assert-NoSensitiveRuntimeFields $qualificationManifest "qualification manifest"

    $qualificationManifestPath = Join-Path $qualificationStagingRoot "manifest.json"
    $qualificationManifestJson = $qualificationManifest | ConvertTo-Json -Depth 30
    Write-Utf8NoBom -Path $qualificationManifestPath -Content ($qualificationManifestJson + "`n")

    $qualificationStatusNote = if ($qualificationSawRetError) {
        "At least one OCCT writer returned IFSelect_RetError. CADCLAW preserved that raw status as ret_error_provisionally_validated after its bounded checks; this is not an unqualified writer-success claim."
    }
    else {
        "Both OCCT writes returned IFSelect_RetDone with the exact ret_done disposition."
    }
    $qualificationReadme = @"
# NIST AP242 software-qualification cohort: $CohortId

Outcome: **$qualificationOutcome**

This cohort qualifies CADCLAW commit $qualificationTarget (tree $qualificationTree), which exactly matched freshly fetched origin/main when the run began. CADCLAW executed from a clean Git archive of that commit; the caller's branch and working tree were not used as Python source.

## Evidence

The cohort runs pmi-present and roundtrip-step against the authored NIST FTC 11 AP242 e2 and STC 06 AP242 e3 fixtures. The FTC 11 archive member is AP242 e2 even though its embedded Part 21 FILE_NAME reports AP242 e1; this cohort retains the archive-member identity without normalization. manifest.json records exact fixture, report, derivative, commit, tree, runtime, and toolchain hashes or versions, along with UTC gate timestamps and exit outcomes. SHA256SUMS covers every tracked cohort artifact other than itself.

$qualificationStatusNote

Derivative STEP files are retained only under the ignored local directory .qualification-temp/nist-ap242/$CohortId/derivatives. They are not part of this tracked cohort. Their hashes, sizes, schemas, and exact OCCT writer statuses/dispositions remain in manifest.json and the raw round-trip reports.

## Scope and limitations

This is a no-spend software-qualification cohort, not a MARB/model benchmark and not a geometry-authoring exercise. It checks declared semantic dimensions, geometric tolerances, and datums; AP242 export/reimport; bounded geometry preservation; and supported semantic PMI class-count preservation.

It does not certify graphical PMI, saved views, materials, process/general notes, semantic values or associations, standards conformance, native-model fidelity, independent-kernel translation, NIST endorsement, or error-free reference-file status. See `manifest.json` for the complete confidence boundary.
"@
    Write-Utf8NoBom -Path (Join-Path $qualificationStagingRoot "README.md") -Content ($qualificationReadme.TrimEnd() + "`n")

    $qualificationChecksumFiles = Get-ChildItem -LiteralPath $qualificationStagingRoot -File |
        Where-Object { $_.Name -ne "SHA256SUMS" } |
        Sort-Object -Property Name
    $qualificationChecksumLines = foreach ($qualificationChecksumFile in $qualificationChecksumFiles) {
        "$(Get-Sha256Lower $qualificationChecksumFile.FullName)  $($qualificationChecksumFile.Name)"
    }
    Write-Utf8NoBom -Path (Join-Path $qualificationStagingRoot "SHA256SUMS") -Content (($qualificationChecksumLines -join "`n") + "`n")

    $qualificationExpectedFinalNames = @($qualificationExpectedTrackedNames + "SHA256SUMS") | Sort-Object -Unique
    $qualificationNestedDirectories = @(Get-ChildItem -LiteralPath $qualificationStagingRoot -Directory -Recurse -Force)
    if ($qualificationNestedDirectories.Count -ne 0) {
        throw "qualification cohort staging contains an unexpected nested directory"
    }
    $qualificationStagedFiles = @(Get-ChildItem -LiteralPath $qualificationStagingRoot -File -Recurse -Force)
    $qualificationActualFinalNames = @($qualificationStagedFiles | ForEach-Object { $_.Name } | Sort-Object -Unique)
    $qualificationInventoryDifference = @(Compare-Object -ReferenceObject $qualificationExpectedFinalNames -DifferenceObject $qualificationActualFinalNames)
    if ($qualificationInventoryDifference.Count -ne 0 -or $qualificationActualFinalNames.Count -ne $qualificationExpectedFinalNames.Count) {
        throw "qualification cohort staging file inventory does not match the frozen contract"
    }
    foreach ($qualificationStagedFile in $qualificationStagedFiles) {
        Assert-NoReparsePointInExistingAncestors -Path $qualificationStagedFile.FullName -Context "staged qualification artifact"
    }

    Assert-NoReparsePointInExistingAncestors -Path $qualificationEvidenceRoot -Context "tracked evidence root"
    if (-not (Test-Path -LiteralPath $qualificationEvidenceRoot)) {
        New-Item -ItemType Directory -Path $qualificationEvidenceRoot | Out-Null
    }
    Assert-NoReparsePointInExistingAncestors -Path $qualificationCohortRoot -Context "tracked evidence output"
    if (Test-Path -LiteralPath $qualificationCohortRoot) {
        throw "cohort '$CohortId' appeared during execution; refusing to overwrite it"
    }
    $qualificationStagingFull = [System.IO.Path]::GetFullPath($qualificationStagingRoot)
    $qualificationCohortFull = [System.IO.Path]::GetFullPath($qualificationCohortRoot)
    $qualificationStagingVolume = [System.IO.Path]::GetPathRoot($qualificationStagingFull)
    $qualificationCohortVolume = [System.IO.Path]::GetPathRoot($qualificationCohortFull)
    if (-not $qualificationStagingVolume.Equals($qualificationCohortVolume, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "qualification staging and evidence roots must be on the same volume for atomic publication"
    }
    [System.IO.Directory]::Move($qualificationStagingFull, $qualificationCohortFull)
    Write-Output "NIST AP242 qualification cohort ${CohortId}: $qualificationOutcome"
    Write-Output "Target commit: $qualificationTarget"
    Write-Output "Tracked evidence: evidence/qualifications/nist-ap242/$CohortId"
    Write-Output "Local derivatives: .qualification-temp/nist-ap242/$CohortId/derivatives"
}
finally {
    $qualificationSnapshotFull = [System.IO.Path]::GetFullPath($qualificationSnapshotParent)
    $qualificationTempFull = [System.IO.Path]::GetFullPath(
        [System.IO.Path]::GetTempPath()
    ).TrimEnd([char[]]@("\", "/"))
    $qualificationSnapshotParentInfo = [System.IO.Directory]::GetParent(
        $qualificationSnapshotFull
    )
    $qualificationSnapshotLeaf = Split-Path -Leaf $qualificationSnapshotFull
    if (
        $null -eq $qualificationSnapshotParentInfo -or
        -not $qualificationSnapshotParentInfo.FullName.Equals(
            $qualificationTempFull,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        $qualificationSnapshotLeaf -notmatch '^cadclaw-nist-ap242-[0-9a-f]{32}$'
    ) {
        throw "temporary snapshot cleanup target failed its exact-parent or GUID-leaf safety check"
    }
    Assert-NoReparsePointInExistingAncestors -Path $qualificationSnapshotFull -Context "temporary target snapshot cleanup"
    Remove-Item -LiteralPath $qualificationSnapshotFull -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $qualificationSnapshotFull) {
        throw "temporary target snapshot cleanup could not be verified"
    }
}
