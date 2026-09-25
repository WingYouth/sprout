<#
.SYNOPSIS
    Bring up the six-database stack for a fresh clone — one command.

.DESCRIPTION
    Runs the whole "somebody just cloned the repo" path:

      1. check that Docker answers (start Docker Desktop / WSL2 if not),
      2. pull the three service images, falling back to a CN mirror,
      3. build the runner image (dependencies plus the `lanes` extra),
      4. start Redis / Milvus / Neo4j and wait until they are healthy,
      5. then either initialise the six lanes or test them (see Command).

    Only the three derived lanes are containers. Sprout file authorities and
    user project ontology need no installation at all: they are ordinary files
    inside the `sprout-data` and `project-data` volumes, created on first write.

.PARAMETER Command
    What to do once the stack is up:

      init    create all six databases empty and ready (CLI: `sprout storage
              init`): the five SQLite schemas, the JSONL and blob directories,
              the three Milvus collections at the production embedding width,
              and the Neo4j constraints. Writes no data; safe to re-run.
      test    prove all six lanes (CLI: `sprout storage check`): write a
              session, two turns, a fact and a context snapshot through the
              production fan-out, then read every lane back with its own client.
              Add -Suite to also run the local live suite.
      up      start the three service lanes and stop there.
      (none)  same as `test` — bring the stack up and prove it.

.PARAMETER Suite
    With `test`, also run the local-only live suite (src/Sprout/tests). That
    suite is not tracked, so a fresh clone does not have it.

.PARAMETER Rebuild
    Rebuild the runner image even when it already exists.

.PARAMETER Down
    Stop the stack (keeps the volume, so the file lanes survive).

.PARAMETER NoProbe
    Start the stack but skip the six-lane proof.

.PARAMETER Clean
    Drop the derived Milvus collections before proving the lanes. Use it when a
    previous run created them at a different embedding width (for example the
    local-only test suite, which uses dim=64): the probe then refuses with a
    schema conflict instead of letting three lanes fail silently.

.PARAMETER Nuke
    Stop the stack and wipe it: delete the `sprout-data` and `project-data`
    volumes and the Milvus bind-mount state under `volumes/milvus`. Both are
    rebuildable, so this is the "blank slate" switch.

.EXAMPLE
    ./bootstrap.ps1                 # bring up + prove all six
    ./bootstrap.ps1 init            # create the six databases, write nothing
    ./bootstrap.ps1 test            # prove the six lanes
    ./bootstrap.ps1 test -Suite     # ... and run the local live suite too
    ./bootstrap.ps1 up              # service lanes only
    ./bootstrap.ps1 -Down           # stop (the volume survives)
    ./bootstrap.ps1 -Clean          # drop the derived Milvus collections first
    ./bootstrap.ps1 -Rebuild -NoProbe
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = "",
    [switch]$Rebuild,
    [switch]$Down,
    [switch]$NoProbe,
    [switch]$Clean,
    [switch]$Suite,
    [switch]$Nuke,
    [string]$PyPiIndex = "https://pypi.tuna.tsinghua.edu.cn/simple",
    [string]$ImageMirror = "docker.m.daocloud.io"
)

$ErrorActionPreference = "Stop"
$composeFile = Join-Path $PSScriptRoot "docker-compose.yml"

if (-not $env:SPROUT_SOURCE_DIR) {
    $sourceDir = Get-Location
    while ($sourceDir -and -not (Test-Path (Join-Path $sourceDir "pyproject.toml"))) {
        $sourceDir = Split-Path $sourceDir -Parent
    }
    if (-not $sourceDir) {
        Write-Host "!! cannot find repository root (no pyproject.toml above current directory)" -ForegroundColor Red
        exit 2
    }
    $env:SPROUT_SOURCE_DIR = $sourceDir.Path
}

# Normalise the command verb into two flags: create the lanes? prove them?
$doInit = $false
$doTest = $true
switch ($Command.ToLowerInvariant()) {
    ""      { }                                        # default: up + prove
    "up"    { $doTest = $false }                       # lanes only
    "init"  { $doInit = $true; $doTest = $false }      # create, write nothing
    "test"  { $doTest = $true }                        # prove
    default {
        Write-Host "!! unknown command '$Command'" -ForegroundColor Red
        Write-Host "   known commands: init | test | up" -ForegroundColor Red
        exit 2
    }
}

function Step([string]$Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Note([string]$Message) { Write-Host "    $Message" -ForegroundColor DarkGray }
function Fail([string]$Message) {
    Write-Host "`n!! $Message" -ForegroundColor Red
    exit 1
}

function Invoke-Compose {
    param([string[]]$Arguments, [switch]$AllowFailure)
    & docker compose -f $composeFile @Arguments
    $code = $LASTEXITCODE
    if ($code -ne 0 -and -not $AllowFailure) {
        Fail "docker compose $($Arguments -join ' ') exited with $code"
    }
}

# -- 1. Docker ---------------------------------------------------------------
Step "Checking Docker"
$serverVersion = (& docker version --format "{{.Server.Version}}" 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not ($serverVersion -match '^\d')) {
    Fail @"
The Docker engine is not answering. Start Docker Desktop and re-run.
On Windows that also means WSL2 must be up; if the engine keeps dropping,
check that Docker Desktop is not running its auto-updater.
"@
}
Note "engine $serverVersion"

if ($Nuke) {
    Step "Removing the stack, its volumes and the Milvus state"
    Invoke-Compose @("down", "-v", "--remove-orphans")
    # `down -v` drops the named `sprout-data` and `project-data` volumes. Milvus keeps its state
    # in a bind mount into the working tree, so it survives a plain `down -v` and
    # would leave the vector index (and its fixed embedding width) behind. It is a
    # derived lane - the next write re-mirrors it - so wiping it is safe.
    $milvusState = Join-Path $PSScriptRoot "volumes/milvus"
    if (Test-Path $milvusState) {
        Remove-Item -Recurse -Force $milvusState
        Note "removed the Milvus bind-mount state (volumes/milvus)"
    }
    Note "Sprout authorities, project ontology, and derived lanes wiped"
    exit 0
}

if ($Down) {
    Step "Stopping the stack (volumes keep Sprout and project authorities)"
    Invoke-Compose @("down", "--remove-orphans")
    exit 0
}

# -- 2. Service images -------------------------------------------------------
# Compose would pull these itself, but a mirror fallback is the difference
# between a working first run and a hung one on CN networks.
$images = @{
    "redis:7-alpine"            = "mirror-safe"
    "neo4j:5"                   = "mirror-safe"
    "milvusdb/milvus:v2.5.11"   = "mirror-safe"
}

function Test-Image([string]$Image) {
    & docker image inspect $Image *> $null
    return $LASTEXITCODE -eq 0
}

function Get-MirroredName([string]$Image) {
    if ($Image -match '/') { return "$ImageMirror/$Image" }
    return "$ImageMirror/library/$Image"
}

Step "Service images (Redis, Milvus, Neo4j)"
foreach ($image in $images.Keys) {
    if (Test-Image $image) {
        Note "$image already present"
        continue
    }
    Note "pulling $image"
    & docker pull $image *> $null
    if ($LASTEXITCODE -eq 0) { continue }

    $mirrored = Get-MirroredName $image
    Note "direct pull failed; trying $mirrored"
    & docker pull $mirrored
    if ($LASTEXITCODE -ne 0) {
        Fail "could not pull $image (tried $mirrored too). Check the network, or pre-pull the image yourself."
    }
    & docker tag $mirrored $image
    if ($LASTEXITCODE -ne 0) { Fail "pulled $mirrored but could not tag it as $image" }
    Note "tagged $mirrored as $image"
}

# -- 3. Runner image --------------------------------------------------------
Step "Runner image (the project's own code against all six lanes)"
if ($Rebuild -or -not (Test-Image "sprout-app:latest")) {
    Invoke-Compose @("build", "--build-arg", "PIP_INDEX_URL=$PyPiIndex", "sprout-app") -AllowFailure
    if ($LASTEXITCODE -ne 0) {
        Note "build against $PyPiIndex failed; retrying against PyPI"
        Invoke-Compose @("build", "--build-arg", "PIP_INDEX_URL=https://pypi.org/simple", "sprout-app")
    }
} else {
    Note "sprout-app:latest already present (use -Rebuild to refresh it)"
}

# -- 4. Start the lanes -----------------------------------------------------
Step "Starting the three service lanes"
Invoke-Compose @("up", "-d", "--wait", "--wait-timeout", "300", "sprout-redis", "sprout-neo4j", "sprout-milvus")
Invoke-Compose @("ps")

# -- 5. Initialise and/or prove all six -------------------------------------
if ($Clean) {
    Step "Dropping the derived Milvus collections (resets the embedding width)"
    Invoke-Compose @("run", "--rm", "-T", "sprout-app", "python", "/app/docker/milvus_cleanup.py")
}

if ($doInit) {
    Step "Initialising the six lanes (create them, write no data)"
    # The service's own command is the check; the init verb is the sibling CLI
    # command, so both halves of the database lifecycle run the same code the
    # project ships.
    Invoke-Compose @("run", "--rm", "-T", "sprout-app", "python", "-m", "Sprout",
        "storage", "init")
}

if ($NoProbe) {
    Note "skipping the proof (-NoProbe)"
    exit 0
}

if ($doTest) {
    Step "Six-lane proof (write through the bundle, read every lane back)"
    # No command argument: the service's own command is the CLI verb
    # `python -m Sprout storage check`. -T disables TTY allocation, so this
    # also works from CI or any non-interactive shell.
    Invoke-Compose @("run", "--rm", "-T", "sprout-app")

    if ($Suite) {
        Step "Local live suite (16 tests, env-gated on the container lanes)"
        Invoke-Compose @("run", "--rm", "-T", "sprout-app", "python", "-m", "pytest",
            "-p", "no:cacheprovider", "-c", "/app/pyproject.toml",
            "/app/src/Sprout/tests/test_sixlane.py", "-v", "--no-header")
    }
}

Write-Host "`nAll six lanes are up. Next:" -ForegroundColor Green
Write-Host "  ./bootstrap.ps1 init            # create all six, write nothing"
Write-Host "  ./bootstrap.ps1 test            # prove all six"
Write-Host "  ./bootstrap.ps1 -Clean          # reset the derived Milvus collections"
Write-Host "  docker compose -f `"$composeFile`" down        # stop (volume survives)"
Write-Host "  ./bootstrap.ps1 -Nuke           # stop; wipe the volume + the Milvus state"
