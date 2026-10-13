"""Gera o e-mail semanal da agenda (semana + mês inteiro) a partir dos dados do app Calendário Pessoal.

Uso:
  python3 -I agenda_email.py <pasta_db> <eventos_google.json> <hoje AAAA-MM-DD> <saida_dir>

<pasta_db>: pasta com os JSON exportados de data/users/me (shifts, tasks, series, notes...),
  no formato do ArtifactData (cada arquivo tem data.v = JSON em texto).
<eventos_google.json>: lista [{"date","time","end","title","med":true|false}] (Medway e agenda principal).
Escreve subject.txt, body.html e body.txt em <saida_dir>.
"""
import json, os, sys, html
from datetime import date, timedelta

WD = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo']
WDS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']
MO = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
COL = {'plantao': '#e5484d', 'estudo': '#3b82f6', 'academia': '#f08c2e', 'yoga': '#30a46c', 'pessoal': '#8e4ec6', 'lembrete': '#c99a06'}


def load(dbdir, name, default):
    p = os.path.join(dbdir, name + '.json')
    if not os.path.exists(p):
        return default
    doc = json.load(open(p))
    doc = doc.get('data', doc)
    try:
        return json.loads(doc['v'])
    except Exception:
        return default


def D(s):
    return date.fromisoformat(s)


def hm(t):
    if not t:
        return ''
    h, m = t.split(':')
    return f"{int(h)}h" if m == '00' else f"{int(h)}h{m}"


def occurs(r, d):
    s = D(r['start'])
    if d < s or (r.get('until') and d >= D(r['until'])) or d.isoformat() in (r.get('skip') or []):
        return False
    diff = (d - s).days
    rule = r.get('rule')
    if rule == 'daily':
        return True
    if rule == 'weekly':
        return diff % 7 == 0
    if rule == 'biweekly':
        return diff % 14 == 0
    if rule == 'monthly':
        return d.day == s.day
    if rule in ('odd', 'even'):
        par = 'odd' if d.isocalendar()[1] % 2 else 'even'
        return diff % 7 == 0 and par == rule
    return diff == 0


def items_on(d, shifts, tasks, series, gev):
    ds = d.isoformat()
    out = []
    for s in shifts:
        if s['date'] == ds:
            kind = 'Porta' if s.get('kind') == 'porta' else 'Tutora'
            out.append((s['start'], s['end'], f'Plantão {kind}', 'plantao'))
    for t in tasks:
        if t.get('date') == ds:
            title = t['title']
            if t.get('type') == 'estudo':
                title = 'Estudo: ' + title
            if t.get('type') == 'lembrete':
                title = 'Lembrete: ' + title
            if t.get('done'):
                title += ' ✓'
            out.append((t.get('time') or '', t.get('end') or '', title, t.get('type') or 'pessoal'))
    for r in series:
        if occurs(r, d):
            out.append((r.get('time') or '', r.get('end') or '', r['title'], r.get('type') or 'pessoal'))
    med = [e for e in gev if e['date'] == ds and e.get('med')]
    if med:
        med.sort(key=lambda e: e['time'])
        out.append((med[0]['time'], max(e['end'] for e in med), 'Medway: ' + '; '.join(e['title'] for e in med), 'estudo'))
    for e in gev:
        if e['date'] == ds and not e.get('med'):
            out.append((e['time'], e['end'], e['title'], 'pessoal'))
    out.sort(key=lambda x: x[0] or '00:00')
    return out


def tm(a, b):
    if not a:
        return 'dia todo'
    return hm(a) + ('–' + hm(b) if b and b > a else '')


def short(it):
    a, b, title, typ = it
    if typ == 'plantao':
        return f'Plantão {hm(a)}'
    if title.startswith('Medway'):
        return f'Estudo {hm(a)}'
    return (f'{hm(a)} ' if a else '') + title[:22]


def main():
    dbdir, gpath, today_s, outdir = sys.argv[1:5]
    today = D(today_s)
    shifts = load(dbdir, 'shifts', [])
    tasks = load(dbdir, 'tasks', [])
    series = load(dbdir, 'series', [])
    notes = load(dbdir, 'notes', [])
    gev = json.load(open(gpath)) if os.path.exists(gpath) else []
    E = html.escape
    count = 0

    def day_rows(d):
        nonlocal count
        its = items_on(d, shifts, tasks, series, gev)
        count += len(its)
        if not its:
            return '<div style="color:#999">livre</div>'
        return '<table style="border-collapse:collapse">' + ''.join(
            f'<tr><td style="padding:1px 10px 1px 0;color:#4f5b64;white-space:nowrap;vertical-align:top">{tm(a, b)}</td>'
            f'<td style="padding:1px 0;border-left:3px solid {COL.get(t, "#888")};padding-left:6px">{E(title)}</td></tr>'
            for a, b, title, t in its) + '</table>'

    def day_txt(d):
        its = items_on(d, shifts, tasks, series, gev)
        return '\n'.join(f'   {tm(a, b)}  {title}' for a, b, title, t in its) or '   livre'

    week = [today + timedelta(days=i) for i in range(1, 8)]
    months = [(today.year, today.month)]
    last = (date(today.year + (today.month == 12), today.month % 12 + 1, 1) - timedelta(days=1))
    if (last - today).days < 10:
        months.append((today.year + (today.month == 12), today.month % 12 + 1))

    H = ['<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#12181c;max-width:720px">']
    T = []
    H.append(f'<h2 style="margin:0 0 4px">Sua agenda</h2><div style="color:#4f5b64;margin-bottom:16px">Enviado em {today.day} de {MO[today.month-1]} de {today.year}</div>')
    H.append('<h3 style="margin:18px 0 8px;border-bottom:2px solid #1c5961;padding-bottom:4px">Próximos 7 dias</h3>')
    T.append('PRÓXIMOS 7 DIAS')
    for d in week:
        H.append(f'<p style="margin:10px 0 2px"><b>{WD[d.weekday()].capitalize()}, {d.day}/{d.month:02d}</b></p>{day_rows(d)}')
        T.append(f'{WD[d.weekday()].capitalize()}, {d.day}/{d.month:02d}\n{day_txt(d)}')

    for (y, m) in months:
        first = date(y, m, 1)
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        days = [first + timedelta(days=i) for i in range((nxt - first).days)]
        H.append(f'<h3 style="margin:24px 0 8px;border-bottom:2px solid #1c5961;padding-bottom:4px">{MO[m-1].capitalize()} {y} — o mês inteiro</h3>')
        # grade
        H.append('<table style="border-collapse:collapse;width:100%;table-layout:fixed;font-size:11px">')
        H.append('<tr>' + ''.join(f'<th style="border:1px solid #ddd;background:#eee">{w}</th>' for w in WDS) + '</tr>')
        cur = first - timedelta(days=first.weekday())
        while cur < nxt:
            H.append('<tr>')
            for _ in range(7):
                if cur.month == m:
                    its = items_on(cur, shifts, tasks, series, gev)
                    bg = '#dfeced' if cur == today else '#ffffff'
                    cell = ''.join(f'<br><span style="color:{COL.get(it[3], "#888")}">■</span>{E(short(it))}' for it in its)
                    H.append(f'<td style="vertical-align:top;height:60px;padding:3px;border:1px solid #ddd;background:{bg}"><b>{cur.day}</b>{cell}</td>')
                else:
                    H.append('<td style="border:1px solid #ddd"></td>')
                cur += timedelta(days=1)
            H.append('</tr>')
        H.append('</table>')
        # lista dia a dia
        H.append('<div style="margin-top:12px">')
        T.append(f'\n{MO[m-1].upper()} {y} — O MÊS INTEIRO')
        for d in days:
            H.append(f'<p style="margin:8px 0 2px"><b>{WDS[d.weekday()]} {d.day}/{d.month:02d}</b></p>{day_rows(d)}')
            T.append(f'{WDS[d.weekday()]} {d.day}/{d.month:02d}\n{day_txt(d)}')
        H.append('</div>')

    pins = [n for n in notes if n.get('pin')]
    if pins:
        H.append('<h3 style="margin:24px 0 8px;border-bottom:2px solid #1c5961;padding-bottom:4px">Notas fixadas</h3>')
        H.extend(f'<div style="margin:4px 0;white-space:pre-wrap">• {E(n["text"])}</div>' for n in pins)
        T.append('\nNOTAS FIXADAS\n' + '\n'.join('• ' + n['text'] for n in pins))
    app = 'https://claude.ai/artifact/TMmHBBRkdEWvSuYTGKJhFh'
    H.append(f'<p style="color:#84909a;font-size:12px;margin-top:24px">Cópia automática do seu Calendário Pessoal, enviada todo domingo. App: <a href="{app}">{app}</a></p></div>')
    T.append(f'\nCópia automática do seu Calendário Pessoal, enviada todo domingo. App: {app}')

    a, b = week[0], week[-1]
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, 'subject.txt'), 'w').write(f'Sua agenda · semana de {a.day:02d}/{a.month:02d} a {b.day:02d}/{b.month:02d} + {MO[months[-1][1]-1]}')
    open(os.path.join(outdir, 'body.html'), 'w').write(''.join(H))
    open(os.path.join(outdir, 'body.txt'), 'w').write('\n'.join(T))
    print(json.dumps({'items_week_and_month': count, 'months': months}))


if __name__ == '__main__':
    main()
