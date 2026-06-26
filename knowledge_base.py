# -*- coding: utf-8 -*-
"""Local knowledge-base indexing and retrieval helpers.

This module intentionally avoids external APIs. It builds a SQLite inverted
index over normalized Chinese/English terms and ranks chunks locally.
"""

import math
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime


SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.xlsx', '.txt', '.md'}

S2T = str.maketrans({
    '\u4e1a': '\u696d', '\u52a1': '\u52d9', '\u4ef7': '\u50f9', '\u62a5': '\u5831',
    '\u56e2': '\u5718', '\u8d44': '\u8cc7', '\u76d6': '\u84cb', '\u9669': '\u96aa',
    '\u79cd': '\u7a2e', '\u8d23': '\u8cac', '\u8d54': '\u8ce0', '\u73b0': '\u73fe',
    '\u8d26': '\u8cec', '\u6237': '\u6236', '\u6761': '\u689d', '\u4ea7': '\u7522',
    '\u533b': '\u91ab', '\u5bff': '\u58fd', '\u8f7b': '\u8f15', '\u7f34': '\u7e73',
    '\u8d39': '\u8cbb', '\u6da6': '\u6f64', '\u7a0e': '\u7a05', '\u540e': '\u5f8c',
    '\u50a8': '\u5132', '\u5907': '\u5099', '\u603b': '\u7e3d', '\u5f00': '\u958b',
    '\u8425': '\u71df', '\u8fd0': '\u904b', '\u8d22': '\u8ca1', '\u5ba1': '\u5be9',
    '\u8ba1': '\u8a08', '\u4e1c': '\u6771', '\u5458': '\u54e1', '\u5185': '\u5167',
    '\u957f': '\u9577', '\u573a': '\u5834', '\u7ea2': '\u7d05', '\u4e07': '\u842c',
    '\u989d': '\u984d', '\u72b9': '\u7336', '\u7ed9': '\u7d66', '\u79ef': '\u7a4d',
    '\u5151': '\u514c', '\u8d60': '\u8d08'
})

T2S = str.maketrans({v: k for k, v in S2T.items()})

SYNONYMS = {
    '\u6350\u6b3e': ['\u6350\u8d60', '\u6350\u8d08', '\u6148\u5584', '\u516c\u76ca'],
    '\u6350\u8d60': ['\u6350\u6b3e', '\u6350\u8d08', '\u6148\u5584', '\u516c\u76ca'],
    '\u6350\u8d08': ['\u6350\u6b3e', '\u6350\u8d60', '\u6148\u5584', '\u516c\u76ca'],
    '\u793e\u533a': ['\u793e\u5340', '\u793e\u6703', '\u793e\u4f1a'],
    '\u793e\u5340': ['\u793e\u533a', '\u793e\u6703', '\u793e\u4f1a'],
    '\u516c\u76ca': ['\u6148\u5584', '\u6350\u6b3e', '\u6350\u8d08'],
    '\u6148\u5584': ['\u516c\u76ca', '\u6350\u6b3e', '\u6350\u8d08'],
}

STOP_TERMS = {
    '\u8fd9\u4e2a', '\u90a3\u4e2a', '\u4ec0\u4e48', '\u600e\u4e48', '\u591a\u5c11',
    '\u662f\u5426', '\u53ef\u4ee5', '\u4e00\u4e0b', '\u5e2e\u6211', '\u8bf7\u95ee',
    '\u8d44\u6599', '\u6587\u4ef6', '\u91cc\u9762', '\u5173\u4e8e', '\u5982\u679c',
    '\u9700\u8981', '\u67e5\u8be2', '\u544a\u8bc9', '\u6211\u4eec', '\u4f60\u4eec',
    '\u6709\u6ca1\u6709', '\u662f\u4e0d\u662f', '\u4e3a\u4ec0\u4e48',
    '\u516c\u53f8', '\u96c6\u56e2', '\u672c\u96c6\u5718', '\u53bb\u5e74', '\u4eca\u5e74',
}

NUMERIC_QUESTION_TERMS = {'\u591a\u5c11', '\u91d1\u989d', '\u6bd4\u4f8b', '\u51e0', '\u7387', 'amount', 'rate'}
NUMERIC_PATTERN = re.compile(r'(\d[\d,]*(?:\.\d+)?\s*(?:%|\u842c|\u4e07|\u5104|\u7f8e\u5143|\u6e2f\u5143|元|美元)?)')


def resolve_path(base_dir, path):
    value = str(path or '')
    if not os.path.isabs(value):
        value = os.path.join(base_dir, value)
    return value


def connect(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path):
    with connect(db_path) as conn:
        conn.executescript("""
CREATE TABLE IF NOT EXISTS kb_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection TEXT NOT NULL DEFAULT '保险知识',
    title TEXT NOT NULL,
    source_filename TEXT,
    stored_filename TEXT,
    source_type TEXT,
    trusted_level TEXT DEFAULT '正式资料',
    product_name TEXT,
    version TEXT,
    effective_date TEXT,
    enabled INTEGER DEFAULT 1,
    chunk_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kb_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    page_number INTEGER,
    section_path TEXT,
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES kb_documents(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS kb_chunk_terms (
    term TEXT NOT NULL,
    chunk_id INTEGER NOT NULL,
    document_id INTEGER NOT NULL,
    tf REAL NOT NULL DEFAULT 1,
    PRIMARY KEY(term, chunk_id),
    FOREIGN KEY(chunk_id) REFERENCES kb_chunks(id) ON DELETE CASCADE,
    FOREIGN KEY(document_id) REFERENCES kb_documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_kb_documents_collection ON kb_documents(collection, enabled);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_document ON kb_chunks(document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_kb_chunk_terms_term ON kb_chunk_terms(term);
CREATE INDEX IF NOT EXISTS idx_kb_chunk_terms_chunk ON kb_chunk_terms(chunk_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunk_terms_document ON kb_chunk_terms(document_id);
""")


def normalize_text(text):
    text = text or ''
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def normalize_for_search(text):
    return re.sub(r'\s+', '', str(text or '').lower())


def text_variants(text):
    text = str(text or '').lower()
    variants = {text, text.translate(S2T), text.translate(T2S)}
    return {item for item in variants if item}


def add_term_with_variants(terms, term):
    if not term:
        return
    for variant in text_variants(term):
        terms.add(variant)
        for synonym in SYNONYMS.get(variant, []):
            terms.update(text_variants(synonym))


def extract_relative_year_terms(query, now=None):
    now = now or datetime.now()
    mapping = {
        '\u4eca\u5e74': now.year,
        '\u53bb\u5e74': now.year - 1,
        '\u524d\u5e74': now.year - 2,
    }
    terms = []
    for marker, year in mapping.items():
        if marker in str(query or ''):
            terms.extend([str(year), f'{year}\u5e74'])
    return terms


def build_query_terms(query, limit=120):
    raw = str(query or '')
    terms = set()
    add_term_with_variants(terms, normalize_for_search(raw))
    for year_term in extract_relative_year_terms(raw):
        add_term_with_variants(terms, year_term)
    for token in re.findall(r'[A-Za-z0-9_\-\u4e00-\u9fff]{2,}', raw.lower()):
        add_term_with_variants(terms, token)
    chinese = ''.join(re.findall(r'[\u4e00-\u9fff]', raw))
    for size in (2, 3, 4):
        for i in range(0, max(0, len(chinese) - size + 1)):
            add_term_with_variants(terms, chinese[i:i + size])
    useful = [term for term in terms if len(term) >= 2 and term not in STOP_TERMS]
    useful.sort(key=lambda item: (len(item), item), reverse=True)
    return useful[:limit]


def iter_chinese_segments(text):
    for segment in re.findall(r'[\u4e00-\u9fff]+', text or ''):
        if len(segment) >= 2:
            yield segment


def index_terms_for_text(text, base_weight=1.0):
    counts = Counter()
    raw_text = str(text or '').lower()
    variants = {raw_text, raw_text.translate(S2T)}
    for variant in variants:
        compact = normalize_for_search(variant)
        for token in re.findall(r'[A-Za-z0-9_\-]{2,}', variant):
            if token not in STOP_TERMS:
                counts[token] += base_weight * 1.2
        for token in re.findall(r'\d{4}\u5e74|\d{4}|\d[\d,]*(?:\.\d+)?', compact):
            counts[token] += base_weight * 1.5
        for segment in iter_chinese_segments(compact):
            if segment not in STOP_TERMS and len(segment) <= 12:
                counts[segment] += base_weight * 1.1
            for size in (2, 3):
                if len(segment) < size:
                    continue
                for i in range(0, len(segment) - size + 1):
                    term = segment[i:i + size]
                    if term not in STOP_TERMS:
                        counts[term] += base_weight
    for term, synonyms in SYNONYMS.items():
        if term in counts:
            for synonym in synonyms:
                for variant in text_variants(synonym):
                    counts[variant] += counts[term] * 0.7
    return counts


def chunk_text(text, chunk_size=900, overlap=120):
    text = normalize_text(text)
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    chunks = []
    current = ''
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= chunk_size:
            current = f"{current}\n\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= chunk_size:
            current = paragraph
        else:
            start = 0
            step = max(1, chunk_size - overlap)
            while start < len(paragraph):
                chunks.append(paragraph[start:start + chunk_size].strip())
                start += step
            current = ''
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def extract_page_number(content):
    match = re.search(r'\[第(\d+)页\]', content or '')
    return int(match.group(1)) if match else None


def extract_text_from_docx(path):
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("缺少 python-docx，无法读取 Word 文件。请先安装 requirements.txt 中的依赖。") from exc
    doc = Document(path)
    lines = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text and cell.text.strip()]
            if cells:
                lines.append(' | '.join(cells))
    return '\n'.join(lines)


def extract_text_from_pdf(path):
    try:
        import fitz
    except ImportError:
        fitz = None
    if fitz:
        lines = []
        with fitz.open(path) as doc:
            for page_index, page in enumerate(doc, start=1):
                page_text = page.get_text("text").strip()
                if page_text:
                    lines.append(f"\n[第{page_index}页]\n{page_text}")
        return '\n'.join(lines)
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("缺少 PyMuPDF 或 pypdf，无法读取 PDF。请先安装 requirements.txt 中的依赖。") from exc
    reader = PdfReader(path)
    lines = []
    for page_index, page in enumerate(reader.pages, start=1):
        page_text = (page.extract_text() or '').strip()
        if page_text:
            lines.append(f"\n[第{page_index}页]\n{page_text}")
    return '\n'.join(lines)


def extract_text_from_plain(path):
    for encoding in ('utf-8', 'utf-8-sig', 'gbk', 'gb2312'):
        try:
            with open(path, 'r', encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()


def extract_text_from_xlsx(path):
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("缺少 openpyxl，无法读取 Excel 文件。请先安装 requirements.txt 中的依赖。") from exc
    workbook = load_workbook(path, read_only=True, data_only=True)
    lines = []
    for sheet in workbook.worksheets:
        lines.append(f"\n[工作表：{sheet.title}]")
        for row in sheet.iter_rows(values_only=True):
            values = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
            if values:
                lines.append(' | '.join(values))
    workbook.close()
    return '\n'.join(lines)


def extract_text_from_file(path, ext=None):
    ext = (ext or os.path.splitext(path)[1]).lower()
    if ext in ('.txt', '.md'):
        return extract_text_from_plain(path)
    if ext == '.docx':
        return extract_text_from_docx(path)
    if ext == '.pdf':
        return extract_text_from_pdf(path)
    if ext == '.xlsx':
        return extract_text_from_xlsx(path)
    raise RuntimeError(f"暂不支持 {ext} 文件。当前支持 PDF、DOCX、XLSX、TXT、MD。")


def build_index_for_document(conn, document_id):
    document = conn.execute("SELECT * FROM kb_documents WHERE id = ?", (document_id,)).fetchone()
    if not document:
        return 0
    conn.execute("DELETE FROM kb_chunk_terms WHERE document_id = ?", (document_id,))
    chunks = conn.execute("""
        SELECT id, title, content
        FROM kb_chunks
        WHERE document_id = ? AND enabled = 1
    """, (document_id,)).fetchall()
    rows = []
    for chunk in chunks:
        counts = Counter()
        metadata = " ".join(str(document[key] or '') for key in (
            'collection', 'title', 'product_name', 'version', 'effective_date', 'trusted_level'
        ))
        counts.update(index_terms_for_text(metadata, base_weight=3.0))
        counts.update(index_terms_for_text(chunk['title'] or '', base_weight=2.0))
        counts.update(index_terms_for_text(chunk['content'] or '', base_weight=1.0))
        for term, value in counts.most_common(1800):
            if len(term) >= 2 and term not in STOP_TERMS:
                rows.append((term, chunk['id'], document_id, round(float(value), 4)))
    if rows:
        conn.executemany("""
            INSERT OR REPLACE INTO kb_chunk_terms(term, chunk_id, document_id, tf)
            VALUES (?, ?, ?, ?)
        """, rows)
    return len(rows)


def rebuild_all_indexes(db_path):
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute("DELETE FROM kb_chunk_terms")
        doc_ids = [row['id'] for row in conn.execute("SELECT id FROM kb_documents").fetchall()]
        total_terms = 0
        for doc_id in doc_ids:
            total_terms += build_index_for_document(conn, doc_id)
        return {'documents': len(doc_ids), 'terms': total_terms}


def ensure_index_ready(conn):
    term_count = conn.execute("SELECT COUNT(*) FROM kb_chunk_terms").fetchone()[0]
    chunk_count = conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0]
    if chunk_count and not term_count:
        doc_ids = [row['id'] for row in conn.execute("SELECT id FROM kb_documents").fetchall()]
        for doc_id in doc_ids:
            build_index_for_document(conn, doc_id)


def list_documents(db_path):
    init_db(db_path)
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute("""
            SELECT d.*,
                   COALESCE(t.index_terms, 0) AS index_terms
            FROM kb_documents d
            LEFT JOIN (
                SELECT document_id, COUNT(*) AS index_terms
                FROM kb_chunk_terms
                GROUP BY document_id
            ) t ON t.document_id = d.id
            ORDER BY d.updated_at DESC, d.id DESC
        """).fetchall()]


def get_index_stats(db_path):
    init_db(db_path)
    with connect(db_path) as conn:
        return {
            'documents': conn.execute("SELECT COUNT(*) FROM kb_documents").fetchone()[0],
            'chunks': conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0],
            'terms': conn.execute("SELECT COUNT(*) FROM kb_chunk_terms").fetchone()[0],
            'unique_terms': conn.execute("SELECT COUNT(DISTINCT term) FROM kb_chunk_terms").fetchone()[0],
        }


def query_has_numeric_intent(query):
    text = str(query or '')
    return any(term in text for term in NUMERIC_QUESTION_TERMS) or bool(re.search(r'\d', text))


def make_debug_snippet(content, matched_terms, max_chars=420):
    text = str(content or '').strip()
    if len(text) <= max_chars:
        return text
    best_pos = -1
    preferred_terms = [
        term for term in (matched_terms or [])
        if not re.fullmatch(r'\d{4}\u5e74|\d{4}|\d[\d,.]*', str(term or ''))
    ]
    for term in sorted(preferred_terms, key=len, reverse=True):
        if len(term) < 2:
            continue
        pos = text.find(term)
        if pos >= 0:
            best_pos = pos
            break
    if best_pos < 0:
        for term in sorted(matched_terms or [], key=len, reverse=True):
            if len(term) < 2:
                continue
            pos = text.find(term)
            if pos >= 0:
                best_pos = pos
                break
    if best_pos < 0:
        number_match = NUMERIC_PATTERN.search(text)
        if number_match:
            best_pos = number_match.start()
    if best_pos < 0:
        return text[:max_chars].rstrip() + '...'
    start = max(0, best_pos - max_chars // 3)
    end = min(len(text), start + max_chars)
    start = max(0, end - max_chars)
    prefix = '...' if start > 0 else ''
    suffix = '...' if end < len(text) else ''
    return prefix + text[start:end].strip() + suffix


def search_knowledge(db_path, query, top_k=5, min_score=8, candidate_limit=240, auto_rebuild=True):
    init_db(db_path)
    terms = build_query_terms(query)
    if not terms:
        return []
    with connect(db_path) as conn:
        if auto_rebuild:
            ensure_index_ready(conn)
        placeholders = ','.join(['?'] * len(terms))
        rows = conn.execute(f"""
            SELECT term, chunk_id, document_id, tf
            FROM kb_chunk_terms
            WHERE term IN ({placeholders})
        """, terms).fetchall()
        if not rows:
            return []
        total_chunks = conn.execute("SELECT COUNT(*) FROM kb_chunks WHERE enabled = 1").fetchone()[0] or 1
        df = Counter(row['term'] for row in rows)
        per_chunk = defaultdict(lambda: {'score': 0.0, 'terms': set(), 'document_id': None})
        for row in rows:
            term = row['term']
            idf = math.log((total_chunks + 1) / (df[term] + 1)) + 1.0
            length_boost = min(3.0, max(1.0, len(term) / 3.0))
            rare_boost = 2.5 if df[term] <= max(3, total_chunks // 50) else 1.0
            score = float(row['tf']) * idf * length_boost * rare_boost
            item = per_chunk[row['chunk_id']]
            item['score'] += score
            item['terms'].add(term)
            item['document_id'] = row['document_id']
        ranked = sorted(per_chunk.items(), key=lambda item: item[1]['score'], reverse=True)[:candidate_limit]
        chunk_ids = [item[0] for item in ranked]
        placeholders = ','.join(['?'] * len(chunk_ids))
        details = {
            row['id']: dict(row)
            for row in conn.execute(f"""
                SELECT
                    c.id, c.content, c.page_number, c.chunk_index,
                    d.title, d.collection, d.product_name, d.version,
                    d.effective_date, d.trusted_level
                FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.document_id
                WHERE c.id IN ({placeholders}) AND c.enabled = 1 AND d.enabled = 1
            """, chunk_ids).fetchall()
        }
    numeric_intent = query_has_numeric_intent(query)
    results = []
    for chunk_id, scoring in ranked:
        detail = details.get(chunk_id)
        if not detail:
            continue
        score = scoring['score']
        content = detail.get('content') or ''
        if numeric_intent and NUMERIC_PATTERN.search(content):
            score += 8
        if detail.get('page_number'):
            score += 0.5
        detail['score'] = round(score, 2)
        detail['matched_terms'] = ', '.join(sorted(scoring['terms'], key=len, reverse=True)[:10])
        detail['snippet'] = make_debug_snippet(content, scoring['terms'])
        results.append(detail)
    results.sort(key=lambda item: item['score'], reverse=True)
    if min_score is not None:
        results = [item for item in results if item.get('score', 0) >= float(min_score)]
    return results[:top_k]


def format_knowledge_context(chunks, max_chars=2500):
    lines = []
    used_chars = 0
    for index, item in enumerate(chunks, start=1):
        source_parts = [item.get('title') or '未命名资料']
        if item.get('collection'):
            source_parts.append(item['collection'])
        if item.get('product_name'):
            source_parts.append(item['product_name'])
        if item.get('version'):
            source_parts.append(f"版本:{item['version']}")
        if item.get('effective_date'):
            source_parts.append(f"生效:{item['effective_date']}")
        if item.get('page_number'):
            source_parts.append(f"第{item['page_number']}页")
        content = str(item.get('content') or '').strip()
        entry = f"[资料{index}] {' | '.join(source_parts)}\n{content}\n"
        remaining = max_chars - used_chars
        if remaining <= 0:
            break
        if len(entry) > remaining:
            entry = entry[:remaining].rstrip()
        lines.append(entry)
        used_chars += len(entry)
    return "\n".join(lines).strip()
