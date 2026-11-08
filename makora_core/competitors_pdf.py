"""Portable PDF export of the saved competitor review; no model calls."""
from io import BytesIO
import json
import textwrap
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph

_font_lock = Lock()
ACTIONS = {'borrow': 'Взять идею', 'adapt': 'Переделать под нас',
           'avoid': 'Пропустить', 'research': 'Изучить ещё'}


def export_competitors(record, *, decisions=None, note=''):
    files = record.get('files', {})
    report = files.get('02_competitors.md', '')
    try:
        competitors = json.loads(files.get('02_competitors.json', '{}')).get('competitors', [])
    except (ValueError, AttributeError):
        competitors = []
    if not competitors and not report.strip():
        raise ValueError('Разбор аналогов ещё не готов для выгрузки.')
    with _font_lock:
        if 'MakoraSans' not in pdfmetrics.getRegisteredFontNames():
            for name, filename in [('MakoraSans', 'DejaVuSans.ttf'), ('MakoraSansBold', 'DejaVuSans-Bold.ttf')]:
                pdfmetrics.registerFont(TTFont(name, str(Path(__file__).parent / 'fonts' / filename)))
    styles = {
        'body': ParagraphStyle('body', fontName='MakoraSans', fontSize=10, leading=15,
                               textColor=colors.HexColor('#263038'), spaceAfter=7, splitLongWords=True),
        'title': ParagraphStyle('title', fontName='MakoraSansBold', fontSize=25, leading=32, spaceAfter=12),
        'heading': ParagraphStyle('heading', fontName='MakoraSansBold', fontSize=15, leading=21,
                                  spaceBefore=18, spaceAfter=9, keepWithNext=True),
        'label': ParagraphStyle('label', fontName='MakoraSansBold', fontSize=10, leading=15,
                                spaceBefore=6, spaceAfter=4, keepWithNext=True),
    }
    story = []

    def paragraph(text, style='body'):
        # Bound paragraphs so a heading never pulls a multi-page description
        # onto the next page and leaves the preceding page almost empty.
        for chunk in textwrap.wrap(str(text), width=1200, break_long_words=False,
                                   break_on_hyphens=False, replace_whitespace=False) or ['']:
            story.append(Paragraph(escape(chunk).replace('\n', '<br/>'), styles[style]))

    def link(url, title):
        parsed = urlparse(str(url))
        if parsed.scheme in ('http', 'https') and parsed.netloc:
            story.append(Paragraph(f'<link href="{escape(str(url), {chr(34): "&quot;"})}" color="#24577b">'
                                   f'{escape(str(title or url))}</link>', styles['body']))
            if title and title != url:
                paragraph(url)

    paragraph('МАКОРА / ЭТАП 03', 'label')
    paragraph('Разбор аналогов', 'title')
    paragraph('Похожие продукты, полезные идеи и сравнение с нашим проектом.')
    if record.get('status') != 'approved':
        paragraph('Рабочая версия. Разбор ещё не утверждён.')
    decisions = decisions if isinstance(decisions, dict) else {}
    for index, item in enumerate(competitors, 1):
        paragraph(f'{index:02d}. {item.get("name", "Аналог")}', 'heading')
        if item.get('summary'):
            paragraph(item['summary'])
        link(item.get('url', ''), 'Сайт продукта')
        if item.get('ideasToBorrow'):
            paragraph('Что можно взять', 'label')
            for idea in item['ideasToBorrow']:
                paragraph('• ' + str(idea))
        if item.get('comparison'):
            paragraph('Сравнение с нашим проектом', 'label')
            for row in item['comparison']:
                paragraph(row.get('criterion', ''), 'label')
                paragraph('У аналога: ' + str(row.get('theirs', 'Не указано')))
                paragraph('У нас: ' + str(row.get('ours', 'Не указано')))
        decision = decisions.get(item.get('id'), {})
        if isinstance(decision, dict) and (decision.get('action') in ACTIONS or decision.get('comment')):
            paragraph('Наше решение', 'label')
            if decision.get('action') in ACTIONS:
                paragraph(ACTIONS[decision['action']])
            if decision.get('comment'):
                paragraph(decision['comment'])
        sources = item.get('sources', [])
        confirmed = sum(any(e.get('status') == 'passed' and e.get('url') == s.get('url')
                            and e.get('quote', '') == s.get('quote', '')
                            for e in record.get('sourceEvidence', [])) for s in sources)
        paragraph('Источники', 'label')
        paragraph(f'Подтверждено источников: {confirmed} из {len(sources)}.' if confirmed
                  else 'Источники пока не подтверждены.')
        for source in sources:
            link(source.get('url', ''), source.get('title'))
            if source.get('quote'):
                paragraph('Цитата: ' + source['quote'])
            if source.get('checkedAt'):
                paragraph('Дата проверки: ' + source['checkedAt'])
    if note:
        paragraph('Общее пожелание к идее', 'heading')
        paragraph(note)
    if report.strip():
        paragraph('Полный отчёт', 'heading')
        # Preserve every line, including source URLs, without interpreting HTML.
        for line in report.splitlines():
            text = line.lstrip('#').strip() if line.startswith('#') else line
            if text.strip():
                paragraph(text, 'label' if line.startswith('#') else 'body')
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=46, leftMargin=46,
                                 topMargin=42, bottomMargin=48, title='Разбор аналогов — Макора',
                                 author='Макора', allowSplitting=True)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('MakoraSans', 8)
        canvas.setFillColor(colors.HexColor('#667580'))
        canvas.drawString(46, 25, 'МАКОРА / РАЗБОР АНАЛОГОВ')
        canvas.drawRightString(A4[0] - 46, 25, str(doc.page))
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
