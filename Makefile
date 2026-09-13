.PHONY: run run-api run-streamlit stop stop-api stop-streamlit restart logs health

# Preferred kill: fuser/lsof on ports (instant, no pkill scan hang)
# Never use `pkill -f "uvicorn|streamlit"` — it matches its own zsh -c line and stalls.

API_PORT ?= 8000
STREAMLIT_PORT ?= 8501

run: run-api

run-api:
	GOOGLE_API_KEY=$$(python3 -c "import keys; print(keys.GOOGLE_API_KEY)" 2>/dev/null || echo "") \
	nohup python3 -m uvicorn api:app --host 0.0.0.0 --port $(API_PORT) > /tmp/uvicorn.log 2>&1 & echo $$! > /tmp/uvicorn.pid; \
	echo "api http://127.0.0.1:$(API_PORT)/ (log /tmp/uvicorn.log pid $$(cat /tmp/uvicorn.pid))"

run-streamlit:
	nohup python3 -m streamlit run prescription.py --server.port $(STREAMLIT_PORT) --server.headless true --server.address 0.0.0.0 > /tmp/streamlit.log 2>&1 & echo $$! > /tmp/streamlit.pid; \
	echo "streamlit http://127.0.0.1:$(STREAMLIT_PORT)/ (log /tmp/streamlit.log)"

stop: stop-api stop-streamlit

stop-api:
	-@fuser -k $(API_PORT)/tcp 2>/dev/null || lsof -ti:$(API_PORT) | xargs -r kill -9 2>/dev/null || kill $$(cat /tmp/uvicorn.pid 2>/dev/null) 2>/dev/null || true
	-@rm -f /tmp/uvicorn.pid
	@echo "api stopped"

stop-streamlit:
	-@fuser -k $(STREAMLIT_PORT)/tcp 2>/dev/null || lsof -ti:$(STREAMLIT_PORT) | xargs -r kill -9 2>/dev/null || kill $$(cat /tmp/streamlit.pid 2>/dev/null) 2>/dev/null || true
	-@rm -f /tmp/streamlit.pid
	@echo "streamlit stopped"

restart: stop run

logs:
	@tail -f /tmp/uvicorn.log /tmp/streamlit.log 2>/dev/null

health:
	@curl -s http://127.0.0.1:$(API_PORT)/health | head -c 300; echo
	@curl -s -o /dev/null -w "api HTTP %{http_code}\n" http://127.0.0.1:$(API_PORT)/health
	@test -f rx-prescription-app.html && echo "html rx-prescription-app.html present" || echo "html missing"
