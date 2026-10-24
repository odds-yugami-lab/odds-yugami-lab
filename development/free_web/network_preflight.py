"""Public network connectivity preflight; diagnostic only, never verifies live odds."""
import argparse
import datetime as dt
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

SOURCES = {
    "jra": "https://www.jra.go.jp/",
    "yahoo_keiba": "https://sports.yahoo.co.jp/keiba/",
    "netkeiba": "https://race.netkeiba.com/",
}

def probe(name, url, timeout=8):
    host = urllib.parse.urlsplit(url).hostname
    result = {"source": name, "host": host, "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    try:
        socket.getaddrinfo(host, 443)
        result["dns"] = "ok"
    except OSError as exc:
        result.update(dns="failed", status="dns_error", error_type=type(exc).__name__)
        return result
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result.update(status="ok", http_status=response.status)
    except urllib.error.HTTPError as exc:
        result.update(status="http_error", http_status=exc.code)
    except Exception as exc:
        result.update(status="transport_error", error_type=type(exc).__name__)
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--race", help="16 digit JRA race code; probe exact live odds URLs")
    args = parser.parse_args()
    targets = dict(SOURCES)
    if args.race:
        import re
        if not re.fullmatch(r"\d{16}", args.race):
            parser.error("--race must be a 16-digit JRA race code")
        web_id = args.race[2:4] + args.race[8:]
        targets.update({
            "free_entries": f"https://sports.yahoo.co.jp/keiba/race/denma/{web_id}",
            "win_odds": f"https://sports.yahoo.co.jp/keiba/race/odds/tfw/{web_id}?ninki=0",
            "umaren_odds": f"https://sports.yahoo.co.jp/keiba/race/odds/ur/{web_id}?ninki=0",
            "sanrenpuku_odds": f"https://sports.yahoo.co.jp/keiba/race/odds/sf/{web_id}?ninki=0",
        })
    outcome = {"kind": "diagnostic_only", "verified_live": False,
               "checks": [probe(name, url) for name, url in targets.items()]}
    report = json.dumps(outcome, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(report)
    print(report)

if __name__ == "__main__":
    main()
