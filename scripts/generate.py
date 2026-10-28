#!/usr/bin/env python3
"""Build a Base64 Xray/V2Ray subscription from Sing-box VLESS feeds."""
from __future__ import annotations

import base64
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCES_FILE = ROOT / "sources.json"
OUTPUT_FILE = ROOT / "fast" / "sub" / "normal"
USER_AGENT = "zoomjomedia-subscription-generator/1.0"
TIMEOUT_SECONDS = 25


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def parse_json_feed(text: str) -> dict[str, Any] | None:
    """Support both a bare JSON document and Sing-box feeds with comment headers."""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def add_param(params: list[tuple[str, str]], key: str, value: Any) -> None:
    if value is not None and str(value) != "":
        params.append((key, str(value)))


def vless_outbound_to_uri(outbound: dict[str, Any], name: str) -> str | None:
    server = outbound.get("server")
    port = outbound.get("server_port")
    uuid = outbound.get("uuid")
    if not server or not port or not uuid:
        return None

    transport = outbound.get("transport")
    transport = transport if isinstance(transport, dict) else {}
    network = str(transport.get("type") or "tcp")
    params: list[tuple[str, str]] = [("encryption", "none"), ("type", network)]
    add_param(params, "flow", outbound.get("flow"))

    tls = outbound.get("tls")
    tls = tls if isinstance(tls, dict) else {}
    if tls.get("enabled"):
        reality = tls.get("reality")
        reality = reality if isinstance(reality, dict) and reality.get("enabled") else None
        params.append(("security", "reality" if reality else "tls"))
        add_param(params, "sni", tls.get("server_name"))

        utls = tls.get("utls")
        if isinstance(utls, dict) and utls.get("enabled"):
            add_param(params, "fp", utls.get("fingerprint"))

        alpn = tls.get("alpn")
        if isinstance(alpn, list) and alpn:
            add_param(params, "alpn", ",".join(map(str, alpn)))

        if reality:
            add_param(params, "pbk", reality.get("public_key"))
            # An empty short ID is meaningful for Reality, so preserve it.
            if "short_id" in reality and reality["short_id"] is not None:
                params.append(("sid", str(reality["short_id"])))
        if tls.get("insecure") is True:
            params.append(("allowInsecure", "1"))
    else:
        params.append(("security", "none"))

    headers = transport.get("headers")
    headers = headers if isinstance(headers, dict) else {}
    host = headers.get("Host") or headers.get("host") or transport.get("host")
    if network in {"ws", "http", "httpupgrade", "xhttp", "splithttp"}:
        add_param(params, "host", host)
    add_param(params, "path", transport.get("path"))
    add_param(params, "serviceName", transport.get("service_name"))
    if network == "grpc":
        add_param(params, "mode", transport.get("mode"))
    if "max_early_data" in transport:
        params.append(("ed", str(transport["max_early_data"])))
    add_param(params, "eh", transport.get("early_data_header_name"))
    add_param(params, "packetEncoding", outbound.get("packet_encoding"))

    query = urllib.parse.urlencode(params, doseq=True)
    fragment = urllib.parse.quote(name, safe="")
    # VLESS servers from public feeds are normally hostnames or IPv4 addresses.
    # Bracket IPv6 literals so the URI's host/port separator is unambiguous.
    host_value = str(server)
    if ":" in host_value and not (host_value.startswith("[") and host_value.endswith("]")):
        host_value = f"[{host_value}]"
    return f"vless://{uuid}@{host_value}:{int(port)}?{query}#{fragment}"


def rename_existing_vless_uri(line: str, name: str) -> str | None:
    """Keep URI server parameters intact; only replace its displayed label."""
    line = line.strip()
    if not line.lower().startswith("vless://"):
        return None
    try:
        parts = urllib.parse.urlsplit(line)
        if not parts.netloc or "@" not in parts.netloc:
            return None
        return urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, parts.query, urllib.parse.quote(name, safe=""))
        )
    except ValueError:
        return None


def process_source(text: str, start_number: int, prefix: str) -> list[str]:
    config = parse_json_feed(text)
    output: list[str] = []
    if config is not None:
        outbounds = config.get("outbounds", [])
        if not isinstance(outbounds, list):
            raise ValueError("JSON feed field 'outbounds' is not a list")
        for outbound in outbounds:
            if not isinstance(outbound, dict) or outbound.get("type") != "vless":
                continue
            name = f"{prefix} {start_number + len(output)}"
            uri = vless_outbound_to_uri(outbound, name)
            if uri:
                output.append(uri)
        return output

    # A future source may already be a plain-text VLESS URI subscription.
    # Keep connection parameters unchanged and only replace the fragment name.
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "://" not in stripped:
            continue
        name = f"{prefix} {start_number + len(output)}"
        uri = rename_existing_vless_uri(stripped, name)
        if uri:
            output.append(uri)
    return output


def main() -> int:
    settings = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    prefix = str(settings.get("name_prefix") or "zoomjomedia").strip() or "zoomjomedia"
    sources = settings.get("sources")
    if not isinstance(sources, list):
        raise ValueError("sources.json must include a 'sources' array")

    all_uris: list[str] = []
    successful_sources = 0
    errors: list[str] = []
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict) or source.get("enabled", True) is False:
            continue
        url = str(source.get("url") or "").strip()
        if not url.startswith(("https://", "http://")):
            errors.append(f"source #{index}: missing or invalid URL")
            continue
        try:
            content = fetch_text(url)
            converted = process_source(content, len(all_uris) + 1, prefix)
            if not converted:
                errors.append(f"source #{index}: no VLESS nodes found ({url})")
                continue
            all_uris.extend(converted)
            successful_sources += 1
            print(f"source #{index}: converted {len(converted)} VLESS node(s)")
        except Exception as exc:  # Keep previous output if every source is unavailable.
            errors.append(f"source #{index}: {url}: {type(exc).__name__}: {exc}")

    for error in errors:
        print(f"warning: {error}", file=sys.stderr)

    if successful_sources == 0 or not all_uris:
        print("error: no source produced VLESS nodes; previous output was not changed", file=sys.stderr)
        return 1

    # Raw subscription URLs are commonly expected to contain Base64 of URI lines.
    body = ("\n".join(all_uris) + "\n").encode("utf-8")
    encoded = base64.b64encode(body).decode("ascii") + "\n"
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = OUTPUT_FILE.with_suffix(".tmp")
    temp_file.write_text(encoded, encoding="ascii")
    temp_file.replace(OUTPUT_FILE)
    print(f"wrote {len(all_uris)} node(s) to {OUTPUT_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
