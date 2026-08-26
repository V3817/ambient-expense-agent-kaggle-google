FROM python:3.11-slim

WORKDIR /app

# Install dependencies directly
RUN pip install --no-cache-dir \
    fastapi>=0.110.0 \
    uvicorn>=0.29.0 \
    "google-adk[gcp]>=2.0.0,<3.0.0" \
    "google-cloud-aiplatform>=1.156.0" \
    jinja2>=3.1.2

# Copy the application code
COPY . .

# Run the FastAPI application on port 8080 (default for Cloud Run)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
