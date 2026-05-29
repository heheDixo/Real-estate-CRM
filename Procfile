web: streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true --server.enableCORS=false --server.enableXsrfProtection=false
api: uvicorn oauth_server:app --host 0.0.0.0 --port ${API_PORT:-8000}
worker: python scheduler.py
