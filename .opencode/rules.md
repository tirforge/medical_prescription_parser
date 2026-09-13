# Kill rule — never use `pkill -f "uvicorn|streamlit"`

`pkill -f` scans `/proc` and matches its own `zsh -c pkill ...` line, causing 60-120s hang (seen 2026-09-13).

Use port-based kill:

```bash
fuser -k 8000/tcp 2>/dev/null || lsof -ti:8000 | xargs -r kill -9 2>/dev/null || kill $(cat /tmp/uvicorn.pid 2>/dev/null) 2>/dev/null || true
fuser -k 8501/tcp 2>/dev/null || lsof -ti:8501 | xargs -r kill -9 2>/dev/null || kill $(cat /tmp/streamlit.pid 2>/dev/null) 2>/dev/null || true
```

Or `make stop` / `make run` (see Makefile). Always `workdir` param, never `cd &&`.
