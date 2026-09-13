FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Website is static html (rx-prescription-app.html) — serve via api or any static host.
# Streamlit kept as fallback internal tool; primary backend is FastAPI on 8000.
EXPOSE 8000 8501
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
