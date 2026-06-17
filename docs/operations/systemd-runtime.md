# PEPEPOW Explorer systemd Runtime Operations

To ensure operational reliability and persistence across reboots or terminal closures, the PEPEPOW explorer runtime has been migrated from manually run `screen` sessions to managed `systemd` services.

---

## Services Overview

The explorer environment consists of the following systemd services:

1. **`mongod.service`**: MongoDB Database Server. Persistent, auto-starts on boot.
2. **`pepepow-explorer.service`**: The main Node.js web application for the eIquidus explorer (running on port `3001`).
3. **`pepepow-explorer-sync.service`**: Long-running bash script (`sync.sh`) that triggers block, peer, market, and masternode synchronization loops.
4. **`pepepow-explorer-monitor.service`**: Independent health monitor service (listening on port `8010`, proxied at `/monitor`).

---

## Service Management Commands

### Check Status of All Services
```bash
sudo systemctl status mongod pepepow-explorer pepepow-explorer-sync pepepow-explorer-monitor --no-pager
```

### Restart a Service
```bash
sudo systemctl restart pepepow-explorer
sudo systemctl restart pepepow-explorer-sync
```

### View Live Logs
```bash
# View recent logs
sudo journalctl -u pepepow-explorer -n 100 --no-pager
sudo journalctl -u pepepow-explorer-sync -n 100 --no-pager

# Follow logs in real-time
sudo journalctl -u pepepow-explorer -f
sudo journalctl -u pepepow-explorer-sync -f
```

---

## Service Configuration Templates

Copies of the systemd service files are stored in the repository for reference and deployment:
- [pepepow-explorer.service](file:///home/ubuntu/explorer/docs/operations/pepepow-explorer.service)
- [pepepow-explorer-sync.service](file:///home/ubuntu/explorer/docs/operations/pepepow-explorer-sync.service)

To redeploy or update them:
```bash
sudo cp docs/operations/pepepow-explorer*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart pepepow-explorer pepepow-explorer-sync
```

---

## Emergency Screen Fallback (Emergency Use Only)

If systemd services need to be disabled or customized in a pinch, the legacy screen fallback is documented below.

### 1. Stop systemd services:
```bash
sudo systemctl disable --now pepepow-explorer pepepow-explorer-sync
```

### 2. Start using screen:
- **Explorer**:
  ```bash
  screen -S eIquidus
  cd /home/ubuntu/explorer
  npm start
  # Press Ctrl+A, then D to detach
  ```
- **Sync**:
  ```bash
  screen -dmS Sync /home/ubuntu/explorer/sync.sh
  ```
