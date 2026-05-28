web: streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
api: uvicorn oauth_server:app --host 0.0.0.0 --port 8000
worker: python scheduler.py
