#!/usr/bin/env python3
"""Read-only usage agent for the Resources page of PhD Plan.

Samples CPU, memory, disks, GPUs (through nvidia-smi) and who is using them, and serves the
numbers as JSON on 127.0.0.1 only. Publish it to your tailnet, and nowhere else, with
`tailscale serve --bg <port>`.

    python3 plan_monitor.py --port 9101 --origin https://h-tr.github.io
    python3 plan_monitor.py --once          # print one snapshot and exit

GET /metrics   the latest snapshot
GET /history   the last 30 minutes at 10 s steps: [t, cpu %, memory %, [GPU util %], [GPU memory %]]

Standard library only; runs as an ordinary user. It never executes anything a request asks for.
"""
import argparse
import json
import os
import pwd
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROC = os.environ.get('PLAN_MONITOR_PROC', '/proc')              # test hooks
NVSMI = os.environ.get('PLAN_MONITOR_NVIDIA_SMI', 'nvidia-smi')
TICK = os.sysconf('SC_CLK_TCK')
PAGE = os.sysconf('SC_PAGE_SIZE')
REAL_FS = {'ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'zfs', 'f2fs', 'nfs', 'nfs4', 'cifs', 'lustre', 'gpfs', 'fuseblk'}
GPU_Q = 'index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit'
APP_Q = 'gpu_uuid,pid,used_memory,process_name'
HIST_STEP = 10


def read(path):
    with open(path) as f:
        return f.read()


def num(s):
    try:
        return float(s)
    except ValueError:          # "[N/A]", "[Not Supported]"
        return None


_names = {}
def user_of(uid):
    if uid not in _names:
        try:
            _names[uid] = pwd.getpwuid(uid).pw_name
        except KeyError:
            _names[uid] = str(uid)
    return _names[uid]


def default_disks():
    """Real filesystems from /proc/mounts, one mount per device, the root first."""
    seen, out = set(), []
    try:
        lines = read(f'{PROC}/mounts').splitlines()
    except OSError:
        return ['/']
    for line in lines:
        dev, mnt, fs = line.split()[:3]
        mnt = mnt.replace('\\040', ' ')
        if fs not in REAL_FS or dev in seen or mnt.startswith(('/boot', '/snap', '/var/lib/docker', '/run')):
            continue
        seen.add(dev)
        out.append(mnt)
    out.sort(key=lambda m: (m != '/', m))
    return out[:6] or ['/']


class Sampler:
    def __init__(self, disks):
        self.disks = disks
        self.prev_cpu = None
        self.prev_proc = {}
        self.prev_t = None
        self.latest = None
        self.hist = deque(maxlen=30 * 60 // HIST_STEP)
        self.lock = threading.Lock()

    def cpu(self):
        f = [int(x) for x in read(f'{PROC}/stat').split('\n', 1)[0].split()[1:]]
        idle, total = f[3] + (f[4] if len(f) > 4 else 0), sum(f[:8])
        pct = None
        if self.prev_cpu and total > self.prev_cpu[0]:
            pct = round(min(100.0, max(0.0, 100 * (1 - (idle - self.prev_cpu[1]) / (total - self.prev_cpu[0])))), 1)
        self.prev_cpu = (total, idle)
        return pct

    def memory(self):
        m = {}
        for line in read(f'{PROC}/meminfo').splitlines():
            k, v = line.split(':', 1)
            m[k] = int(v.split()[0]) * 1024
        total = m.get('MemTotal', 0)
        avail = m.get('MemAvailable', m.get('MemFree', 0))
        return ({'total': total, 'used': total - avail},
                {'total': m.get('SwapTotal', 0), 'used': m.get('SwapTotal', 0) - m.get('SwapFree', 0)})

    def disk_usage(self):
        out = []
        for mnt in self.disks:
            try:
                s = os.statvfs(mnt)
            except OSError:
                continue
            total = s.f_blocks * s.f_frsize
            out.append({'mount': mnt, 'total': total, 'used': total - s.f_bfree * s.f_frsize, 'avail': s.f_bavail * s.f_frsize})
        return out

    def processes(self, now):
        """CPU (in cores) and resident memory per user, from /proc/<pid>/stat deltas."""
        cur, per_user = {}, {}
        for pid in os.listdir(PROC):
            if not pid.isdigit():
                continue
            try:
                stat = read(f'{PROC}/{pid}/stat')
                uid = os.stat(f'{PROC}/{pid}').st_uid
            except OSError:
                continue
            rest = stat[stat.rfind(')') + 2:].split()          # rest[0] is field 3 of proc(5)
            ticks, start, rss = int(rest[11]) + int(rest[12]), int(rest[19]), int(rest[21]) * PAGE
            cur[pid] = (ticks, start)
            u = per_user.setdefault(uid, [0.0, 0])
            u[1] += rss
            prev = self.prev_proc.get(pid)
            if prev and prev[1] == start and self.prev_t and now > self.prev_t:
                u[0] += (ticks - prev[0]) / TICK / (now - self.prev_t)
        self.prev_proc = cur
        users = [{'user': user_of(uid), 'cpu': round(c, 2), 'rss': r} for uid, (c, r) in per_user.items()
                 if c >= 0.05 or r >= 512 * 2 ** 20]
        users.sort(key=lambda x: (-x['cpu'], -x['rss']))
        return users[:10]

    def proc_info(self, pid, mem, name, uptime):
        info = {'pid': int(pid), 'mem': mem, 'name': os.path.basename(name), 'user': '?', 'cmd': '', 'elapsed': None}
        try:
            info['user'] = user_of(os.stat(f'{PROC}/{pid}').st_uid)
            info['cmd'] = read(f'{PROC}/{pid}/cmdline').replace('\0', ' ').strip()[:160]
            stat = read(f'{PROC}/{pid}/stat')
            info['elapsed'] = int(uptime - int(stat[stat.rfind(')') + 2:].split()[19]) / TICK)
        except (OSError, ValueError, IndexError):
            pass                  # another PID namespace, or /proc mounted with hidepid
        return info

    def gpus(self, uptime):
        try:
            g = subprocess.run([NVSMI, '--query-gpu=' + GPU_Q, '--format=csv,noheader,nounits'],
                               capture_output=True, text=True, timeout=8)
        except FileNotFoundError:
            return [], None       # no NVIDIA driver: a CPU-only machine
        except (OSError, subprocess.TimeoutExpired) as e:
            return [], f'nvidia-smi: {e}'
        if g.returncode:
            return [], (g.stderr or g.stdout).strip()[:200]
        gpus, by_uuid = [], {}
        for line in g.stdout.strip().splitlines():
            p = [x.strip() for x in line.split(',')]
            if len(p) < 9:
                continue
            d = {'i': int(p[0]), 'name': p[2], 'util': num(p[3]), 'mem_used': num(p[4]), 'mem_total': num(p[5]),
                 'temp': num(p[6]), 'power': num(p[7]), 'power_limit': num(p[8]), 'procs': []}
            gpus.append(d)
            by_uuid[p[1]] = d
        try:
            a = subprocess.run([NVSMI, '--query-compute-apps=' + APP_Q, '--format=csv,noheader,nounits'],
                               capture_output=True, text=True, timeout=8)
            for line in a.stdout.strip().splitlines():
                p = [x.strip() for x in line.split(',')]
                if len(p) >= 4 and p[0] in by_uuid:
                    by_uuid[p[0]]['procs'].append(self.proc_info(p[1], num(p[2]), p[3], uptime))
        except (OSError, subprocess.TimeoutExpired):
            pass
        return gpus, None

    def sample(self):
        now = time.time()
        errors = {}
        uptime = float(read(f'{PROC}/uptime').split()[0])
        cpu = self.cpu()
        mem, swap = self.memory()
        try:
            users = self.processes(now)
        except OSError as e:
            users, errors['users'] = [], str(e)
        self.prev_t = now
        gpus, gerr = self.gpus(uptime)
        if gerr:
            errors['gpu'] = gerr
        snap = {'v': 1, 'host': socket.gethostname(), 't': round(now, 1), 'uptime': int(uptime),
                'load': [float(x) for x in read(f'{PROC}/loadavg').split()[:3]], 'cores': os.cpu_count(),
                'cpu': cpu, 'mem': mem, 'swap': swap, 'disks': self.disk_usage(), 'gpus': gpus, 'users': users,
                'errors': errors}
        pct = lambda a, b: round(100 * a / b, 1) if a is not None and b else None
        with self.lock:
            self.latest = snap
            if cpu is not None and (not self.hist or now - self.hist[-1][0] >= HIST_STEP - 0.5):
                self.hist.append([snap['t'], cpu, pct(mem['used'], mem['total']), [g['util'] for g in gpus],
                                  [pct(g['mem_used'], g['mem_total']) for g in gpus]])
        return snap


def serve(sampler, bind, port, origins):
    class Handler(BaseHTTPRequestHandler):
        def cors(self):
            origin = self.headers.get('Origin')
            if origin and (origin in origins or '*' in origins):
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Vary', 'Origin')
            # Chrome's Private/Local Network Access: a public page asking for a tailnet (100.x) address
            self.send_header('Access-Control-Allow-Private-Network', 'true')

        def do_OPTIONS(self):
            self.send_response(204)
            self.cors()
            self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', '*')
            self.send_header('Access-Control-Max-Age', '600')
            self.end_headers()

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            with sampler.lock:
                if path in ('/', '/metrics'):
                    body = sampler.latest
                elif path == '/history':
                    body = {'v': 1, 'step': HIST_STEP, 'points': list(sampler.hist)}
                else:
                    body = None
            if body is None:
                self.send_error(404)
                return
            data = json.dumps(body, separators=(',', ':')).encode()
            self.send_response(200)
            self.cors()
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):    # quiet: no per-request log lines
            pass

    ThreadingHTTPServer((bind, port), Handler).serve_forever()


def main():
    ap = argparse.ArgumentParser(description='Read-only usage agent for the Resources page of PhD Plan.')
    ap.add_argument('--port', type=int, default=9101)
    ap.add_argument('--bind', default='127.0.0.1', help='keep 127.0.0.1; tailscale serve does the publishing')
    ap.add_argument('--origin', action='append', default=None,
                    help='page origin allowed to read the numbers (repeatable); default https://h-tr.github.io')
    ap.add_argument('--interval', type=float, default=2.0, help='seconds between samples')
    ap.add_argument('--disk', action='append', help='mount point to report (repeatable); default: every real filesystem')
    ap.add_argument('--once', action='store_true', help='print one snapshot and exit')
    a = ap.parse_args()
    sampler = Sampler(a.disk or default_disks())
    sampler.sample()
    time.sleep(0.5)
    if a.once:
        json.dump(sampler.sample(), sys.stdout, indent=1)
        print()
        return

    def loop():
        while True:
            time.sleep(a.interval)
            try:
                sampler.sample()
            except Exception as e:          # keep serving the last good snapshot
                print(time.strftime('%F %T'), 'sample failed:', repr(e), file=sys.stderr, flush=True)

    threading.Thread(target=loop, daemon=True).start()
    serve(sampler, a.bind, a.port, set(a.origin or ['https://h-tr.github.io']))


if __name__ == '__main__':
    main()
