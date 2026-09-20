# Installation

## Recommended: uv

### Default install (lightweight, CPU-friendly)

```bash
# Install as a global tool: note CRUD, BM25 keyword search, and the knowledge
# graph. No semantic vector search — no torch/CUDA download, zero nvidia
# dependencies on CPU-only machines.
uv tool install "jfox-cli"

# Or install from source
uv tool install "git+https://github.com/zhuxixi/jfox.git"

# Try without installing
uvx --from "git+https://github.com/zhuxixi/jfox.git" jfox --help
```

### Semantic search component (optional)

```bash
# GPU machines
uv tool install "jfox-cli[embed]"

# CPU-only machines (UV_TORCH_BACKEND=cpu makes uv resolve the CPU torch
# build, no CUDA)
UV_TORCH_BACKEND=cpu uv tool install "jfox-cli[embed]"

# pip users (on CPU machines run first: pip install torch --index-url
# https://download.pytorch.org/whl/cpu)
pip install "jfox-cli[embed]"
```

### For local development

```bash
# Clone and install for local development
git clone https://github.com/zhuxixi/jfox.git
cd jfox
uv sync --extra dev --extra embed
```

Verify:

```bash
jfox --help
jfox --version
```

## Legacy: pip

```bash
pip install -e ".[dev,embed]"
```

## Upgrade

```bash
# Auto-detect installation method and upgrade
jfox update

# JSON output with version info
jfox update --json
```

If `jfox update` fails (e.g. behind a proxy or on an unsupported install method), use the manual command for your install method:

```bash
# uv tool users
uv tool upgrade jfox-cli

# pipx users
pipx upgrade jfox-cli

# pip users
pip install --upgrade jfox-cli

# Development mode (git clone + uv sync --extra dev --extra embed)
git pull && uv sync --extra dev --extra embed
```

### Upgrading from 1.x

Starting with 2.0, the default install no longer bundles the semantic search component. An in-place upgrade (pip/uv do not uninstall existing packages) usually keeps working unchanged; after rebuilding an environment, jfox prints the same install hint the first time a semantic feature is used. After installing the `[embed]` component, run `jfox index rebuild` to backfill the semantic index.

## Uninstall

```bash
# uv users
uv tool uninstall jfox-cli

# pip users
pip uninstall jfox-cli
```

## Requirements

- Python >= 3.10
- Core dependencies: typer, rich, chromadb, networkx, watchdog, pyyaml, fastapi, uvicorn
- Optional `[embed]` extra: sentence-transformers (+ torch) — required only for semantic vector search

## Windows PATH

If `jfox` command is not found after installation:

**uv users:**

```powershell
# Check uv tool install path
uv tool dir
# Add the corresponding bin directory to PATH
```

**pip users:**

```powershell
# Check install location
pip show jfox-cli | findstr Location
# Add the Scripts directory to PATH, e.g.:
# C:\Users\<user>\AppData\Local\Packages\PythonSoftwareFoundation.Python3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts
```

## HuggingFace Mirror (China)

```bash
export HF_ENDPOINT=https://hf-mirror.com
jfox init
```
