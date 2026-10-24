#!/usr/bin/env bash
# Installs the PhD Plan usage agent for the current user (no root) and keeps it running with cron.
#
#   bash install.sh [--userspace-tailscale] [--hostname NAME] [--port 9101] [--origin https://h-tr.github.io]
#
# or straight from GitHub:
#   curl -fsSL https://raw.githubusercontent.com/H-tr/PhD-Plan/main/tools/server-monitor/install.sh | bash -s -- --userspace-tailscale
#
# --userspace-tailscale  also download Tailscale into ~/.local/share/plan-monitor and run it as this user in
#                        userspace-networking mode (for machines where you have no root). Leave it out where
#                        Tailscale is already installed system-wide.
set -euo pipefail
PORT=9101
ORIGIN=https://h-tr.github.io
USERSPACE=0
NAME=$(hostname -s)
RAW=https://raw.githubusercontent.com/H-tr/PhD-Plan/main/tools/server-monitor
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT=$2; shift 2 ;;
    --origin) ORIGIN=$2; shift 2 ;;
    --hostname) NAME=$2; shift 2 ;;
    --userspace-tailscale) USERSPACE=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
command -v python3 >/dev/null || { echo "python3 is needed" >&2; exit 1; }
fetch() { python3 -c 'import sys,urllib.request; sys.stdout.buffer.write(urllib.request.urlopen(sys.argv[1], timeout=60).read())' "$1"; }

DIR="$HOME/.local/share/plan-monitor"
mkdir -p "$DIR/bin"
# private: on a shared server this holds the Tailscale node key and control socket, which other users must not reach
chmod 700 "$DIR"
SRC=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)
if [ -n "$SRC" ] && [ -f "$SRC/plan_monitor.py" ]; then cp "$SRC/plan_monitor.py" "$DIR/"; else fetch "$RAW/plan_monitor.py" > "$DIR/plan_monitor.py"; fi
python3 "$DIR/plan_monitor.py" --once >/dev/null || { echo "the agent could not take a sample; see the error above" >&2; exit 1; }

if [ "$USERSPACE" = 1 ] && [ ! -x "$DIR/bin/tailscaled" ]; then
  case $(uname -m) in x86_64) A=amd64 ;; aarch64|arm64) A=arm64 ;; *) echo "unsupported CPU: $(uname -m)" >&2; exit 1 ;; esac
  TGZ=$(fetch 'https://pkgs.tailscale.com/stable/?mode=json' | python3 -c "import json,sys; print(json.load(sys.stdin)['Tarballs']['$A'])")
  echo "Downloading $TGZ"
  fetch "https://pkgs.tailscale.com/stable/$TGZ" | tar -xz -C "$DIR"
  cp "$DIR"/tailscale_*/tailscale "$DIR"/tailscale_*/tailscaled "$DIR/bin/"
  rm -rf "$DIR"/tailscale_*/
fi

# run.sh starts whatever is not already running; cron calls it at boot and every five minutes.
cat > "$DIR/run.sh" <<EOF
#!/usr/bin/env bash
D="$DIR"
if ! pgrep -u "\$(id -u)" -f "plan_monitor.py --port $PORT" >/dev/null; then
  nohup python3 "\$D/plan_monitor.py" --port $PORT --origin "$ORIGIN" >>"\$D/agent.log" 2>&1 &
fi
EOF
if [ "$USERSPACE" = 1 ]; then cat >> "$DIR/run.sh" <<EOF
if ! pgrep -u "\$(id -u)" -f "\$D/bin/tailscaled" >/dev/null; then
  nohup "\$D/bin/tailscaled" --tun=userspace-networking --statedir="\$D/ts-state" --socket="\$D/ts.sock" --port=0 >>"\$D/tailscaled.log" 2>&1 &
fi
EOF
fi
chmod +x "$DIR/run.sh"
if command -v crontab >/dev/null && { crontab -l 2>/dev/null | grep -v 'plan-monitor/run.sh'; echo "@reboot $DIR/run.sh"; echo "*/5 * * * * $DIR/run.sh"; } | crontab - 2>/dev/null; then
  CRON="cron restarts it at boot and every 5 minutes"
else
  CRON="cron is not available to you here: after a reboot, run $DIR/run.sh again"
fi
"$DIR/run.sh"
sleep 3
if fetch "http://127.0.0.1:$PORT/metrics" >/dev/null 2>&1; then OK="running on 127.0.0.1:$PORT ($CRON)"; else OK="NOT answering yet; see $DIR/agent.log"; fi

if [ "$USERSPACE" = 1 ]; then TS="$DIR/bin/tailscale --socket=$DIR/ts.sock"
elif command -v tailscale >/dev/null; then TS="sudo tailscale"
else TS="sudo tailscale"; echo "Tailscale is not installed. With root: curl -fsSL https://tailscale.com/install.sh | sh ; without root: rerun this with --userspace-tailscale"; fi
cat <<EOF

Agent: $OK

Next, once on this server:
  $TS up --hostname=$NAME      # prints a login link: open it and add this machine to your tailnet
  $TS serve --bg $PORT         # publishes the agent over HTTPS, to your tailnet only
In the Tailscale admin console, turn off key expiry for this machine so it does not drop off after 180 days.
Then add it on the Resources page:   $NAME https://$NAME.<your-tailnet>.ts.net
EOF
