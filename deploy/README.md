# Deployment notes

This repository includes Docker scaffolding for a reproducible local or single-host deployment. It is not an automatic cloud deployment and does not contain credentials.

## Before deploying

- Replace SQLite with a managed PostgreSQL/Supabase database for multi-instance hosting.
- Put uploads and clips in object storage; do not rely on a container filesystem.
- Keep the local worker on an always-on machine. A serverless web host cannot process files on a laptop that is turned off.
- Set `API_ACCESS_TOKEN`, restrictive `CORS_ORIGINS`, YouTube OAuth secrets, and a secret-managed token path.
- Use HTTPS for the dashboard and OAuth redirect URL.
- Run a private test upload before enabling public publishing.

## Local container smoke run

```powershell
Copy-Item backend/.env.example backend/.env
docker compose up --build
```

The deployment remains intentionally conservative: cloud publishing, Supabase migration, object storage, and domain/OAuth configuration require explicit operator choices.
