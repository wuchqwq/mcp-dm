"""Persistent read-only JSONL probe port for one configured image workspace."""
import json
import sys
from image_workspace import Workspace, strict_json, failure, BACKEND
from image_numeric import NumericReader, probe


def main():
    workspace = Workspace(sys.argv[1], False)
    reader = NumericReader()
    for raw in sys.stdin.buffer:
        serial = None
        try:
            if len(raw) > 32768:
                raise ValueError('Probe request exceeds 32 KiB')
            message = strict_json(raw.decode('utf-8'))
            if type(message) is not dict or set(message) != {'serial', 'parameters'}:
                raise ValueError('Typed probe message required')
            serial, request = message['serial'], message['parameters']
            if type(serial) is not int or serial < 1 or type(request) is not dict or set(request)-{'object_id','points','coordinate_space','component'}:
                raise ValueError('Invalid probe identity or fields')
            result = probe(workspace, request, reader)
            reply = dict(serial=serial, ok=True, result=dict(state='completed', backend=BACKEND, **result))
        except Exception as error:
            reply = dict(serial=serial, **failure(error))
        sys.stdout.write(json.dumps(reply, ensure_ascii=True, allow_nan=False)+'\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
