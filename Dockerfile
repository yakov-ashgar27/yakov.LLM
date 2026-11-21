FROM python:3.12-slim
# git is used to pull repositories when GitHub sync finds a new or changed project
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "pypdf>=4"
WORKDIR /app
COPY yakovllm ./yakovllm
COPY web ./web
COPY data ./data
ENV PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health')"
CMD ["python", "-m", "yakovllm"]
