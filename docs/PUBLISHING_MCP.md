# Publishing the MCP server to the official registry

Everything that could be automated is done and committed. What remains needs
your credentials — PyPI and GitHub — so it has to be you.

## State: ready

| item | status |
|---|---|
| `server.json` at repo root, schema `2025-12-11` | done |
| `mcp-name` ownership marker in README | done |
| Version 0.1.2 in `pyproject.toml` + `server.json` (all three places) | done |
| `sqlbench-mcp` console entry point | done |
| Server moved into the package so it ships in the wheel | done |
| Read tools work with no API running (in-process ASGI) | done, verified |
| `taxonomy.yaml` shipped as package data | done, was silently missing |
| Wheel built at `dist/sqlbenchdag-0.1.2-py3-none-any.whl` | done |
| Clean-install verification over real MCP stdio protocol | done, 10 tools |
| 8 manifest tests guarding version/name/packaging drift | done |
| **Publish to PyPI** | **yours** |
| **Publish to MCP registry** | **yours** |

## What was verified, and how

Not "it imports" — a clean venv outside the repo, installing the built wheel,
driven over the actual MCP protocol:

```
initialize      -> sql-benchmarks
tools/list      -> 10 tools
tools/call      -> list_categories returns real taxonomy data
```

That test is what caught the missing `taxonomy.yaml`. Four of five catalog
tools were returning `[]` from a clean install while working perfectly inside
the repo.

## Step 1 — publish to PyPI (yours: needs your token)

The registry resolves `sqlbenchdag==0.1.2` on PyPI. **It must exist there
first** or the listing points at nothing.

```bash
cd ~/Projects/sql-benchmarks-dagster
uv build --wheel
uv publish dist/sqlbenchdag-0.1.2-py3-none-any.whl
```

Note `uv build` rather than `python -m build` — the repo has a local `build/`
directory that shadows the `build` module.

Verify it landed:

```bash
pip index versions sqlbenchdag
```

## Step 2 — install the publisher CLI (yours: Homebrew)

Not installed here, and there's no Go toolchain, so Homebrew is the path:

```bash
brew install mcp-publisher
```

## Step 3 — authenticate (yours: GitHub)

The namespace `io.github.rctruta/sqlbenchdag` is claimed by proving you control
the GitHub account. Opens a browser:

```bash
mcp-publisher login github
```

## Step 4 — publish

```bash
cd ~/Projects/sql-benchmarks-dagster
mcp-publisher publish
```

It reads `server.json` from the current directory, checks the README marker
against `name`, and submits.

## Step 5 — verify the listing

```bash
curl -s "https://registry.modelcontextprotocol.io/v0/servers?search=sqlbenchdag" | jq
```

## If publish fails

- **"authentication"/"namespace"** — usually the README marker, not your login.
  It must read exactly `<!-- mcp-name: io.github.rctruta/sqlbenchdag -->` and
  match `name` in `server.json`. `test_readme_ownership_marker_matches_server_name`
  guards this locally.
- **"package not found"** — PyPI hasn't propagated, or step 1 was skipped.
  `packages[].version` must exist on PyPI.
- **schema errors** — the `$schema` URL in `server.json` is the authority; the
  version in it (`2025-12-11`) is dated and will move.

## What users get

`uvx sqlbenchdag` (or install + `sqlbench-mcp`) gives a working benchmark lab
with **no API server and no setup**: 76 SQL suites, the category taxonomy,
templates, and the recommendation engine.

`list_results` is empty until they point `SB_RESULTS_DIR` at a capsule
directory — capsules are run output, deliberately not shipped. That's
documented in `server.json` so it reads as configuration rather than breakage.

`submit_experiment` refuses without `SB_API_BASE`, with a message explaining
why: it needs a process outliving the request, which an in-process mount
cannot provide.

## Releasing after the first time — automated

`.github/workflows/release.yml` does the whole thing on a version tag. No
tokens: both PyPI and the registry authenticate with OIDC, so nothing
long-lived is stored.

```bash
# bump pyproject.toml AND both places in server.json, commit, then:
git tag v0.1.3 && git push origin v0.1.3
```

Or run it from the Actions tab with `dry_run: true` to exercise every check
and publish nothing.

The workflow gates before it publishes, because a PyPI version can never be
reused and a bad release can only be yanked:

1. full test suite
2. tag matches the version in `pyproject.toml`
3. wheel built, then **installed into a clean venv and its tools called** —
   this is what catches missing package data, which is invisible from inside
   the repo
4. `mcp-publisher validate` — free, no auth, catches schema problems like the
   100-character description limit before anything is attempted
5. PyPI, then **wait for it to be servable**, then the registry — that order
   matters, because the registry entry resolves the PyPI version and the
   reverse order publishes a listing nobody can install

### One-time setup on PyPI

Project `sqlbenchdag` → Publishing → add a GitHub publisher:

| field | value |
|---|---|
| owner | `rctruta` |
| repository | `sql-benchmarks-dagster` |
| workflow | `release.yml` |
| environment | *(leave blank)* |

Nothing to configure for the MCP registry — the `io.github.rctruta/*`
namespace is claimed by the OIDC claim proving the workflow runs in an
`rctruta` repo.

**Trusted publishing binds to the exact repo and workflow filename.** Rename
either and it breaks with an error that looks like authentication. If a
release suddenly fails after a rename, check that first.