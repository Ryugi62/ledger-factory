# Pocketful — stage 4

Wallet and payments service with browser screens, payment authorizations (holds and captures), historical
balances (`GET /me?as_of=&known_at=`), paginated statements with snapshots (`GET /statement`), bitemporal
payment corrections (`POST /payments/{id}/corrections`, `GET /payments/{id}/revisions`), refunds
(`POST /payments/{id}/refunds`) and operator correction batches (`POST /correction-batches`).
Node.js 22, standard library only, in-memory state. The UI is plain HTML/CSS/JavaScript served by the
service itself (system fonts, no external resources), so it works with no network at run time.

## Build and start

```sh
docker build -t pocketful-s4 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s4
```

The service listens on `0.0.0.0:$PORT` (default `8080`). `GET /health` answers `200 {"status":"ok"}`
within a second of start. Open <http://localhost:8080/login> in a browser after a `POST /_test/reset`.

Screens: `/` (wallet: balance, pay, request, activity), `/requests`, `/split`, `/authorizations` (holds),
`/login`, `/signup`. `/requests` and `/authorizations` return the screen for `Accept: text/html` and JSON
otherwise.

## Unit tests (domain rules, holds, instants, bitemporal views, corrections, statements, refunds, batches; loopback only, no network)

```sh
docker run --rm --network none pocketful-s4 node --test
```

or, with Node.js 20+ installed locally, `node --test` from this folder.

## Layout

- `src/domain/` — pure rules: field validation, handle derivation, equal split, net affordability, canonical JSON, RFC 3339 instants
- `src/state/` — in-memory store (balances, opening balances, payment revisions, holds and their lifecycle), reset fixture loader, export/import (accepts stage-1, stage-2 and stage-3 exports; carries saved statement snapshots), scrypt passwords
- `src/services/` — auth, payments/requests/splits/feed, authorizations/captures, settlements, idempotency, history (bitemporal views), statements/snapshots, corrections, refunds, correction batches
- `src/transport/` — HTTP server, body parsing, error envelope, route table, UI/static serving
- `src/ui/` — browser client: `index.html` shell and `assets/` (router, screens, API client, money formatting, stylesheet)
- `test/` — unit tests
