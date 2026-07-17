# Versioned Deployment Documentation Implementation Plan

> **For Claude Code:** Follow this plan step by step. Do not modify runtime code, tests, dependency metadata, or systemd templates as part of this documentation task.

**Goal:** Make a fresh-machine deployment reproducible by documenting one recommended Conda/Mamba path with pinned, verified tool versions, plus the existing venv/systemd path as an optional production alternative.

**Architecture:** Keep `README.md` as the short entry point. Put exact commands, version compatibility, validation, LAN access, data persistence, upgrades, and troubleshooting in a new root-level `DEPLOYMENT.md`. Preserve the existing deployment documentation strings required by `tests/test_deployment_assets.py`.

**Reference stack:** fullpcr 0.1.0 (`v0.1.0`), Python 3.13.14, OBITools4 4.4.46, MFEprimer 4.2.4, Streamlit 1.59.1, pandas 3.0.3.

---

## Scope and safety constraints

- Modify only `README.md`, new `DEPLOYMENT.md`, and this plan during the documentation step.
- Do not edit `deploy/systemd/fullpcr.service` or `deploy/systemd/fullpcr.env.example`.
- Do not claim MFEprimer 4.3.1 compatibility; explicitly document it as unsupported for this release.
- Do not remove README phrases checked by `tests/test_deployment_assets.py`, including `绝对路径可以不同`, `--data-dir`, `FULLPCR_DATA_DIR`, `/_stcore/health`, `200`, `obipcr`, `mfeprimer`, `完整分析`, and the no-auth/no-TLS warning.
- Do not overwrite or discard the already verified adaptive-CPU/error-diagnostics worktree changes.
- Never force-push or replace an existing remote tag.

## Task 1: Add the reproducible deployment runbook

**Files:**
- Create: `DEPLOYMENT.md`

1. Add a compatibility table containing the exact reference stack above and explain that the versions are the validated baseline for `v0.1.0`.
2. Add a five-minute Conda/Mamba installation path:
   - clone `https://github.com/ala-Lisa/fullpcr.git` and checkout `v0.1.0`;
   - create `fullpcr` with Python 3.13.14 and OBITools4 4.4.46 from conda-forge/bioconda;
   - install MFEprimer 4.2.4 by CPU architecture with SHA256 verification;
   - pin Streamlit 1.59.1 and pandas 3.0.3;
   - install the local project without dependency re-resolution;
   - verify all executable and Python versions.
3. Use these MFEprimer assets and hashes:
   - x86_64: `mfeprimer-4.2.4-linux-amd64.gz`, `533ea292958ecb0d638dc4c34f664f6e8314e1e12dca2e323b3d6ae0f69968c0`;
   - aarch64/arm64: `mfeprimer-4.2.4-linux-arm64.gz`, `b4c7f42b1241869e98aa954215bf06e097d4e0f9dc84a47c8e2d21e27bd87517`.
4. Add local and LAN launch commands with a persistent data directory. Clarify that `0.0.0.0` is a bind address, not a browser URL.
5. Add health checks for `/_stcore/health` and the root HTTP status.
6. Add input-format, permissions, data migration, upgrade/rollback, systemd, firewall, and troubleshooting sections.
7. Explain the MFEprimer 4.3.1 incompatibility symptoms (`.primerqc.bin` and extra Spec TSV columns) and require 4.2.4 for `v0.1.0`.

**Verification:**

```bash
rg -n "v0\.1\.0|3\.13\.14|4\.4\.46|4\.2\.4|1\.59\.1|3\.0\.3|533ea292|b4c7f42b" DEPLOYMENT.md
rg -n "0\.0\.0\.0|/_stcore/health|FULLPCR_DATA_DIR|MFEprimer 4\.3\.1|systemd" DEPLOYMENT.md
```

Expected: every pinned version, both hashes, health checks, persistence configuration, incompatibility warning, and production-service route are present.

## Task 2: Turn README into a concise deployment entry point

**Files:**
- Modify: `README.md`

1. Add a prominent `v0.1.0` deployment section near the dependency/install material.
2. Show a short recommended Conda/Mamba flow and link to `DEPLOYMENT.md` for full commands and troubleshooting.
3. Add the validated version matrix or a compact summary of it.
4. Keep existing GUI, LAN/WSL, migration, security, and systemd documentation intact unless a small correction is required to avoid contradiction.
5. Retain all strings covered by `tests/test_deployment_assets.py`.

**Verification:**

```bash
python3 -m pytest -q tests/test_deployment_assets.py
rg -n "DEPLOYMENT\.md|v0\.1\.0|Conda|Mamba|MFEprimer 4\.2\.4" README.md
```

Expected: deployment tests pass and the README points a new operator to the pinned runbook without duplicating it in full.

## Task 3: Validate and commit the release candidate

**Files:**
- Verify all tracked and intended untracked project files.

1. Inspect `git diff`, `git diff --cached`, and `git status --short`; confirm no unrelated file is included.
2. Run:

```bash
python3 -m pytest -q tests/test_deployment_assets.py
python3 -m pytest -q
python3 -m compileall -q fullpcr
git diff --check
```

3. Confirm the local reference environment versions:

```bash
/home/a8/miniforge3/envs/obitools4/bin/python --version
/home/a8/miniforge3/envs/obitools4/bin/python -c 'from importlib.metadata import version; print(version("fullpcr"), version("pandas"), version("streamlit"))'
/home/a8/miniforge3/envs/obitools4/bin/mfeprimer version
/home/a8/miniforge3/envs/obitools4/bin/obipcr --version
```

4. Commit the already verified adaptive-CPU/error-diagnostics implementation and its matching tests/design documents as one feature commit.
5. Commit `README.md`, `DEPLOYMENT.md`, and this plan as one documentation commit. The deployment design specification is already committed separately.

**Stop condition:** If any test fails, the diff contains unrelated changes, or the version evidence contradicts the runbook, do not commit or push; report the exact blocker.

## Task 4: Push main and publish the immutable release tag

1. Verify no local or remote `v0.1.0` tag already exists.
2. Push `main` normally; never force-push.
3. Create annotated tag `v0.1.0` with message `fullpcr 0.1.0` on the verified documentation commit.
4. Push the tag.
5. Fetch and verify that local `HEAD`, `origin/main`, and dereferenced `v0.1.0^{}` identify the same commit.

**Verification:**

```bash
git status --short
git rev-parse HEAD
git rev-parse origin/main
git rev-parse 'v0.1.0^{}'
git ls-remote --tags origin refs/tags/v0.1.0 refs/tags/v0.1.0^{}
```

Expected: worktree is clean, branch and tag are published, and all three commit IDs match.
