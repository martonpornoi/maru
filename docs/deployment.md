# Deployment Checklist

Use this checklist before running maru outside local development.

## Required Environment

Set these values explicitly:

```bash
MARU_DEBUG=0
MARU_SECRET_KEY="a-long-random-secret"
MARU_ALLOWED_HOSTS="events.example.org"
MARU_DB="/path/to/production/database"
MARU_GOOGLE_OAUTH_CLIENT_ID="google-client-id"
MARU_GOOGLE_OAUTH_CLIENT_SECRET="google-client-secret"
MARU_GOOGLE_OAUTH_REDIRECT_URI="https://events.example.org/oauth/google/callback/"
MARU_CSRF_TRUSTED_ORIGINS="https://events.example.org"
```

When `MARU_DEBUG=0`, the development email login is disabled even if
`MARU_DEV_LOGIN_ENABLED=1` is present.

## Security Defaults

Production defaults enable:

- HTTPS redirect
- secure session cookies
- secure CSRF cookies
- HTTP Strict Transport Security
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: same-origin`

If the app is behind a reverse proxy, make sure the proxy sends
`X-Forwarded-Proto: https`.

## Preflight Commands

Run these commands before deploying a new version:

```bash
uv run --extra dev python manage.py migrate
uv run --extra dev python manage.py check --deploy
uv run --extra dev pytest -q -s tests
uv run --extra dev ruff check .
```

## Operational Checks

- Verify the Google OAuth redirect URI exactly matches the deployed URL.
- Verify `marton.pornoi@gmail.com` or another Admin account can log in with
  Google OAuth.
- Verify `/accounts/` is visible only to Admin users.
- Rotate public export tokens before exposing website/signage endpoints.
- Confirm timetable/profile exports expose only intended public data.
