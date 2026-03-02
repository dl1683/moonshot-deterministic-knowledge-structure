param(
  [int]$MaxIterations = 0,
  [double]$HeartbeatSeconds = 30,
  [switch]$EchoProgress,
  [switch]$EchoErrors,
  [string]$DirectiveFile = "prompts\\runtime-directive.txt",
  [string]$PostIterCommand = "tools\\post_iter_verify.cmd",
  [double]$PostIterTimeout = 180,
  [switch]$NoJudge
)

$moonshotDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectsDir = Resolve-Path (Join-Path $moonshotDir "..\..")
$continuumDir = Join-Path $projectsDir "codex-continuum"
$continuumScript = Join-Path $continuumDir "continuum.ps1"

if (-not (Test-Path $continuumScript)) {
  Write-Error "continuum.ps1 not found at: $continuumScript"
  exit 1
}

$promptFile = Join-Path $moonshotDir "prompts\planning-worker.txt"
$conditionFile = Join-Path $moonshotDir "prompts\planning-condition.txt"
$directiveFilePath = if ([System.IO.Path]::IsPathRooted($DirectiveFile)) {
  $DirectiveFile
} else {
  Join-Path $moonshotDir $DirectiveFile
}

$cmdArgs = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", $continuumScript,
  "-Workdir", $moonshotDir,
  "-PromptFile", $promptFile,
  "-DirectiveFile", $directiveFilePath,
  "-MaxIterations", $MaxIterations,
  "-HeartbeatSeconds", $HeartbeatSeconds,
  "-PostIterCommand", $PostIterCommand,
  "-PostIterTimeout", $PostIterTimeout
)

if ($NoJudge) {
  $cmdArgs += "-NoJudge"
} else {
  $cmdArgs += @("-ConditionFile", $conditionFile)
}

if ($EchoProgress) { $cmdArgs += "-EchoProgress" }
if ($EchoErrors) { $cmdArgs += "-EchoErrors" }

Push-Location $continuumDir
try {
  & powershell @cmdArgs
} finally {
  Pop-Location
}
