# Pocketful — stage 1

Wallet and payments HTTP API (Node.js 22, standard library only, in-memory state).

## Build and start

```sh
docker build -t pocketful-s1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s1
```

The service listens on `0.0.0.0:$PORT` (default `8080`) and answers `GET /health` with
`200 {"status":"ok"}` within a second of start. It needs no network at run time.

## Unit tests (domain rules and state replacement; loopback only, no network)

```sh
docker run --rm --network none pocketful-s1 node --test
```

or, with Node.js 20+ installed locally, `node --test` from this folder.

## Layout

- `src/domain/` — pure rules: field validation, handle derivation, equal split, net affordability, canonical JSON
- `src/state/` — in-memory store, reset fixture loader, export/import, password hashing (scrypt)
- `src/services/` — auth, payments/requests/splits/feed, settlements, idempotency
- `src/transport/` — HTTP server, body parsing, error envelope, route table
- `test/` — unit tests for the domain rules, password hashing and reset/signup ordering
