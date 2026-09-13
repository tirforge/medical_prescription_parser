# Contributing

1. Fork, branch `feat/...`, `pip install -r requirements.txt`
2. Run `python -m py_compile prescription.py && python eval_accuracy.py` before PR
3. Add tests in `tests/` for new logic
4. Never commit `keys.py` / `.env` / `*.bak` / `Check_*` — they are ignored
5. For UI changes, test both light+dark themes and mobile width (360px)
