# Local PDS integration harness

This directory holds the Docker setup that backs the live PDS integration
tests. `docker-compose.yml` runs a real bluesky Personal Data Server so the
`lairs` client is exercised against genuine XRPC, blob, and repository
endpoints rather than a mock transport.

The `pds_server` fixture in `tests/conftest.py` manages the container
lifecycle: it generates ephemeral secrets, starts the service, waits for the
`_health` endpoint, creates a throwaway account through
`com.atproto.server.createAccount`, yields the connection details, and tears
the container down afterwards.

## Running

The integration tests are deselected by default. They run only with
`--run-integration`, and skip cleanly when Docker, the image, or the health
check are unavailable:

```bash
uv run pytest --run-integration -m integration -k pds
```

## DID and PLC

A real PDS mints a `did:plc` on account creation through `PDS_DID_PLC_URL`,
which defaults to the public PLC directory. That is the configuration closest
to a real remote PDS, and it requires outbound network access at account
creation. For a fully offline, hermetic run, point `PDS_DID_PLC_URL` at a local
PLC service. The record, blob, and `applyWrites` round trips themselves run
entirely against the local PDS using the session's access token; only account
creation and handle-to-DID resolution depend on the PLC.

## Environment overrides

| Variable | Default | Purpose |
|---|---|---|
| `LAIRS_PDS_IMAGE` | `ghcr.io/bluesky-social/pds:0.4` | PDS image and tag |
| `LAIRS_PDS_PORT` | a free port | host port the PDS is published on; the fixture picks a free one unless this is set |
| `PDS_DID_PLC_URL` | `https://plc.directory` | PLC directory used at account creation |

The `pds_server` fixture selects a free host port automatically, so the
integration suite runs even when another service already holds 3000. Set
`LAIRS_PDS_PORT` to pin a specific port (the compose file alone, run by hand,
still defaults to 3000).

The fixture generates `PDS_JWT_SECRET`, `PDS_ADMIN_PASSWORD`, and
`PDS_PLC_ROTATION_KEY_K256_PRIVATE_KEY_HEX` per session and passes them to the
container; the defaults in the compose file are only for starting the service
by hand.
