import os
import csv
import json
import io
import traceback
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


@app.errorhandler(Exception)
def handle_all_errors(e):
    tb = traceback.format_exc()
    return jsonify({
        'error': imap_extractor.error_message(e),
        'detail': str(e),
    }), 500


def get_creds():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    return {
        'email': str(body.get('email') or '').strip(),
        'password': str(body.get('password') or ''),
        'host': str(body.get('host') or '').strip() or None,
        'port': body.get('port') if body.get('port') else None,
    }


@app.get('/api/health')
def health():
    return jsonify({'status': 'ok'}), 200


@app.post('/api/test-connection')
def test_connection():
    try:
        creds = get_creds()
        if not creds['email'] or not creds['password']:
            return jsonify({'success': False, 'error': 'Email and password are required.', 'provider': 'Unknown'}), 400
        return jsonify(imap_extractor.test_connection(creds)), 200
    except Exception as e:
        return jsonify({'success': False, 'error': imap_extractor.error_message(e), 'provider': 'Unknown'}), 200


@app.post('/api/providers')
def providers():
    return jsonify({'providers': imap_extractor.PROVIDERS}), 200


@app.post('/api/folders')
def folders():
    try:
        creds = get_creds()
        if not creds['email'] or not creds['password']:
            return jsonify({'error': 'Email and password are required.'}), 400
        return jsonify({'folders': imap_extractor.list_folders(creds)}), 200
    except Exception as e:
        return jsonify({'error': imap_extractor.error_message(e)}), 200


@app.post('/api/extract')
def extract():
    try:
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            body = {}
        creds = get_creds()
        folders = body.get('folders') or []
        if isinstance(folders, str):
            folders = [folders]
        start_from = body.get('startFrom') or 1
        count = body.get('count') or 100
        fields = body.get('fields') or ['fromEmail', 'subject', 'fromName', 'date']
        if not creds['email'] or not creds['password']:
            return jsonify({'error': 'Email and password are required.', 'results': [], 'stats': {'processed': 0, 'found': 0, 'skipped': 0, 'errors': 0}}), 200
        if not folders:
            return jsonify({'error': 'Select at least one folder to extract from.', 'results': [], 'stats': {'processed': 0, 'found': 0, 'skipped': 0, 'errors': 0}}), 200
        result = imap_extractor.extract_emails(creds, folders, start_from, count, fields)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({
            'error': imap_extractor.error_message(e),
            'results': [],
            'stats': {'processed': 0, 'found': 0, 'skipped': 0, 'errors': 0},
        }), 200


@app.post('/api/export')
def export():
    try:
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            body = {}
        data = body.get('data') or []
        if not isinstance(data, list):
            data = []
        fmt = str(body.get('format') or 'csv').lower()
        keys = list(dict.fromkeys(k for row in data if isinstance(row, dict) for k in row.keys()))
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
            if isinstance(row, dict):
                cleaned = {k: ('' if isinstance(v, list) else v) for k, v in row.items()}
                writer.writerow(cleaned)
        return Response(
            '\ufeff' + buf.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=extraction.csv'},
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 200


@app.get('/')
def index():
    try:
        return send_from_directory(str(FRONTEND_DIR), 'index.html')
    except Exception:
        return '<h1>MailCMH</h1><p>Frontend not found. Check deployment.</p>', 200


@app.get('/<path:filename>')
def static_files(filename):
    try:
        target = (FRONTEND_DIR / filename).resolve()
        if FRONTEND_DIR in target.parents or target == FRONTEND_DIR:
            if target.is_file():
                return send_from_directory(str(FRONTEND_DIR), filename)
        return send_from_directory(str(FRONTEND_DIR), 'index.html')
    except Exception:
        return send_from_directory(str(FRONTEND_DIR), 'index.html')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '5000'))
    app.run(host='0.0.0.0', port=port, debug=True)
