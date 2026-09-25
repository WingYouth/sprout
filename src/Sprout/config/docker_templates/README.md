# Six-database stack (Docker)

Two commands cover the lifecycle — create the six databases, then prove they all
work. Both are wrappers over the project's own CLI, so the same code runs with
or without Docker: `init` is `sprout storage init`, `test` is
`sprout storage check`.

```powershell
./bootstrap.ps1 init       # Windows: create all six databases, write no data
./bootstrap.ps1 test       # Windows: write real data, read every lane back
```
```bash
./bootstrap.sh init        # macOS / Linux  (= sprout storage init)
./bootstrap.sh test        #                (= sprout storage check)
```

With no verb, `./bootstrap.ps1` brings the stack up and runs `test`.

## Fresh clone — what a teammate runs

```bash
git clone https://github.com/WingYouth/SEAM_Sprout.git
cd SEAM_Sprout
~/.sprout/docker/bootstrap.sh init      # macOS / Linux: create all six databases
~/.sprout/docker/bootstrap.sh test      # prove them
```
```powershell
.\docker\bootstrap.ps1 init     # Windows, from the repository root
.\docker\bootstrap.ps1 test
```

> **Branch note.** The stack currently ships on `dev`. If the branch you cloned
> (usually `main`) has no generated home stack yet, run `sprout` once or
> `sprout home` after the
> clone — the commands below assume the checkout contains this directory.

`init` is the entire "set up the databases" story: pull the three service images
(with the CN mirror fallback), build the runner image, start the lanes, then
create the six databases empty. Nothing else needs installing — the three file
lanes are plain files the runner creates on its own volume.

Prerequisites: Docker with the compose plugin (on Windows, Docker Desktop with
WSL2 running), about 1.5 GB for the Redis/Neo4j/Milvus images, and free host
ports 6380, 7474, 7687, 9091 and 19530.

A fresh clone has neither `sprout-data` nor `project-data` volumes nor a
`~/.sprout/docker/volumes/milvus`
directory, so the first run always starts from an empty Milvus and cannot hit the
embedding-width conflict noted below.
`src/Sprout/tests/` is not tracked either, so a teammate gets `init` and `test`
but not the live suite.

## What actually runs

| Lane | Role | Where it runs | Needs installing? |
|---|---|---|---|
| **SQLite** | Sprout authorities (`sprout_core`, `sprout_conversation`, `sprout_knowledge`, `sprout_audit`, `sprout_usage`) | `sprout-data` volume, in-process | no |
| **SQLite** | user project ontology (`project_manifest`, `project_structure`, `project_architecture`, `project_database`, `project_evolution`) | `project-data` volume at `/data/projects`, in-process | no |
| **JSONL** | append-only evidence log | `sprout-data` / `project-data`, in-process | no |
| **BlobStore** | content-addressed objects | `sprout-data` / `project-data`, in-process | no |
| **Redis** | hot path (session cache, context cache) | `sprout-redis` container | yes |
| **Milvus** | vector index | `sprout-milvus` container | yes |
| **Neo4j** | graph projection | `sprout-neo4j` container | yes |

The authority files are ordinary files inside the `sprout-data` and
`project-data` volumes —
nothing to install and nothing to pull. `init` creates them up front (empty); if
you skip it, the first write creates them on the fly. Only the three derived
lanes are containers, and they are rebuildable at any time (delete them and the
next write re-mirrors).

Where the derived lanes keep their state differs, and it matters when you want a
blank slate: Redis and Neo4j use the named `sprout-redis-data` and
`sprout-neo4j-data` volumes, while Milvus uses the generated
`~/.sprout/docker/volumes/milvus`
bind mount. `docker compose down -v` removes the named `sprout-data` and
`project-data`, Redis, and Neo4j volumes, so it leaves the vector index — and its
fixed embedding width — behind.
`-Nuke` therefore deletes that directory as well.

`sprout-app` is the **runner**: it executes this repository's own code
(bind-mounted read-only at `/app`) against all six lanes, so "six databases
together" is verifiable rather than asserted. It is deliberately *not* a
long-running service — invoke it per command:

```bash
docker compose run --rm -T sprout-app                      # the six-lane proof
docker compose exec sprout-redis redis-cli keys 'sprout:*'
```

`-T` disables TTY allocation, which is what makes `run` usable from CI and from
non-interactive shells; drop it for an interactive session.

### The local live suite

`src/Sprout/tests/` is deliberately **not tracked** (it is in `.gitignore`), so
a clone gets the check but not the test suite. If you have it locally, it can
run against the same lanes:

```bash
docker compose run --rm -T sprout-app python -m pytest \
    -p no:cacheprovider -c /app/pyproject.toml \
    /app/src/Sprout/tests/test_sixlane.py -v
```

> **The suite and the check disagree on embedding width.** The suite creates its
> Milvus collections at `dim=64` (to stay fast); `sprout storage check` uses the
> production `1536`. Both use the same `sprout_vec_*` namespaces, and Milvus
> fixes the width when a collection is *created* — so whichever ran first wins,
> and the other fails with
> `the length(64) of float data should divide the dim(1536)`.
> Clear the collections between the two:
>
> ```bash
> docker compose run --rm -T sprout-app python /app/docker/milvus_cleanup.py
> ```
>
> A fresh clone never hits this: the volume starts empty and only the check
> runs.

## How to test the six lanes

Three layers, cheapest first. The first is what answers "are all six databases
actually running together?":

**1. The six-lane check — `./bootstrap.ps1 test`.** This is the CLI verb
`sprout storage check` (inside the runner image, `python -m Sprout storage
check`; the image does not install the console script). It writes a session, two
turns, a memory fact and an oversized (108 KB) context snapshot through the
*production* fan-out, then reads every lane back with its **own** client:
`sqlite3` on the file, Redis, Milvus, Neo4j, the blob directory, the JSONL log.
Exit 0 only when all six hold the data and the fan-out logged no lane errors.

The read-back is the point — "the fan-out said it worked" is not evidence, and
a lane failure is logged rather than raised, so an unreachable Milvus looks
exactly like an empty one. Milvus row counts printed by the check are
*cumulative* across runs (the derived lanes are append-and-rebuild, not wiped
per run); `-Clean` resets them. The JSONL lane is append-only evidence by
design.

You can run the same verb by hand, which is what `bootstrap` does:

```bash
docker compose run --rm -T sprout-app                       # the service's own command
docker compose run --rm -T sprout-app python -m Sprout storage check
docker compose run --rm -T sprout-app python -m Sprout storage check --json
```

Outside Docker, on a checkout with the lanes installed, it is just
`sprout storage check` (add `--config <path>` to point at another `sprout.toml`).
Run it against the no-Docker profile and it verifies what that profile actually
has, naming the rest as skipped:

```bash
SPROUT_CONFIG=~/.sprout/docker/sprout.local.toml.example sprout storage check
# [  ok] SQLite (authority) …   [  ok] BlobStore (objects) …
# skipped JSONL (evidence): the context lane is 'sqlite:///data/context.db', not a jsonl:// store
# skipped Redis (hot path): the cache lane is 'memory'
# …
```

The check is topology aware. Lanes pointing at `memory`/`none` have no external
client to read back with, so they are skipped and **reported as skipped** rather
than counted as verified — 2 verified beats 6 claimed. Exit codes: `0` every
checked lane holds the data; `1` a lane failed; `2` no six-lane fan-out is
configured at all; `3` a stale Milvus embedding width (run `-Clean`).

The sibling verb creates rather than proves, and is what `init` runs:

```bash
docker compose run --rm -T sprout-app python -m Sprout storage init
docker compose run --rm -T sprout-app python -m Sprout storage init --json
```

`init` is idempotent (`IF NOT EXISTS` at every layer), writes no business data,
and skips the same non-service lanes. Exit codes: `0` everything configured was
created; `1` a configured lane failed. Outside Docker it is `sprout storage init`
— note that this *supersedes* the older behaviour of reserving only the SQLite
schemas: the Milvus collections and the Neo4j constraints are created too.

**2. The live suite — `./bootstrap.ps1 test -Suite`.** The 16 env-gated
integration tests in `src/Sprout/tests/test_sixlane.py`, pointed at the
container lanes through the `SPROUT_TEST_*` variables compose already injects.
Per-contract assertions rather than one end-to-end story. The suite is
local-only, so a fresh clone does not have it.

**3. Spot checks.** Whatever you want to see with your own eyes:

```bash
docker compose exec sprout-redis redis-cli keys 'sprout:*'            # Redis
docker compose exec sprout-neo4j /var/lib/neo4j/bin/cypher-shell \
    -u neo4j -p sprout123 \
    "MATCH (n) RETURN labels(n) AS l, count(*) AS n ORDER BY n DESC"  # Neo4j
docker compose run --rm -T sprout-app ls -la /data                    # Sprout file authorities
docker compose run --rm -T sprout-app ls -la /data/projects           # user project ontology
```

Milvus ships no CLI in the image; read it through the check's row counts, or
point any Milvus client at `localhost:19530`. Neo4j Browser is on
<http://localhost:7474> (neo4j / sprout123).

## Commands

Each verb is a wrapper over a `sprout` command, so nothing here is Docker-only
knowledge — `init` → `sprout storage init`, `test` → `sprout storage check`.

```bash
./bootstrap.ps1               # bring up + prove all six
./bootstrap.ps1 init          # create all six databases, write no data
./bootstrap.ps1 test          # prove all six lanes
./bootstrap.ps1 test -Suite   # ... and run the local live suite too
./bootstrap.ps1 up            # start the three service lanes only

./bootstrap.ps1 -Clean        # drop the derived Milvus collections first
./bootstrap.ps1 -Rebuild      # rebuild the runner image after changing dependencies
./bootstrap.ps1 -NoProbe      # start the lanes without running the proof
./bootstrap.ps1 -Down         # stop (the volume survives)
./bootstrap.ps1 -Nuke         # stop; wipe the volume and the Milvus state
```

Raw compose works too: `docker compose -f ~/.sprout/docker/docker-compose.yml up -d
--wait sprout-redis sprout-neo4j sprout-milvus`, then `ps`, `down`, `down -v`.

## Ports

| Service | Host port | In-network |
|---|---|---|
| Redis | `6380` (keeps the native Redis on 6379 free) | `sprout-redis:6379` |
| Neo4j | `7687` Bolt, `7474` HTTP (neo4j / sprout123) | `sprout-neo4j:7687` |
| Milvus | `19530` gRPC, `9091` health | `sprout-milvus:19530` |

## Configuration

`sprout.containers.toml` is the container-side settings file (`SPROUT_CONFIG`).
Two things are worth knowing:

- **Paths are relative on purpose.** Both DSN parsers strip exactly one leading
  slash after the scheme, so `sqlite:////data/sprout_conversation.db` would silently become
  the *relative* path `data/sprout_conversation.db`. The runner's `WORKDIR` is `/data` (the
  volume), and that is what the relative DSNs resolve against.
- **Service lanes use compose DNS names** — `redis://sprout-redis:6379`,
  `milvus://sprout-milvus:19530`, `neo4j://neo4j:sprout123@sprout-neo4j:7687`.
  The credentials live in the DSN (the Neo4j store strips the userinfo before
  handing the URI to the 6.x driver, which rejects userinfo).

Switch a lane by editing that file; no code changes. Dropping `cache`,
`vectors`, `graph` and `context` to `memory`/`none` degrades gracefully — the
authority lanes keep working and the missing lanes are skipped, never fatal.

## Without Docker

The authority lanes are files, so a contributor with no Docker still gets a
working (three-lane) runtime:

```bash
uv sync --extra lanes                 # clients for the three service lanes, optional
SPROUT_CONFIG=~/.sprout/docker/sprout.local.toml.example sprout storage status
SPROUT_CONFIG=~/.sprout/docker/sprout.local.toml.example sprout storage check
```

`SQLite + JSONL + BlobStore (+ FTS5)` is fully offline and is enough for
development and the whole test suite except the env-gated live tests.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `docker compose ps` shows three containers, "where are the other three?" | Expected: file authorities live inside the runner's `sprout-data` / `project-data` volumes. Run `docker compose run --rm sprout-app` to see them written and read back. |
| Engine not answering | Start Docker Desktop (WSL2 must be up). If it keeps dropping, check Docker Desktop's auto-updater — it shuts the engine down mid-install. |
| Image pull stalls or EOFs | Milvus is ~600 MB of layers and does not resume. `bootstrap` retries through `docker.m.daocloud.io`; you can also pre-pull `docker.m.daocloud.io/library/<image>` and `docker tag` it. |
| Milvus unhealthy for ~90 s after `up` | Normal: the embedded etcd starts first. The health gate waits it out. |
| `pip install` fails while building the runner | `bootstrap` retries against PyPI; to pin another index: `./bootstrap.ps1 -PyPiIndex <url>`. |
| `ModuleNotFoundError` from inside the container right after someone changed `pyproject.toml` | `requirements-lanes.txt` is a `uv export` **snapshot**, so the image installs yesterday's dependency set. Re-export with the command in that file's header, then `./bootstrap.ps1 -Rebuild`. |
| `milvus schema conflict: … embedding dim 64, expected 1536` | A previous run created the collections with a narrower embedding, and Milvus fixes the width at creation. The check prints this (and exits 3) instead of letting three lanes fail silently: `docker compose run --rm -T sprout-app python /app/docker/milvus_cleanup.py`, then re-run. |
| Stale counts in Milvus assertions | Same cause as above, or leftovers from an interrupted run: drop the collections with `milvus_cleanup.py`. |
