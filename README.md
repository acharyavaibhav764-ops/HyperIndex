# Honeywell Project

## Environment Setup

Follow these steps to run the current development environment locally.

### 1. Install prerequisites

Install the following tools:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Git
- `curl` or another HTTP client for testing the API

After installing Docker Desktop, open it and confirm that the Docker engine is running.

### 2. Open the project

Clone the repository and move into the project directory:

```powershell
git clone <repository-url>
Set-Location HONEYWELL
```

If the repository is already available locally, open a terminal in its root directory, beside `docker-compose.yml`.

### 3. Create the environment file

Create a file named `.env` in the project root. Use local development credentials such as:

```dotenv
POSTGRES_USER=postgres
POSTGRES_PASSWORD=change-me
POSTGRES_DB=honeywell
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=change-me-too
```

Replace the example values with your own local credentials. Never commit `.env` or production credentials to source control.

### 4. Validate the configuration

From the project root, run:

```powershell
docker compose config
```

This confirms that Docker Compose can read the environment variables and render the service configuration successfully.

### 5. Build and start the services

Start PostgreSQL, MinIO, and the FastAPI backend:

```powershell
docker compose up --build
```

Keep this terminal open to view live logs. To start the services in the background, use:

```powershell
docker compose up --build -d
```

The services are available at:

| Service | Address |
| --- | --- |
| FastAPI backend | `http://localhost:8000` |
| FastAPI Swagger UI | `http://localhost:8000/docs` |
| FastAPI ReDoc | `http://localhost:8000/redoc` |
| MinIO API | `http://localhost:9000` |
| MinIO Console | `http://localhost:9001` |
| PostgreSQL | `localhost:5432` |

### 6. Verify the backend

Check that the API is responding:

```powershell
curl http://localhost:8000/docs
```

Upload a document. Replace the path with a real local file:

```powershell
curl.exe -X POST http://localhost:8000/upload -F "file=@C:\path\to\sample.pdf"
```

Retrieve metadata for the uploaded file:

```powershell
curl.exe http://localhost:8000/metadata/sample.pdf
```

The backend creates the `honeywell-documents` bucket in MinIO when it starts.

### 7. View service logs

View logs for all services:

```powershell
docker compose logs -f
```

View only backend logs:

```powershell
docker compose logs -f backend-dev
```

### 8. Stop the environment

Stop the running containers while preserving local database and object-storage data:

```powershell
docker compose down
```

To stop the containers and delete the persisted local volumes:

```powershell
docker compose down --volumes
```

## Current Services

The development stack currently contains:

- **PostgreSQL:** relational database service
- **MinIO:** S3-compatible object storage for uploaded documents
- **FastAPI backend:** document upload and metadata API

Document parsing, embeddings, vector search, and the frontend are planned parts of the wider product and are not yet included in the current development stack.

