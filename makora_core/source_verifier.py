"""Bounded public-source verification; citations are data, never instructions."""
import hashlib
import http.client
import ipaddress
import socket
import ssl
import time
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def fetch_public_text(url):
    for _ in range(4):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Ожидается публичный HTTP(S) источник')
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if port not in (80, 443):
            raise ValueError('Нестандартный порт источника запрещён')
        lookup = queue.Queue(maxsize=1)
        def resolve():
            try: lookup.put(socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM))
            except Exception as exc: lookup.put(exc)
        threading.Thread(target=resolve, daemon=True).start()
        addresses = lookup.get(timeout=3)
        if isinstance(addresses, Exception):
            raise addresses
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError('Локальный или непубличный адрес источника запрещён')
        # Pin the vetted address: the HTTP client must not resolve the hostname again.
        connection = http.client.HTTPConnection(parsed.hostname, port, timeout=8)
        connection.sock = socket.create_connection(addresses[0][4][:2], timeout=8)
        try:
            if parsed.scheme == 'https':
                connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=parsed.hostname)
            connection.request('GET', (parsed.path or '/') + ('?' + parsed.query if parsed.query else ''),
                               headers={'Host': parsed.netloc, 'User-Agent': 'MakoraSourceCheck/1.0'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = urljoin(url, response.getheader('Location', ''))
                continue
            if response.status != 200:
                raise ValueError(f'HTTP {response.status}')
            data = bytearray()
            deadline = time.monotonic() + 12
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Истёк лимит чтения источника')
                if connection.sock:
                    connection.sock.settimeout(min(remaining, 8))
                block = response.read1(8192)
                if not block:
                    break
                data.extend(block)
                if len(data) > 256 * 1024:
                    raise ValueError('Источник превышает лимит проверки 256 КБ')
            parser = Text()
            parser.feed(data.decode('utf-8', errors='replace'))
            return ' '.join(' '.join(parser.parts).split()), hashlib.sha256(data).hexdigest()
        finally:
            connection.close()
    raise ValueError('Слишком много перенаправлений')


def verify_sources(research):
    sources = {}
    for competitor in research.get('competitors', []):
        if competitor.get('status') == 'verified':
            for source in competitor.get('sources', []):
                sources[(source['url'], source.get('quote', ''))] = source
    if len(sources) > 12:
        return [{'url': url, 'status': 'not_checked', 'detail': 'Не более 12 источников за проверку'} for url, quote in sources]

    def check(source):
        result = {'url': source['url'], 'quote':source.get('quote',''), 'checkedAt': datetime.now(timezone.utc).isoformat()}
        try:
            quote = source.get('quote', '').strip()
            if len(quote) < 15:
                raise ValueError('Нужна точная цитата источника длиной от 15 символов')
            text, digest = fetch_public_text(source['url'])
            matched = ' '.join(quote.split()).casefold() in text.casefold()
            result.update(status='passed' if matched else 'failed', sha256=digest, quoteMatched=matched,
                          detail='Цитата найдена' if matched else 'Цитата не найдена в доступном содержимом')
        except Exception as exc:
            result.update(status='not_checked', detail=str(exc)[:300])
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(check, sources.values()))
