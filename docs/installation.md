# Installation

## Recommended: uv

```bash
# Clone and install for local development
git clone https://github.com/zhuxixi/jfox.git
cd jfox
uv sync --extra dev

# Or install as a global tool
uv tool install "git+https://github.com/zhuxixi/jfox.git"

# Try without installing
uvx --from "git+https://github.com/zhuxixi/jfox.git" jfox --help
```

Verify:

```bash
jfox --help
jfox --version
```

## Legacy: pip

```bash
pip install -e ".[dev]"
```

## Uninstall

```bash
# uv users
uv tool uninstall jfox-cli

# pip users
pip uninstall jfox-cli
```

## Requirements

- Python >= 3.10
- Dependencies: typer, rich, sentence-transformers, chromadb, networkx, watchdog, pyyaml, fastapi, uvicorn

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
