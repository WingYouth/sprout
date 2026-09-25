#!/usr/bin/env bash
# Bring up the six-database stack for a fresh clone — one command.
#
#   ./bootstrap.sh              # bring the stack up and prove all six
#   ./bootstrap.sh init         # create all six databases, write no data
#   ./bootstrap.sh test         # prove all six lanes
#   ./bootstrap.sh test --suite  # prove them and run the local live suite
#   ./bootstrap.sh up           # start the three service lanes only
#   ./bootstrap.sh --rebuild    # rebuild the runner image
#   ./bootstrap.sh --clean      # drop the derived Milvus collections first
#   ./bootstrap.sh --down       # stop (the volume keeps the file lanes)
#   ./bootstrap.sh --nuke       # stop; wipe the volume and the Milvus state
#
# Only the three derived lanes are containers; Sprout file authorities and
# user project ontology are files inside the `sprout-data` and `project-data`
# volumes and need no installation.

set -euo pipefail

if [[ -z "${SPROUT_SOURCE_DIR:-}" ]]; then
    SPROUT_SOURCE_DIR="$(pwd)"
    while [[ ! -f "${SPROUT_SOURCE_DIR}/pyproject.toml" ]]; do
        PARENT="$(dirname "${SPROUT_SOURCE_DIR}")"
        if [[ "${PARENT}" == "${SPROUT_SOURCE_DIR}" ]]; then
            printf 'cannot find repository root (no pyproject.toml above %s)\n' "$(pwd)" >&2
            exit 2
        fi
        SPROUT_SOURCE_DIR="${PARENT}"
    done
fi
export SPROUT_SOURCE_DIR

# Resolve this script's own directory without coreutils: minimal images and the
# Git Bash shim on Windows do not always ship `dirname`. Accept both POSIX and
# Windows-style separators.
SELF="${BASH_SOURCE[0]//\\//}"
case "${SELF}" in
    */*) SCRIPT_DIR="${SELF%/*}" ;;
    *)   SCRIPT_DIR="." ;;
esac
# Work from the stack's own directory and name the compose file relatively: an
# absolute POSIX path handed to docker.exe gets rewritten by the MSYS layer on
# Windows (it turns /d/x into D:\d\x), while a bare filename never does.
cd -- "${SCRIPT_DIR}" 2>/dev/null \
    || { printf 'cannot enter %s\n' "${SCRIPT_DIR}" >&2; exit 1; }
COMPOSE_FILE="docker-compose.yml"
PYPI_INDEX="${PYPI_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
IMAGE_MIRROR="${IMAGE_MIRROR:-docker.m.daocloud.io}"

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
note() { printf '    \033[90m%s\033[0m\n' "$1"; }
die()  { printf '\n\033[31m!! %s\033[0m\n' "$1" >&2; exit 1; }

usage() {
    printf '%s\n' \
        "Bring up the six-database stack for a fresh clone." \
        "" \
        "  ./bootstrap.sh               bring the stack up and prove all six" \
        "  ./bootstrap.sh init          create all six databases, write no data" \
        "  ./bootstrap.sh test          prove all six lanes" \
        "  ./bootstrap.sh test --suite  prove them and run the local live suite" \
        "  ./bootstrap.sh up            start the three service lanes only" \
        "  ./bootstrap.sh --rebuild     rebuild the runner image" \
        "  ./bootstrap.sh --clean       drop the derived Milvus collections first" \
        "  ./bootstrap.sh --down        stop (the volume keeps the file lanes)" \
        "  ./bootstrap.sh --nuke        stop; wipe the volume and the Milvus state"
}

compose() { docker compose -f "${COMPOSE_FILE}" "$@"; }

REBUILD=0
NO_PROBE=0
CLEAN=0
SUITE=0
DOWN=0
NUKE=0
COMMAND=""

for arg in "$@"; do
    case "${arg}" in
        init|test|up) COMMAND="${arg}" ;;
        --suite) SUITE=1 ;;
        --rebuild) REBUILD=1 ;;
        --no-probe) NO_PROBE=1 ;;
        --clean) CLEAN=1 ;;
        --down) DOWN=1 ;;
        --nuke) NUKE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'unknown argument: %s\n' "${arg}" >&2; exit 2 ;;
    esac
done

# Normalise the verb into two flags: create the lanes? prove them?
DO_INIT=0
DO_TEST=1
case "${COMMAND}" in
    "")     DO_INIT=0; DO_TEST=1 ;;   # default: up + prove
    up)     DO_INIT=0; DO_TEST=0 ;;   # lanes only
    init)   DO_INIT=1; DO_TEST=0 ;;   # create, write nothing
    test)   DO_INIT=0; DO_TEST=1 ;;   # prove
esac

# -- 1. Docker ---------------------------------------------------------------
step "Checking Docker"
command -v docker >/dev/null 2>&1 || die "docker is not on PATH."
if ! docker info >/dev/null 2>&1; then
    die "The Docker engine is not answering. Start Docker Desktop / dockerd and re-run."
fi
# The MSYS bash shipped with Git for Windows eats one layer of braces from a Go
# template, so the version arrives as a bare `.Server.Version`. Escaping the
# braces fixes it there but makes the template invalid on Linux, so fall back to
# a neutral message instead of printing something misleading.
SERVER_VERSION="$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)"
case "${SERVER_VERSION}" in
    [0-9]*) note "engine ${SERVER_VERSION}" ;;
    *)      note "engine reachable (version unreadable through this shell)" ;;
esac

if [[ "${NUKE}" == "1" ]]; then
    step "Removing the stack, its volumes and the Milvus state"
    compose down -v --remove-orphans
    # `down -v` drops the named `sprout-data` and `project-data` volumes. Milvus keeps its state
    # in a bind mount into the working tree, so it survives a plain `down -v` and
    # would leave the vector index (and its fixed embedding width) behind. It is a
    # derived lane - the next write re-mirrors it - so wiping it is safe.
    MILVUS_STATE="volumes/milvus"
    if [[ -d "${MILVUS_STATE}" ]]; then
        if rm -rf -- "${MILVUS_STATE}"; then
            note "removed the Milvus bind-mount state (volumes/milvus)"
        else
            note "could not remove ${MILVUS_STATE} (docker may own it; delete it by hand)"
        fi
    fi
    note "Sprout authorities, project ontology, and derived lanes wiped"
    exit 0
fi

if [[ "${DOWN}" == "1" ]]; then
    step "Stopping the stack (volumes keep Sprout and project authorities)"
    compose down --remove-orphans
    exit 0
fi

# -- 2. Service images -------------------------------------------------------
# Compose pulls these itself, but the mirror fallback is the difference between
# a working first run and a hung one on networks where Docker Hub is blocked.
step "Service images (Redis, Milvus, Neo4j)"
for image in "redis:7-alpine" "neo4j:5" "milvusdb/milvus:v2.5.11"; do
    if docker image inspect "${image}" >/dev/null 2>&1; then
        note "${image} already present"
        continue
    fi
    note "pulling ${image}"
    if docker pull "${image}" >/dev/null 2>&1; then
        continue
    fi
    case "${image}" in
        */*) mirrored="${IMAGE_MIRROR}/${image}" ;;
        *)   mirrored="${IMAGE_MIRROR}/library/${image}" ;;
    esac
    note "direct pull failed; trying ${mirrored}"
    docker pull "${mirrored}" \
        || die "could not pull ${image} (tried ${mirrored} too)."
    docker tag "${mirrored}" "${image}"
    note "tagged ${mirrored} as ${image}"
done

# -- 3. Runner image --------------------------------------------------------
step "Runner image (the project's own code against all six lanes)"
if [[ "${REBUILD}" == "1" ]] || ! docker image inspect "sprout-app:latest" >/dev/null 2>&1; then
    if ! compose build --build-arg "PIP_INDEX_URL=${PYPI_INDEX}" sprout-app; then
        note "build against ${PYPI_INDEX} failed; retrying against PyPI"
        compose build --build-arg "PIP_INDEX_URL=https://pypi.org/simple" sprout-app
    fi
else
    note "sprout-app:latest already present (use --rebuild to refresh it)"
fi

# -- 4. Start the lanes -----------------------------------------------------
step "Starting the three service lanes"
compose up -d --wait --wait-timeout 300 sprout-redis sprout-neo4j sprout-milvus
compose ps

# -- 5. Initialise and/or prove all six -------------------------------------
if [[ "${CLEAN}" == "1" ]]; then
    step "Dropping the derived Milvus collections (resets the embedding width)"
    compose run --rm -T sprout-app python /app/docker/milvus_cleanup.py
fi

if [[ "${DO_INIT}" == "1" ]]; then
    step "Initialising the six lanes (create them, write no data)"
    # The service's own command is the check; the init verb is the sibling CLI
    # command, so both halves of the database lifecycle run the same code.
    compose run --rm -T sprout-app python -m Sprout storage init
fi

if [[ "${NO_PROBE}" == "1" ]]; then
    note "skipping the proof (--no-probe)"
    exit 0
fi

if [[ "${DO_TEST}" == "1" ]]; then
    step "Six-lane proof (write through the bundle, read every lane back)"
    # No command argument: the service's own command is the CLI verb
    # `python -m Sprout storage check`. -T disables TTY allocation, so this
    # also works from CI / non-interactive shells.
    compose run --rm -T sprout-app

    if [[ "${SUITE}" == "1" ]]; then
        step "Local live suite (16 tests, env-gated on the container lanes)"
        compose run --rm -T sprout-app python -m pytest \
            -p no:cacheprovider -c /app/pyproject.toml \
            /app/src/Sprout/tests/test_sixlane.py -v --no-header
    fi
fi

printf '%s\n' \
    "" \
    "All six lanes are up. Next:" \
    "  ./bootstrap.sh init            # create all six, write nothing" \
    "  ./bootstrap.sh test            # prove all six" \
    "  ./bootstrap.sh --clean         # reset the derived Milvus collections" \
    "  ./bootstrap.sh --down          # stop (volume survives)" \
    "  ./bootstrap.sh --nuke          # stop; wipe the volume and the Milvus state"
