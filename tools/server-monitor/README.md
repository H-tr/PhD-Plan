# Server monitor

The agent behind the planner's **Resources** tab. `plan_monitor.py` samples CPU, memory, disks, GPUs (through `nvidia-smi`), and who is using them, every 2 seconds. It serves the numbers as JSON on `127.0.0.1:9101`. `tailscale serve` publishes that port over HTTPS to your tailnet and nowhere else, and the page polls it every 3 seconds while the tab is open.

- Standard library Python 3 only; runs as an ordinary user and never executes anything a request asks for.
- Answers browsers only from `https://h-tr.github.io` (`--origin` to change), including Chrome's private-network preflight.
- `GET /metrics`: the latest snapshot. `GET /history`: the last 30 minutes at 10-second steps.

## Install on a server

```sh
curl -fsSL https://raw.githubusercontent.com/H-tr/PhD-Plan/main/tools/server-monitor/install.sh | bash -s -- --userspace-tailscale
```

- **No root:** `--userspace-tailscale` downloads Tailscale into `~/.local/share/plan-monitor/` and runs it in userspace-networking mode. Leave the flag out where Tailscale is already installed system-wide.
- **Persistence:** cron (`@reboot` and every 5 minutes) restarts whatever has stopped.
- **Finishing:** the installer prints two commands to finish with:
  - `tailscale up --hostname=<name>` (open the login link it shows);
  - `tailscale serve --bg 9101`.
- **Last step:** add `<name> https://<name>.<your-tailnet>.ts.net` under *Edit servers* on the Resources tab.

## Once for the tailnet

- In the [admin console → DNS](https://login.tailscale.com/admin/dns), turn on MagicDNS and HTTPS certificates.
- Disable key expiry for each server.
- Keep Tailscale switched on on the devices you view the page from.

## Day to day

- **Check one server:** `python3 ~/.local/share/plan-monitor/plan_monitor.py --once` prints a snapshot.
- **Logs:** `~/.local/share/plan-monitor/agent.log` and `tailscaled.log`.
- **Remove:**
  1. Run `crontab -e` and delete the two `plan-monitor` lines.
  2. Run `pkill -f plan_monitor.py` and `pkill -f plan-monitor/bin/tailscaled`.
  3. Delete `~/.local/share/plan-monitor`, and remove the machine in the Tailscale console.
- **Rules:** shared lab machines fall under the lab's and NUS IT's rules, so check that running Tailscale there is allowed.
