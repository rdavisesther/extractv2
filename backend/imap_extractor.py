import imaplib
import ssl
import email
import re
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr

PROVIDERS = {
    'gmail.com': ('imap.gmail.com', 993, 'Gmail'),
    'googlemail.com': ('imap.gmail.com', 993, 'Gmail'),
    'outlook.com': ('outlook.office365.com', 993, 'Outlook'),
    'hotmail.com': ('outlook.office365.com', 993, 'Outlook'),
    'live.com': ('outlook.office365.com', 993, 'Outlook'),
    'live.fr': ('outlook.office365.com', 993, 'Outlook'),
    'yahoo.com': ('imap.mail.yahoo.com', 993, 'Yahoo'),
    'yahoo.fr': ('imap.mail.yahoo.com', 993, 'Yahoo'),
    'aol.com': ('imap.aol.com', 993, 'AOL'),
    'icloud.com': ('imap.mail.me.com', 993, 'iCloud'),
    'me.com': ('imap.mail.me.com', 993, 'iCloud'),
}


def detect_provider(email_addr):
    domain = (email_addr or '').split('@')[-1].lower()
    info = PROVIDERS.get(domain)
    if info:
        return {'host': info[0], 'port': info[1], 'name': info[2]}
    return None


def build_client_config(creds):
    if creds.get('host'):
        return {'host': creds['host'], 'port': int(creds.get('port') or 993)}
    provider = detect_provider(creds.get('email'))
    if provider:
        return {'host': provider['host'], 'port': provider['port']}
    return {'host': '', 'port': 993}


def error_message(e):
    msg = str(e).lower()
    if 'not enough values to unpack' in msg or 'too many values to unpack' in msg:
        return 'Server returned unexpected data. Try again or use fewer folders.'
    if any(k in msg for k in ('invalid credentials', 'authentication failed', 'login failed')):
        return 'Authentication failed. Check your email and app password.'
    if any(k in msg for k in ('timeout', 'timed out')):
        return 'Connection timed out. Server did not respond.'
    if any(k in msg for k in ('connection refused', 'ec onnrefused')):
        return 'Cannot connect. Check host and port.'
    if any(k in msg for k in ('name or service not known', 'getaddrinfo')):
        return 'Cannot resolve hostname. Check your email or host.'
    if any(k in msg for k in ('ssl', 'tls', 'certificate')):
        return 'SSL/TLS error. Certificate issue.'
    if 'memory' in msg or 'memoryview' in msg:
        return 'Server returned corrupted data. Try again.'
    if 'option' in msg and 'not' in msg:
        return 'IMAP command not supported by this server.'
    return 'Connection failed. Check email, password, and server settings.'


def _connect(creds):
    cfg = build_client_config(creds)
    host = cfg['host']
    if not host:
        raise ValueError('Could not detect IMAP server. Provide host and port manually.')
    ctx = ssl.create_default_context()
    client = imaplib.IMAP4_SSL(host, cfg['port'], ssl_context=ctx, timeout=20)
    try:
        client.login(creds['email'], creds['password'])
    except Exception as e:
        try:
            client.logout()
        except Exception:
            pass
        raise ValueError(error_message(e)) from e
    return client


def _safe_tuple(val, expected=2):
    if isinstance(val, tuple) and len(val) >= expected:
        return val
    return None


def test_connection(creds):
    try:
        client = _connect(creds)
        try:
            client.logout()
        except Exception:
            pass
        provider = detect_provider(creds.get('email'))
        return {'success': True, 'provider': provider['name'] if provider else 'Custom IMAP', 'error': None}
    except Exception as e:
        provider = detect_provider(creds.get('email'))
        return {'success': False, 'provider': provider['name'] if provider else 'Custom IMAP', 'error': str(e)}


def list_folders(creds):
    client = _connect(creds)
    try:
        result = client.list()
        pair = _safe_tuple(result, 2)
        if not pair:
            return []
        typ, data = pair
        if typ != 'OK' or not data:
            return []
        folders = []
        for raw in data:
            try:
                if not raw:
                    continue
                line = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else str(raw)
                line = line.strip()
                if not line:
                    continue
                m = re.fullmatch(r'\((?P<flags>.*?)\)\s+"?(?P<delim>[^"]*)"?\s+(?P<name>.+)', line)
                if m:
                    name = m.group('name').strip().strip('"')
                    folders.append({
                        'name': name,
                        'path': name,
                        'delimiter': m.group('delim').strip() if m.group('delim') else '/',
                        'flags': m.group('flags').split() if m.group('flags').strip() else [],
                    })
                else:
                    folders.append({'name': line, 'path': line, 'delimiter': '/', 'flags': []})
            except Exception:
                continue
        return folders
    finally:
        try:
            client.logout()
        except Exception:
            pass


def _decode(value):
    if not value:
        return ''
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        try:
            return str(value)
        except Exception:
            return ''


def _address_list(value):
    if not value:
        return ''
    try:
        out = []
        for name, addr in getaddresses([str(value)]):
            if name and addr:
                out.append(f'{name} <{addr}>')
            elif addr:
                out.append(addr)
            elif name:
                out.append(name)
        return ', '.join(out)
    except Exception:
        return str(value)


def _extract_body(msg):
    text = None
    html = None
    try:
        if msg.is_multipart():
            for part in msg.walk():
                try:
                    ctype = part.get_content_type()
                    if ctype == 'text/plain' and text is None:
                        raw = part.get_payload(decode=True)
                        if raw is not None:
                            charset = part.get_content_charset() or 'utf-8'
                            text = raw.decode(charset, 'replace')
                    elif ctype == 'text/html' and html is None:
                        raw = part.get_payload(decode=True)
                        if raw is not None:
                            charset = part.get_content_charset() or 'utf-8'
                            html = raw.decode(charset, 'replace')
                except Exception:
                    continue
        else:
            raw = msg.get_payload(decode=True)
            if raw is not None:
                charset = msg.get_content_charset() or 'utf-8'
                text = raw.decode(charset, 'replace')
    except Exception:
        pass
    return (text or '').strip() or None, (html or '') or None


def _attachments(msg):
    out = []
    try:
        if msg.is_multipart():
            for part in msg.walk():
                fn = part.get_filename()
                if fn:
                    out.append(_decode(fn) or 'unnamed')
    except Exception:
        pass
    return out


def _extract_spf_domain(msg):
    try:
        auth = _decode(msg.get('Authentication-Results', ''))
        if not auth:
            auth = _decode(msg.get('Received-SPF', ''))
        m = re.search(r'spf\s*=\s*\w+\s*\(?domain\s+of\s+[\w@.-]+\s+designates\s+([\d.]+)\s+as\s+permitted\s+sender', auth, re.I)
        if m:
            return m.group(1)
        m = re.search(r'spf[=:]\s*\w+\s+.*?domain=([\w@.-]+)', auth, re.I)
        if m:
            return m.group(1)
        received = _decode(msg.get('Received', ''))
        m = re.search(r'from\s+([\w.-]+)\s+\(', received)
        if m:
            return m.group(1)
        m = re.search(r'by\s+([\w.-]+)\s', received)
        if m:
            return m.group(1)
        from_header = _decode(msg.get('From', ''))
        m = re.search(r'@([\w.-]+)', from_header)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _extract_spf_status(msg):
    try:
        auth = _decode(msg.get('Authentication-Results', ''))
        m = re.search(r'spf[=:]\s*(\w+)', auth, re.I)
        if m:
            return m.group(1).lower()
        received_spf = _decode(msg.get('Received-SPF', ''))
        if received_spf:
            m = re.match(r'(\w+)', received_spf)
            if m:
                return m.group(1).lower()
    except Exception:
        pass
    return None


def _extract_dkim_status(msg):
    try:
        auth = _decode(msg.get('Authentication-Results', ''))
        m = re.search(r'dkim[=:]\s*(\w+)', auth, re.I)
        if m:
            return m.group(1).lower()
    except Exception:
        pass
    return None


def _extract_sender_ip(msg):
    try:
        auth = _decode(msg.get('Authentication-Results', ''))
        m = re.search(r'bringing\s+ IPAddress=(\d+\.\d+\.\d+\.\d+)', auth, re.I)
        if m:
            return m.group(1)
        received_spf = _decode(msg.get('Received-SPF', ''))
        m = re.search(r'designates\s+(\d+\.\d+\.\d+\.\d+)\s+as\s+permitted', received_spf, re.I)
        if m:
            return m.group(1)
        received = _decode(msg.get('Received', ''))
        m = re.search(r'\[(\d+\.\d+\.\d+\.\d+)\]', received)
        if m:
            return m.group(1)
        m = re.search(r'from\s+\S+\s+\((?:helo|HELO|EHLO)?\s*=\s*[\w.-]*\s*\[(\d+\.\d+\.\d+\.\d+)\]', received, re.I)
        if m:
            return m.group(1)
        auth = _decode(msg.get('Authentication-Results', ''))
        m = re.search(r'ip=(\d+\.\d+\.\d+\.\d+)', auth, re.I)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def extract_emails(creds, folders, start_from, count, fields):
    client = _connect(creds)
    rows = []
    processed = 0
    found = 0
    skipped = 0
    errors = 0
    try:
        for folder in folders:
            if found >= count:
                break

            pair = None
            try:
                pair = client.select(folder, readonly=True)
            except Exception:
                errors += 1
                continue

            pair = _safe_tuple(pair, 2)
            if not pair:
                errors += 1
                continue

            typ, data = pair
            if typ != 'OK':
                errors += 1
                continue

            total_msgs = 0
            try:
                if data and data[0]:
                    total_msgs = int(data[0])
            except Exception:
                total_msgs = 0

            if total_msgs == 0:
                continue

            start = max(1, int(start_from or 1))
            end = min(start + int(count or 100) - 1, total_msgs)
            if start > total_msgs:
                skipped += total_msgs
                continue
            if end < start:
                continue

            seq = f'{start}:{end}'
            fetch_pair = None
            try:
                fetch_pair = client.fetch(seq, '(BODY.PEEK[])')
            except Exception:
                errors += 1
                continue

            fetch_pair = _safe_tuple(fetch_pair, 2)
            if not fetch_pair:
                errors += 1
                continue

            ftyp, msgs = fetch_pair
            if ftyp != 'OK' or not msgs:
                errors += 1
                continue

            for item in msgs:
                if found >= count:
                    break
                processed += 1
                try:
                    pair = _safe_tuple(item, 2)
                    if not pair:
                        skipped += 1
                        continue

                    meta_part, body_part = pair

                    uid = None
                    if isinstance(meta_part, bytes):
                        meta_str = meta_part.decode('utf-8', 'replace')
                        m_uid = re.search(r'UID\s+(\d+)', meta_str)
                        if m_uid:
                            uid = m_uid.group(1)
                    elif isinstance(meta_part, str):
                        m_uid = re.search(r'UID\s+(\d+)', meta_part)
                        if m_uid:
                            uid = m_uid.group(1)

                    if body_part is None:
                        skipped += 1
                        continue

                    if not isinstance(body_part, bytes):
                        skipped += 1
                        continue

                    msg = email.message_from_bytes(body_part)

                    row = {'uid': uid, 'folder': folder}
                    text_body, html_body = _extract_body(msg)

                    for f in fields:
                        try:
                            if f == 'fromName':
                                row['fromName'] = parseaddr(_decode(msg.get('From', '')))[0] or None
                            elif f == 'fromEmail':
                                row['fromEmail'] = parseaddr(_decode(msg.get('From', '')))[1] or None
                            elif f == 'to':
                                row['to'] = _address_list(msg.get('To')) or None
                            elif f == 'cc':
                                row['cc'] = _address_list(msg.get('Cc')) or None
                            elif f == 'bcc':
                                row['bcc'] = _address_list(msg.get('Bcc')) or None
                            elif f == 'subject':
                                row['subject'] = _decode(msg.get('Subject')) or None
                            elif f == 'date':
                                row['date'] = _decode(msg.get('Date')) or None
                            elif f == 'messageId':
                                row['messageId'] = _decode(msg.get('Message-ID')) or None
                            elif f == 'replyTo':
                                row['replyTo'] = _address_list(msg.get('Reply-To')) or None
                            elif f == 'body':
                                row['body'] = text_body
                            elif f == 'textBody':
                                row['textBody'] = text_body
                            elif f == 'htmlBody':
                                row['htmlBody'] = html_body
                            elif f == 'attachments':
                                row['attachments'] = _attachments(msg)
                            elif f == 'spfDomain':
                                row['spfDomain'] = _extract_spf_domain(msg)
                            elif f == 'spfStatus':
                                row['spfStatus'] = _extract_spf_status(msg)
                            elif f == 'dkimStatus':
                                row['dkimStatus'] = _extract_dkim_status(msg)
                            elif f == 'senderIP':
                                row['senderIP'] = _extract_sender_ip(msg)
                        except Exception:
                            pass
                    found += 1
                    rows.append(row)
                except Exception:
                    errors += 1

        return {'results': rows, 'stats': {
            'processed': processed, 'found': found, 'skipped': skipped, 'errors': errors,
        }}
    finally:
        try:
            client.logout()
        except Exception:
            pass
