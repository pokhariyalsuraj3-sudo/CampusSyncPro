import os

# Gunicorn configuration for Render deployment
port = os.environ.get("PORT", "10000")
bind = f"0.0.0.0:{port}"
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
timeout = 120
accesslog = "-"
errorlog = "-"
