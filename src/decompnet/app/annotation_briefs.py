"""Metadata-aware note excerpts stay tentative; archives never silently become current instructions."""
from . import annotation_archives as archives, annotation_records as records, annotation_views as views
from . import sms_annotation_context as context


def texts(net, proj, rows, *, include_archives=False):
    if not rows:
        return []
    if net.cfg(proj).get('platform') not in ('sms', 'gg'):
        return [row['text'] for row in rows]
    with context.read(net):
        stored = {row['id']: net.store.one('SELECT * FROM notes WHERE project_id=? AND id=?', proj['id'], row['id']) for row in rows}
        available = [row for row in stored.values() if row is not None and not archives.is_archive(row)]
        bound = records.values(net, proj, available)
        result = []
        for item in rows:
            row = stored[item['id']]
            if row is None:
                result.append('')
            elif archives.is_archive(row):
                result.append(f"[archived original research; inactive; inspect_annotations(note, key={row['id']})]" if include_archives else '')
            elif all(row[key] is None for key in ('annotation', 'evidence', 'subject')):
                result.append(row['text'])
            else:
                state = views.describe(net, 'note', row, net.cfg(proj), bound)
                result.append(f"[research {state.get('state', 'unknown')}; {state['application']}; "
                              f"confidence {state.get('confidence', 'unknown')}] {row['text']}")
        return result


def symbol(net, proj, name):
    with context.read(net):
        row = net.store.one('SELECT * FROM symbols WHERE project_id=? AND name=?', proj['id'], name)
        if row is None or all(row[key] is None for key in ('annotation', 'evidence', 'subject')):
            return []
        state = views.describe(net, 'symbol', row, net.cfg(proj), records.values(net, proj, [row]))
        return [f"Symbol research for {name}: {state['application']}; {state.get('state', 'unknown')}; "
                f"confidence {state.get('confidence', 'unknown')}. Inspect with inspect_annotations(symbol, key=\"{name}\")."]
