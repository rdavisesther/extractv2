import os
import csv
import json
import io
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, Response
import imap_extractor

BASE_DIR = Path(__file__).resolve().parent

FRONTEND_DIR = None
for candidate in ['public', 'frontend', '.']:
    p = (BASE_DIR.parent / candidate).resolve()
    if p.is_dir() and (p / 'index.html').exists():
        FRONTEND_DIR = p
        break
if FRONTEND_DIR is None:
    FRONTEND_DIR = (BASE_DIR.parent / 'public').resolve()

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024


def get_creds():
    body = request.get_json(silent=True) or {}
    return {
        'email': (body.get('email') or '').strip(),
        'password': body.get('password') or '',
        'host': (body.get('host') or '').strip() or None,
        'port': body.get('port') or None,
    }


@app.get('/api/health')
def health():
    return jsonify({'status': 'ok'}), 200


@app.post('/api/test-connection')
def test_connection():
    return jsonify(imap_extractor.test_connection(get_creds())), 200


@app.post('/api/providers')
def providers():
    return jsonify({'providers': imap_extractor.PROVIDERS}), 200


@app.post('/api/folders')
def folders():
    try:
        return jsonify({'folders': imap_extractor.list_folders(get_creds())}), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': imap_extractor.error_message(e)}), 400


@app.post('/api/extract')
def extract():
    body = request.get_json(silent=True) or {}
    creds = get_creds()
    folders = body.get('folders') or []
    if isinstance(folders, str):
        folders = [folders]
    start_from = body.get('startFrom') or 1
    count = body.get('count') or 100
    fields = body.get('fields') or ['fromEmail', 'subject', 'fromName', 'date']
    if not creds['email'] or not creds['password']:
        return jsonify({'error': 'Email and password are required.'}), 400
    if not folders:
        return jsonify({'error': 'Select at least one folder to extract from.'}), 400
    try:
        result = imap_extractor.extract_emails(creds, folders, start_from, count, fields)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': imap_extractor.error_message(e)}), 400


@app.post('/api/export')
def export():
    body = request.get_json(silent=True) or {}
    data = body.get('data') or []
    if not isinstance(data, list):
        data = []
    fmt = (body.get('format') or 'csv').lower()
    keys = list(dict.fromkeys(k for row in data for k in row.keys()))
    if fmt == 'json':
        return Response(
            json.dumps(data, ensure_ascii=False, indent=2),
            mimetype='application/json',
            headers={'Content-Disposition': 'attachment; filename=extraction.json'},
        )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=keys, extrasaction='ignore')
    writer.writeheader()
    for row in data:
        cleaned = {k: ('' if isinstance(v, list) else v) for k, v in row.items()}
        writer.writerow(cleaned)
    return Response(
        '\ufeff' + buf.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=extraction.csv'},
    )


@app.get('/')
def index():
    return send_from_directory(FRONTEND_DIR, 'index.html')


@app.get('/<path:filename>')
def static_files(filename):
    target = (FRONTEND_DIR / filename).resolve()
    if FRONTEND_DIR in target.parents or target == FRONTEND_DIR:
        if target.is_file():
            return send_from_directory(FRONTEND_DIR, filename)
    return send_from_directory(FRONTEND_DIR, 'index.html')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '5000'))
    app.run(host='0.0.0.0', port=port, debug=True)
