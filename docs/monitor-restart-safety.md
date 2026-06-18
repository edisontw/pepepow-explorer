# PEPEPOW Monitor Restart Safety Note

This host runs the public explorer and the monitor side by side. Monitor-only fixes must not restart unrelated services.

## Service layout

- Explorer main service: Node.js, usually listening on port 3001.
- nginx: public reverse proxy on ports 80 and 443.
- Monitor service: FastAPI / uvicorn, listening on 127.0.0.1:8010.
- Explorer sync jobs may run separately. They are not part of the monitor restart path.

## Safe rule

For monitor-only changes, touch only the uvicorn process that is bound to 127.0.0.1:8010.

Do not restart the whole server, nginx, npm, pm2, the explorer node process, or explorer sync jobs for monitor-only updates.

## Safe workflow summary

1. Check current processes and listening ports.
2. Confirm the monitor process is the uvicorn process bound to 127.0.0.1:8010.
3. Check git status before pulling.
4. Pull the repository only when local changes are understood.
5. Run Python compile checks for monitor files before restarting.
6. Stop only the monitor uvicorn process bound to 127.0.0.1:8010.
7. Start only the monitor uvicorn process from the monitor virtual environment.
8. Verify health and monitor API responses.

## Monitor verification endpoints

The monitor currently exposes these API routes under `/api`:

- `/api/status`
- `/api/masternodes`
- `/api/fork`
- `/api/hashrate`
- `/api/peers`
- `/api/blocks/recent`
- `/api/alerts`
- `/api/health`

`/api/snapshot` is not a valid route unless it is added later.

## Strong warning

For monitor-only fixes, do not restart nginx, npm, pm2, the explorer node process, or sync jobs. Those actions can interrupt explorer service or chain sync.
