#!/usr/bin/env python3
"""Calendar sync for the Control Panel, run every 15 minutes by .github/workflows/calendar.yml.

Reads the calendars listed in the CALENDAR_SOURCES secret, expands the events from two weeks ago to ten weeks
ahead (recurring meetings included), and writes them encrypted for the planner: a fresh AES-256-GCM key per run,
wrapped with the planner's RSA-OAEP public key. Only the planner, which holds the private key inside its own
encrypted data, can read the result. Nothing about the calendars is printed beyond counts and error types.

    python3 sync.py <out.json> <public-key.json>

CALENDAR_SOURCES, one calendar per line:
    Google | https://calendar.google.com/calendar/ical/.../basic.ics
    NUS    | https://outlook.office365.com/owa/calendar/.../calendar.ics
    Feishu | caldav | https://caldav.example.com/ | username | password
"""
import base64
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.request
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PAST_DAYS, FUTURE_DAYS = 14, 70
LOCAL_TZ = ZoneInfo(os.environ.get('CALENDAR_TZ', 'Asia/Singapore'))    # for "floating" times without a zone
MEETING = re.compile(r'https://(?:[\w-]+\.)*(?:zoom\.us/(?:j|my|w)/|teams\.microsoft\.com/(?:l/meetup-join|meet)/|teams\.live\.com/meet/|meet\.google\.com/'
                     r'|vc\.feishu\.cn/j/|meetings\.feishu\.cn/|vc\.larksuite\.com/j/|meeting\.tencent\.com/|voovmeeting\.com/|webex\.com/)[^\s<>"\'\\)\]]+')


def b64url(s):
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def public_key(path):
    j = json.load(open(path))
    return rsa.RSAPublicNumbers(int.from_bytes(b64url(j['e']), 'big'), int.from_bytes(b64url(j['n']), 'big')).public_key()


def seal(obj, pub):
    key, iv = AESGCM.generate_key(bit_length=256), os.urandom(12)
    ct = AESGCM(key).encrypt(iv, json.dumps(obj, separators=(',', ':'), ensure_ascii=False).encode(), None)
    wk = pub.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    b64 = lambda x: base64.b64encode(x).decode()
    return {'v': 1, 'alg': 'RSA-OAEP-256+A256GCM', 'wk': b64(wk), 'iv': b64(iv), 'ct': b64(ct)}


def parse_sources(text):
    out = []
    for line in text.splitlines():
        p = [x.strip() for x in line.strip().split('|')]
        if not p[0] or p[0].startswith('#') or len(p) < 2:
            continue
        if p[1].lower() == 'caldav' and len(p) >= 5:
            out.append({'name': p[0], 'kind': 'caldav', 'url': p[2], 'user': p[3], 'password': '|'.join(p[4:])})
        else:
            out.append({'name': p[0], 'kind': 'ics', 'url': re.sub(r'^webcals?://', 'https://', p[1])})
    return out


def fetch_ics(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'phd-plan-calendar-sync/1'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return [icalendar.Calendar.from_ical(r.read())]


def fetch_caldav(src, start, end):
    import caldav
    with caldav.DAVClient(url=src['url'], username=src['user'], password=src['password']) as client:
        cals = []
        for cal in client.principal().calendars():
            for res in cal.search(start=start, end=end, event=True, expand=False):
                cals.append(icalendar.Calendar.from_ical(res.data))
        return cals


def stamp(x):
    if not isinstance(x, dt.datetime):
        return x.isoformat()                         # an all-day date
    if x.tzinfo is None:
        x = x.replace(tzinfo=LOCAL_TZ)
    return x.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def events_of(cal, si, start, end):
    """Returns (events, how many malformed ones were skipped): one bad event must not cost the whole calendar."""
    out, bad = [], 0
    for ev in recurring_ical_events.of(cal, skip_bad_series=True).between(start, end):
        try:
            item = one_event(ev, si)
        except Exception:
            bad += 1
            continue
        if item:
            out.append(item)
    return out, bad


def one_event(ev, si):
    if str(ev.get('STATUS', '')).upper() == 'CANCELLED':
        return None
    s = ev.get('DTSTART').dt
    all_day = not isinstance(s, dt.datetime)
    if ev.get('DTEND') is not None:
        e = ev.get('DTEND').dt
    elif ev.get('DURATION') is not None:
        e = s + ev.get('DURATION').dt
    else:
        e = s + (dt.timedelta(days=1) if all_day else dt.timedelta(hours=1))
    text = ' '.join(str(ev.get(k, '')) for k in ('LOCATION', 'URL', 'DESCRIPTION', 'X-GOOGLE-CONFERENCE',
                                                'X-MICROSOFT-SKYPETEAMSMEETINGURL', 'X-MICROSOFT-ONLINEMEETINGCONFLINK'))
    link = MEETING.search(text)
    uid = f"{si}:{ev.get('UID', '')}:{stamp(s)}"
    return {'id': hashlib.sha1(uid.encode()).hexdigest()[:12], 'src': si, 't': str(ev.get('SUMMARY', '') or 'Busy')[:200],
            's': stamp(s), 'e': stamp(e), 'all': all_day, 'loc': str(ev.get('LOCATION', '') or '')[:160],
            'url': link.group(0) if link else ''}


def main():
    out_path, key_path = sys.argv[1], sys.argv[2]
    sources = parse_sources(os.environ.get('CALENDAR_SOURCES', ''))
    if not sources:
        print('CALENDAR_SOURCES is not set: nothing to sync')
        return
    if not os.path.exists(key_path):
        print('No public key yet: turn calendar sync on in the planner settings first')
        return
    now = dt.datetime.now(dt.timezone.utc)
    start, end = now - dt.timedelta(days=PAST_DAYS), now + dt.timedelta(days=FUTURE_DAYS)
    events, status, seen = [], [], set()
    for si, src in enumerate(sources):
        try:
            cals = fetch_ics(src['url']) if src['kind'] == 'ics' else fetch_caldav(src, start, end)
            evs, bad = [], 0
            for c in cals:
                got, b = events_of(c, si, start, end)
                evs += got
                bad += b
            fresh = []
            for e in evs:                               # the same meeting in two calendars shows once
                key = (e['t'].strip().lower(), e['s'], e['e'])
                if key not in seen:
                    seen.add(key)
                    fresh.append(e)
            events += fresh
            status.append({'name': src['name'], 'ok': True, 'n': len(fresh), 'skipped': bad})
            print(f"{src['name']}: {len(fresh)} events" + (f', {bad} malformed skipped' if bad else ''))
        except Exception as exc:                        # report the kind of failure, never the address
            code = getattr(exc, 'code', None)
            err = type(exc).__name__ + (f' {code}' if code is not None else '')
            status.append({'name': src['name'], 'ok': False, 'n': 0, 'err': err})
            print(f"{src['name']}: failed ({err})")
    events.sort(key=lambda e: (e['s'], e['t']))
    payload = {'v': 1, 'at': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'tz': str(LOCAL_TZ), 'sources': status, 'events': events}
    with open(out_path, 'w') as f:
        json.dump(seal(payload, public_key(key_path)), f)
    print(f'{len(events)} events written')


if __name__ == '__main__':
    main()
