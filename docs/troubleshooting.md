# Troubleshooting

## Model Download Slow or Failed

The embedding model (`all-MiniLM-L6-v2`) is downloaded from HuggingFace on first use. If download is slow:

```bash
# Use HuggingFace mirror (China users)
export HF_ENDPOINT=https://hf-mirror.com
jfox init
```

## Windows Console Encoding

JFox has built-in Windows UTF-8 handling. If you still see garbled text:

```bash
chcp 65001
set PYTHONUTF8=1
```

## Command Not Found

See [Windows PATH](installation.md#windows-path) in the installation guide.

## Index Issues

If search results seem stale or incomplete:

```bash
# Check index status
jfox index status

# Full rebuild
jfox index rebuild

# Verify integrity
jfox index verify
```

## ChromaDB Lock File

If you see errors about ChromaDB lock files, ensure no other `jfox` process is running, then retry. The lock file is auto-cleaned on next startup.
