# Versioned Deployment Documentation Design

## Goal

Make a new Linux or WSL deployment reproducible without requiring the operator to infer compatible Python, OBITools4, MFEprimer, Streamlit, or pandas versions from development history.

The documentation must let an operator:

1. clone an immutable fullpcr release;
2. create a compatible environment;
3. install the external bioinformatics tools;
4. start the GUI with persistent data;
5. verify both the Web service and the five-step analysis environment;
6. upgrade, migrate, or roll back without losing run data.

## Scope

Documentation changes only:

- update `README.md` with a concise recommended deployment entry point;
- add a root-level `DEPLOYMENT.md` containing the complete deployment runbook;
- preserve the existing detailed CLI and scientific usage documentation;
- preserve the existing systemd assets and explain how to use them with either Conda or venv.

No dependency declarations, Python source, service templates, analysis behavior, or output formats are changed by this documentation task.

## Documentation Structure

### README.md

Add a short Chinese section near the dependency/installation material:

- link to `DEPLOYMENT.md`;
- show the tested version matrix;
- show the shortest supported Conda/Mamba deployment path;
- warn that MFEprimer 4.3.1 is not currently compatible;
- keep local start and LAN start commands visible;
- direct advanced systemd, migration, troubleshooting, and rollback users to the dedicated runbook.

Existing long deployment sections should be reduced to links or clearly marked as the venv/systemd alternative so that two competing “recommended” procedures do not remain.

### DEPLOYMENT.md

Use this order:

1. supported platforms and prerequisites;
2. tested version matrix and compatibility policy;
3. recommended Conda/Mamba installation;
4. MFEprimer 4.2.4 installation from the official release;
5. cloning and checking out `v0.1.0`;
6. installing pinned Python GUI packages and fullpcr;
7. persistent data directory and permissions;
8. local-only and trusted-LAN startup commands;
9. environment and HTTP acceptance checks;
10. one real five-step analysis acceptance requirement;
11. background service alternatives, including systemd PATH handling for a Conda environment;
12. data migration, upgrade, rollback, and troubleshooting;
13. security boundaries.

## Version Policy

The reference deployment is the environment that passed the current full test suite and real application checks:

| Component | Pinned reference version | Policy |
|---|---:|---|
| fullpcr | 0.1.0 / Git tag `v0.1.0` | Deploy the immutable tag, not an arbitrary moving branch |
| Python | 3.13.14 | Recommended exact Conda version; package metadata continues to declare Python >= 3.10 |
| OBITools4 | 4.4.46 | Pin in the recommended Conda command |
| MFEprimer | 4.2.4 | Required exact version for the current parser and index contract |
| Streamlit | 1.59.1 | Pin in the reference deployment command |
| pandas | 3.0.3 | Pin in the reference deployment command |

The runbook must distinguish “tested reference version” from “broad package metadata support.” Newer versions are not automatically certified merely because installation succeeds.

MFEprimer 4.3.1 must be called out explicitly as unsupported for this release because it introduces `.primerqc.bin` and additional Spec TSV columns. The runbook must tell operators to verify `mfeprimer version` and install 4.2.4 rather than using the latest release link.

## Recommended Conda/Mamba Flow

The primary workflow targets Linux x86_64 servers and WSL:

1. install Miniforge/Conda or Mamba using the organization-approved method;
2. clone `git@github.com:ala-Lisa/fullpcr.git` or the HTTPS equivalent;
3. check out `v0.1.0`;
4. create a dedicated `fullpcr` environment with Python 3.13.14 and OBITools4 4.4.46 from conda-forge/Bioconda;
5. install the official MFEprimer 4.2.4 binary for the detected architecture into that environment’s `bin` directory;
6. install Streamlit 1.59.1, pandas 3.0.3, and fullpcr 0.1.0 from the checked-out source;
7. run version and import checks before starting the GUI.

Commands must avoid editable installation for production. Development installation remains documented separately.

## venv and systemd Alternative

The existing venv/systemd path remains supported as an advanced alternative. The runbook must make clear that:

- venv installs only the Python application and GUI dependencies;
- `obipcr` and `mfeprimer` remain external executables;
- `/etc/fullpcr/fullpcr.env` must include both the application environment and external-tool directories in `PATH`;
- the service user must own or be able to write the persistent data directory;
- systemd success is insufficient unless the external-tool version checks and a real five-step analysis also pass.

For Conda-backed systemd, documentation should use the environment’s absolute Python path or an explicit environment `PATH`; it must not depend on an interactive `conda activate` inside the service.

## Acceptance and Error Handling

The runbook must separate three levels of success:

1. **Environment acceptance:** imports and exact tool versions match the reference matrix.
2. **Web acceptance:** `/_stcore/health` returns `ok` and `/` returns HTTP 200.
3. **Analysis acceptance:** one small real five-step run completes and generates the final report.

Each troubleshooting entry should start from observable evidence:

- environment indicator red: run the exact version/import commands;
- Web opens but Spec fails: compare `mfeprimer version`, executable path, and raw error dialog;
- LAN access fails: inspect bind address, server LAN IP, firewall, and WSL networking mode;
- historical results disappear: verify the persistent data-directory argument and permissions;
- service works interactively but not under systemd: inspect the service user and `PATH`.

## Release and Git Plan

After documentation and the already-verified feature changes pass validation:

1. commit the feature/test changes and documentation without modifying Git history;
2. push `main` to `origin`;
3. create an annotated `v0.1.0` tag matching `pyproject.toml`;
4. push the tag to `origin`;
5. verify that local `main`, `origin/main`, and the tag resolve to the intended release commit.

No force push, history rewrite, or unrelated file cleanup is allowed.

## Validation

Before release:

- inspect every documented command for correct paths, quoting, and activation assumptions;
- verify official release and package links;
- verify the documented local environment reports the pinned versions;
- run the deployment-asset tests and full test suite;
- run `python3 -m compileall -q fullpcr`;
- run `git diff --check`;
- audit `git status --short` and the complete staged diff before committing;
- after push, verify remote branch and tag references.

## Non-goals

- no Docker or Kubernetes deployment in this release;
- no automatic dependency installer in application code;
- no authentication, TLS, reverse-proxy, or firewall automation;
- no MFEprimer 4.3.1 parser/index compatibility work;
- no changes to current algorithms, GUI behavior, CLI semantics, output data, or systemd templates.
