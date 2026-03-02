param(
  [double]$RefreshSeconds = 2.0,
  [int]$LogTailLines = 120,
  [int]$StateChars = 0,
  [switch]$Once
)

$moonshotDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectsDir = Resolve-Path (Join-Path $moonshotDir "..\..")
$continuumDir = Join-Path $projectsDir "codex-continuum"
$watchPy = Join-Path $continuumDir "continuum_watch.py"

if (-not (Test-Path $watchPy)) {
  Write-Error "continuum_watch.py not found at: $watchPy"
  exit 1
}

$promptFile = Join-Path $moonshotDir "prompts\planning-worker.txt"
$conditionFile = Join-Path $moonshotDir "prompts\planning-condition.txt"

$cmdArgs = @(
  $watchPy,
  "--workdir", $moonshotDir,
  "--refresh-seconds", $RefreshSeconds,
  "--log-tail-lines", $LogTailLines,
  "--state-chars", $StateChars,
  "--prompt-file", $promptFile,
  "--condition-file", $conditionFile
)

if ($Once) { $cmdArgs += "--once" }

& python @cmdArgs
