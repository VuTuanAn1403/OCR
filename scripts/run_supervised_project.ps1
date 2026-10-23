param(
    [ValidateSet('antigravity', 'codex')]
    [string]$RequestedBy = 'antigravity',
    [switch]$FullBatch
)

$ErrorActionPreference = 'Stop'
$supervisedRoot = Split-Path -Parent $PSScriptRoot
$supervisedPython = Join-Path $supervisedRoot '.venv\Scripts\python.exe'
$supervisedOutput = Join-Path $supervisedRoot 'output\supervised_execution'
New-Item -ItemType Directory -Path $supervisedOutput -Force | Out-Null
$supervisedLockPath = Join-Path $supervisedOutput 'run.lock'
try {
    $supervisedLock = [System.IO.File]::Open(
        $supervisedLockPath, [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None
    )
} catch [System.IO.IOException] {
    Write-Host 'A supervised project run already holds the execution lock.'
    exit 2
}

$supervisedStamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 6)
$supervisedRun = Join-Path $supervisedOutput $supervisedStamp
New-Item -ItemType Directory -Path $supervisedRun -Force | Out-Null
$supervisedStatus = [ordered]@{
    status = 'RUNNING'
    requested_by = $RequestedBy
    process_id = $PID
    started_at_utc = [DateTime]::UtcNow.ToString('o')
    output_directory = $supervisedRun
    profile = 'unified_gpu_full_ocr'
    resume = $false
    full_batch = [bool]$FullBatch
    accuracy_status = 'NOT_EVALUATED_NO_INDEPENDENT_GROUND_TRUTH'
    steps = @()
}

function Save-SupervisedStatus {
    $supervisedStatus | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $supervisedRun 'run_status.json') -Encoding UTF8
    $supervisedStatus | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $supervisedOutput 'latest_run.json') -Encoding UTF8
}

function Invoke-SupervisedStep([string]$StepName, [string[]]$StepArguments) {
    Write-Host "Starting: $StepName"
    $supervisedTimer = [System.Diagnostics.Stopwatch]::StartNew()
    $supervisedPreviousPreference = $ErrorActionPreference
    try {
        # Native model warnings on stderr are logged without aborting a successful run.
        $ErrorActionPreference = 'Continue'
        & $supervisedPython @StepArguments 2>&1 | Tee-Object -FilePath (Join-Path $supervisedRun "$StepName.log")
        $supervisedStepExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $supervisedPreviousPreference
        $supervisedTimer.Stop()
    }
    $supervisedStatus.steps += [ordered]@{
        name = $StepName
        exit_code = $supervisedStepExit
        wall_seconds_including_process_startup = [math]::Round($supervisedTimer.Elapsed.TotalSeconds, 3)
    }
    Save-SupervisedStatus
    if ($supervisedStepExit -ne 0) { throw "$StepName failed with exit code $supervisedStepExit. See the saved log." }
}

$supervisedPriorLocation = Get-Location
try {
    Set-Location -LiteralPath $supervisedRoot
    Save-SupervisedStatus
    Write-Host "Execution owner: $RequestedBy; output: $supervisedRun"
    if (-not (Test-Path -LiteralPath $supervisedPython -PathType Leaf)) { throw 'Project Python environment is missing.' }
    Invoke-SupervisedStep 'gpu_smoke' @('scripts/smoke_unified.py', '--output', (Join-Path $supervisedRun 'smoke'))
    if ($FullBatch) {
        Invoke-SupervisedStep 'full_batch' @('run_batch.py', '--input', 'inputs', '--output', (Join-Path $supervisedRun 'batch'))
    }
    $supervisedStatus.status = 'COMPLETED'
    $supervisedStatus.finished_at_utc = [DateTime]::UtcNow.ToString('o')
    Save-SupervisedStatus
    Write-Host "Project execution completed: $supervisedRun"
} catch {
    $supervisedStatus.status = 'FAILED'
    $supervisedStatus.error = $_.Exception.Message
    $supervisedStatus.finished_at_utc = [DateTime]::UtcNow.ToString('o')
    Save-SupervisedStatus
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    exit 1
} finally {
    Set-Location -LiteralPath $supervisedPriorLocation.Path
    $supervisedLock.Dispose()
}
