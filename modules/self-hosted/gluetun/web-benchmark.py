#!/usr/bin/env python3
import argparse
import json
import ssl
import sys
import time
import urllib.request


class BenchmarkError(RuntimeError):
    pass


def measure(args: argparse.Namespace) -> int:
    started = time.monotonic()
    deadline = started + args.time_limit
    transferred = 0
    attempts = 0
    completed = 0
    context = ssl.create_default_context()

    while time.monotonic() < deadline and transferred < args.bytes_target:
        attempts += 1
        timeout = max(1.0, min(args.timeout, deadline - time.monotonic()))
        request = urllib.request.Request(
            args.url,
            headers={
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'User-Agent': 'ghostship-gluetun-benchmark/1.0',
            },
        )
        request_completed = False
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                while time.monotonic() < deadline and transferred < args.bytes_target:
                    remaining = args.bytes_target - transferred
                    chunk = response.read(min(args.chunk_size, remaining))
                    if not chunk:
                        request_completed = True
                        break
                    transferred += len(chunk)
        except Exception as exc:
            if transferred == 0:
                raise BenchmarkError(f'Failed to download benchmark payload: {exc}') from exc
            break
        if request_completed:
            completed += 1

    elapsed = max(time.monotonic() - started, 0.001)
    if transferred == 0:
        raise BenchmarkError('Benchmark transferred no data')

    payload = {
        'measured_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'bytes_transferred': transferred,
        'elapsed_seconds': elapsed,
        'bytes_per_second': transferred / elapsed,
        'requests_attempted': attempts,
        'requests_completed': completed,
        'benchmark_url': args.url,
        'time_limit_seconds': args.time_limit,
        'bytes_target': args.bytes_target,
    }
    print(json.dumps(payload))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Bounded generic web download benchmark helper')
    parser.add_argument('--url', required=True)
    parser.add_argument('--timeout', type=float, default=15.0)
    parser.add_argument('--bytes-target', type=int, default=67108864)
    parser.add_argument('--time-limit', type=float, default=15.0)
    parser.add_argument('--chunk-size', type=int, default=262144)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return measure(args)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except BenchmarkError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
