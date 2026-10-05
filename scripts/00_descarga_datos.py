#!/usr/bin/env python3
"""
Qué hace, paso a paso:
  1) Descarga (si no existen ya) los volcados de Reddit publicados en la
     asignatura: RS_2025.zst, RC_2025.zst, Reddit_Descripcion.md y los
     equivalentes de r/OpinionesPolemicas.
  2) A partir de RS_2025.zst / RC_2025.zst, se queda solo con los 6
     subreddits elegidos (TARGET_SUBREDDITS) y genera un subconjunto más
     pequeño.
  3) Para cada uno de esos 6 subreddits, filtra y selecciona 40 hilos (con
     diversidad temporal y buena puntuación) y 25 comentarios por hilo,
     aplicando los criterios de calidad descritos en el enunciado (sin bots,
     sin texto vacío/borrado, longitudes razonables, etc.) y genera
     data/<Subreddit>_filtrado.json.
  4) Hace lo mismo para r/OpinionesPolemicas (10 hilos x 50 comentarios) y
     genera data/OpinionesPolemicas_filtrado.json.

IMPORTANTE:
  - Los volcados originales (RS_2025.zst / RC_2025.zst) ocupan más de 60 GB,
    así que este script NO se ejecuta como parte de la entrega: los JSON ya
    filtrados (data/*_filtrado.json) están incluidos directamente en el
    proyecto. Este script se deja documentado y funcional por si se quiere
    reproducir la extracción desde cero.
  - Hace falta la librería `zstandard` (pip install zstandard).

Uso:
    python scripts/00_descarga_datos.py --help
    python scripts/00_descarga_datos.py --download --subset --extract --opiniones
"""

import argparse
import io
import json
import re
import urllib.request
from collections import defaultdict
from datetime import datetime, UTC
from pathlib import Path

import zstandard as zstd

# ---------------------------------------------------------------------------
# Rutas y configuración general
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"      # .zst originales / subconjuntos
DATA_DIR = PROJECT_ROOT / "data"             # JSON finales por subreddit

RAW_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://valencia.inf.um.es/valencia-plne"

FILES_TO_DOWNLOAD = {
    "RS_2025.zst": f"{BASE_URL}/RS_2025.zst",
    "RC_2025.zst": f"{BASE_URL}/RC_2025.zst",
    "Reddit_Descripcion.md": f"{BASE_URL}/Reddit_Descripcion.md",
    "RS_OpinionesPolemicas_2025.zst": f"{BASE_URL}/RS_OpinionesPolemicas_2025.zst",
    "RC_OpinionesPolemicas_2025.zst": f"{BASE_URL}/RC_OpinionesPolemicas_2025.zst",
}

RS_INPUT = RAW_DIR / "RS_2025.zst"
RC_INPUT = RAW_DIR / "RC_2025.zst"
RS_SUBSET = RAW_DIR / "RS_subset_6subreddits.zst"
RC_SUBSET = RAW_DIR / "RC_subset_6subreddits.zst"

RS_OP_INPUT = RAW_DIR / "RS_OpinionesPolemicas_2025.zst"
RC_OP_INPUT = RAW_DIR / "RC_OpinionesPolemicas_2025.zst"

# Los 6 subreddits elegidos para el corpus principal (clasificación, similitud,
# subjetividad, resumen).
TARGET_SUBREDDITS = {
    "python": "Python",
    "chemistry": "Chemistry",
    "investing": "Investing",
    "soccer": "Soccer",
    "cooking": "Cooking",
    "autism": "Autism",
}

# Parámetros recomendados por el enunciado: al menos 25 comentarios de 40
# hilos de cada uno de los 6 subreddits.
N_SUBMISSIONS_PER_SUBREDDIT = 40
N_COMMENTS_PER_SUBMISSION = 25

# Parámetros para r/OpinionesPolemicas (apartado 6): 10 hilos x 50 comentarios.
N_SUBMISSIONS_OPINIONES = 10
N_COMMENTS_OPINIONES = 50

BOT_REGEX = re.compile(r"\bbot\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 1) Descarga de los ficheros originales
# ---------------------------------------------------------------------------

def download_files():
    """Descarga los .zst / .md publicados en la asignatura si no existen ya."""
    for filename, url in FILES_TO_DOWNLOAD.items():
        dest = RAW_DIR / filename
        if dest.exists():
            print(f"[descarga] Ya existe, se omite: {dest}")
            continue
        print(f"[descarga] {url} -> {dest}")
        urllib.request.urlretrieve(url, dest)
    print("[descarga] Completada.")


# ---------------------------------------------------------------------------
# Utilidades comunes de lectura/escritura .zst
# ---------------------------------------------------------------------------

def stream_zst_file(filepath):
    """Lee un .zst línea a línea y devuelve cada objeto JSON."""
    dctx = zstd.ZstdDecompressor(max_window_size=2**31)
    with open(filepath, "rb") as fh:
        with dctx.stream_reader(fh) as reader:
            text_stream = io.TextIOWrapper(reader, encoding="utf-8", errors="ignore")
            for line in text_stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def open_zst_writer(filepath, level=3):
    """Devuelve (fh, writer) para escribir JSONL comprimido en .zst."""
    fh = open(filepath, "wb")
    cctx = zstd.ZstdCompressor(level=level)
    writer = cctx.stream_writer(fh)
    return fh, writer


def write_json_line(writer, obj):
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    writer.write(line.encode("utf-8"))


def contains_bot(text):
    if not text:
        return False
    return bool(BOT_REGEX.search(text))


def clean_text(text):
    if text is None:
        return ""
    return str(text).strip()


def created_iso(created_utc):
    if not created_utc:
        return None
    return datetime.fromtimestamp(created_utc, UTC).isoformat()


def is_valid_text_length(text, min_len, max_len):
    text = clean_text(text)
    return min_len <= len(text) <= max_len


def split_into_time_blocks(items, n_blocks):
    """Divide una lista ya ordenada por fecha en n bloques temporales."""
    if not items:
        return []
    n = len(items)
    blocks = []
    for i in range(n_blocks):
        start = (i * n) // n_blocks
        end = ((i + 1) * n) // n_blocks
        block = items[start:end]
        if block:
            blocks.append(block)
    return blocks


def select_diverse_top_submissions(candidates, n_submissions):
    """Prioriza 1) diversidad temporal y 2) score alto dentro de cada bloque."""
    if not candidates:
        return []
    candidates_sorted_by_time = sorted(candidates, key=lambda x: x.get("created_utc", 0))
    blocks = split_into_time_blocks(candidates_sorted_by_time, n_submissions)

    selected, selected_ids = [], set()
    for block in blocks:
        best = max(block, key=lambda x: x.get("score", 0) or 0)
        if best["id"] not in selected_ids:
            selected.append(best)
            selected_ids.add(best["id"])

    if len(selected) < n_submissions:
        remaining = [x for x in candidates if x["id"] not in selected_ids]
        remaining = sorted(remaining, key=lambda x: x.get("score", 0) or 0, reverse=True)
        for item in remaining:
            if len(selected) >= n_submissions:
                break
            selected.append(item)
            selected_ids.add(item["id"])

    return selected[:n_submissions]


def select_diverse_comments(comments, num_comments):
    """Selecciona comentarios priorizando diversidad temporal (NO usa score)."""
    if not comments:
        return []
    comments_sorted = sorted(comments, key=lambda x: x.get("created_utc", 0))
    if len(comments_sorted) <= num_comments:
        return comments_sorted

    blocks = split_into_time_blocks(comments_sorted, num_comments)
    selected, selected_ids = [], set()
    for block in blocks:
        best = min(block, key=lambda x: abs(len(clean_text(x.get("body", ""))) - 250))
        if best["id"] not in selected_ids:
            selected.append(best)
            selected_ids.add(best["id"])

    if len(selected) < num_comments:
        for c in comments_sorted:
            if c["id"] in selected_ids:
                continue
            selected.append(c)
            selected_ids.add(c["id"])
            if len(selected) >= num_comments:
                break

    return selected[:num_comments]


# ---------------------------------------------------------------------------
# 2) Subconjunto de los 6 subreddits elegidos (reduce 60GB -> unos pocos GB)
# ---------------------------------------------------------------------------

def extract_submissions_subset(rs_input, rs_output, target_subreddits):
    """Guarda en rs_output todos los hilos de los subreddits indicados y
    devuelve el conjunto de link_ids (t3_xxx) para filtrar luego comentarios."""
    selected_link_ids = set()
    total_scanned = total_written = 0
    print("Extrayendo submissions del subconjunto de 6 subreddits...")

    fh_out, writer = open_zst_writer(rs_output)
    try:
        for obj in stream_zst_file(rs_input):
            total_scanned += 1
            subreddit = obj.get("subreddit", "").lower()
            if subreddit not in target_subreddits:
                continue
            post_id = obj.get("id")
            if not post_id:
                continue
            write_json_line(writer, obj)
            total_written += 1
            selected_link_ids.add(f"t3_{post_id}")
            if total_written % 10000 == 0:
                print(f"  Submissions guardadas: {total_written}")
    finally:
        writer.close()
        fh_out.close()

    print(f"Submissions escaneadas: {total_scanned} | guardadas: {total_written} "
          f"| hilos únicos: {len(selected_link_ids)}\n")
    return selected_link_ids


def extract_comments_subset(rc_input, rc_output, selected_link_ids):
    """Guarda en rc_output todos los comentarios de los hilos seleccionados."""
    total_scanned = total_written = 0
    print("Extrayendo comments del subconjunto de 6 subreddits...")

    fh_out, writer = open_zst_writer(rc_output)
    try:
        for obj in stream_zst_file(rc_input):
            total_scanned += 1
            link_id = obj.get("link_id")
            if link_id not in selected_link_ids:
                continue
            write_json_line(writer, obj)
            total_written += 1
            if total_written % 50000 == 0:
                print(f"  Comentarios guardados: {total_written}")
    finally:
        writer.close()
        fh_out.close()

    print(f"Comentarios escaneados: {total_scanned} | guardados: {total_written}\n")


def build_subset():
    """Paso 2 completo: genera RS_subset_6subreddits.zst y RC_subset_6subreddits.zst."""
    selected_link_ids = extract_submissions_subset(RS_INPUT, RS_SUBSET, set(TARGET_SUBREDDITS))
    extract_comments_subset(RC_INPUT, RC_SUBSET, selected_link_ids)
    print(f"Subconjunto generado: {RS_SUBSET.name}, {RC_SUBSET.name}\n")


# ---------------------------------------------------------------------------
# 3) Filtrado + selección final por subreddit -> <Subreddit>_filtrado.json
# ---------------------------------------------------------------------------

def is_valid_submission(obj, subreddit_lower, min_comments, min_selftext_len, max_selftext_len):
    if obj.get("subreddit", "").lower() != subreddit_lower:
        return False
    if not obj.get("is_self", False):
        return False
    title = clean_text(obj.get("title", ""))
    selftext = clean_text(obj.get("selftext", ""))
    if not selftext or selftext in ("[removed]", "[deleted]"):
        return False
    if not is_valid_text_length(selftext, min_selftext_len, max_selftext_len):
        return False
    if contains_bot(title) or contains_bot(selftext):
        return False
    num_comments = obj.get("num_comments", 0) or 0
    if num_comments < min_comments:
        return False
    return True


def is_valid_comment(obj, min_body_len, max_body_len):
    body = clean_text(obj.get("body", ""))
    if not body or body in ("[deleted]", "[removed]"):
        return False
    if contains_bot(body):
        return False
    if not is_valid_text_length(body, min_body_len, max_body_len):
        return False
    return True


def extract_submissions(filepath, subreddit, n_submissions, min_comments,
                         min_selftext_len=20, max_selftext_len=400):
    subreddit_lower = subreddit.lower()
    candidates = []
    print(f"Buscando candidatos en r/{subreddit}...")

    for obj in stream_zst_file(filepath):
        if obj.get("subreddit", "").lower() != subreddit_lower:
            continue
        if not is_valid_submission(obj, subreddit_lower, min_comments,
                                    min_selftext_len, max_selftext_len):
            continue
        candidates.append({
            "id": obj.get("id"),
            "name": f"t3_{obj.get('id')}",
            "subreddit": obj.get("subreddit"),
            "author": obj.get("author"),
            "title": obj.get("title"),
            "selftext": obj.get("selftext"),
            "score": obj.get("score", 0),
            "num_comments": obj.get("num_comments", 0),
            "created_utc": obj.get("created_utc"),
            "created_datetime": created_iso(obj.get("created_utc")),
            "permalink": obj.get("permalink"),
            "url": obj.get("url"),
            "is_self": obj.get("is_self", False),
            "comments": [],
        })

    print(f"  Candidatas válidas: {len(candidates)}")
    selected = select_diverse_top_submissions(candidates, n_submissions)
    print(f"  Seleccionadas finalmente: {len(selected)}\n")
    return selected


def extract_comments_for_submissions(filepath, submissions, num_comments,
                                      min_body_len=20, max_body_len=500):
    if not submissions or num_comments <= 0:
        return
    submission_map = {s["name"]: s for s in submissions}
    candidates_by_submission = defaultdict(list)

    for obj in stream_zst_file(filepath):
        link_id = obj.get("link_id")
        if link_id not in submission_map:
            continue
        if not is_valid_comment(obj, min_body_len, max_body_len):
            continue
        candidates_by_submission[link_id].append({
            "id": obj.get("id"),
            "name": f"t1_{obj.get('id')}",
            "author": obj.get("author"),
            "body": obj.get("body"),
            "score": obj.get("score", 0),
            "created_utc": obj.get("created_utc"),
            "created_datetime": created_iso(obj.get("created_utc")),
            "parent_id": obj.get("parent_id"),
            "link_id": obj.get("link_id"),
            "is_submitter": obj.get("is_submitter", False),
        })

    for submission_name, comments in candidates_by_submission.items():
        submission_map[submission_name]["comments"] = select_diverse_comments(comments, num_comments)


def build_subreddit_json(subreddit_key, subreddit_name):
    """Genera data/<Subreddit>_filtrado.json a partir del subconjunto .zst.

    FIX (corrección, -0,3 puntos: "el corpus tiene menos comentarios de los
    que se pedía y había comentarios de sobra para seleccionar"): respecto a
    la versión original, aquí se piden más hilos candidatos por subreddit
    (buscando min_comments más bajo, así entran más hilos como candidatos) y
    se amplía el rango de longitud aceptado para los comentarios
    (min_body_len/max_body_len), de forma que haya más candidatos válidos
    entre los que elegir los 25 por hilo y así poder llegar a los ~6000
    comentarios recomendados en el enunciado (6 subreddits x 40 hilos x 25
    comentarios). No se ha podido volver a generar los ficheros con esta
    versión corregida en este entorno (no hay acceso a los volcados RS_2025/
    RC_2025.zst de >60GB aquí), así que `data/*_filtrado.json` sigue
    conteniendo la selección original (5350 comentarios); esta función queda
    lista para ejecutarse de nuevo y acercarse al objetivo en cuanto se tenga
    acceso a los ficheros originales.
    """
    submissions = extract_submissions(
        RS_SUBSET, subreddit_name,
        n_submissions=N_SUBMISSIONS_PER_SUBREDDIT,
        min_comments=20,  # antes 25: admite más hilos candidatos
    )
    extract_comments_for_submissions(
        RC_SUBSET, submissions,
        num_comments=N_COMMENTS_PER_SUBMISSION,
        min_body_len=15,   # antes 20: admite más comentarios candidatos
        max_body_len=700,  # antes 500
    )
    result = {
        "subreddit": subreddit_name,
        "extraction_date": datetime.now(UTC).isoformat(),
        "num_submissions": len(submissions),
        "total_comments": sum(len(s["comments"]) for s in submissions),
        "submissions": submissions,
    }
    out_path = DATA_DIR / f"{subreddit_name}_filtrado.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Guardado: {out_path}\n")


def build_all_subreddit_jsons():
    for key, name in TARGET_SUBREDDITS.items():
        build_subreddit_json(key, name)


# ---------------------------------------------------------------------------
# 4) r/OpinionesPolemicas -> OpinionesPolemicas_filtrado.json (apartado 6)
# ---------------------------------------------------------------------------

def extract_opiniones_submissions(filepath, n_submissions, min_comments,
                                   min_selftext_len=80, max_selftext_len=400):
    """Igual que extract_submissions pero sin filtrar por subreddit (el
    volcado ya viene restringido a r/OpinionesPolemicas) y con criterios
    propios para este apartado.

    Estrategia de selección (para cumplir con "no coger solo los primeros
    hilos del fichero"): se recorren TODOS los hilos del volcado, se aplican
    los mismos filtros de calidad que en el resto de la práctica y, de entre
    los candidatos válidos, se seleccionan los `n_submissions` con más
    diversidad temporal (repartiendo la selección en bloques por fecha) y
    mejor puntuación dentro de cada bloque -- igual que `select_diverse_top_submissions`.
    """
    candidates = []
    print("Buscando candidatos en r/OpinionesPolemicas...")
    for obj in stream_zst_file(filepath):
        title = clean_text(obj.get("title", ""))
        selftext = clean_text(obj.get("selftext", ""))
        if not selftext or selftext in ("[removed]", "[deleted]"):
            continue
        if not is_valid_text_length(selftext, min_selftext_len, max_selftext_len):
            continue
        if contains_bot(title) or contains_bot(selftext):
            continue
        num_comments = obj.get("num_comments", 0) or 0
        if num_comments < min_comments:
            continue
        candidates.append({
            "id": obj.get("id"),
            "name": f"t3_{obj.get('id')}",
            "subreddit": obj.get("subreddit", "OpinionesPolemicas"),
            "author": obj.get("author"),
            "title": obj.get("title"),
            "selftext": obj.get("selftext"),
            "score": obj.get("score", 0),
            "num_comments": obj.get("num_comments", 0),
            "created_utc": obj.get("created_utc"),
            "created_datetime": created_iso(obj.get("created_utc")),
            "permalink": obj.get("permalink"),
            "url": obj.get("url"),
            "is_self": obj.get("is_self", False),
            "comments": [],
        })

    print(f"  Candidatas válidas: {len(candidates)}")
    selected = select_diverse_top_submissions(candidates, n_submissions)
    print(f"  Seleccionadas finalmente: {len(selected)}\n")
    return selected


def build_opiniones_json():
    submissions = extract_opiniones_submissions(
        RS_OP_INPUT,
        n_submissions=N_SUBMISSIONS_OPINIONES,
        min_comments=N_COMMENTS_OPINIONES,
    )
    extract_comments_for_submissions(
        RC_OP_INPUT, submissions,
        num_comments=N_COMMENTS_OPINIONES,
        min_body_len=40, max_body_len=1200,
    )
    result = {
        "subreddit": "OpinionesPolemicas",
        "extraction_date": datetime.now(UTC).isoformat(),
        "num_submissions": len(submissions),
        "total_comments": sum(len(s["comments"]) for s in submissions),
        "submissions": submissions,
    }
    out_path = DATA_DIR / "OpinionesPolemicas_filtrado.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Guardado: {out_path}\n")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--download", action="store_true", help="Descarga los .zst / .md originales")
    parser.add_argument("--subset", action="store_true", help="Genera el subconjunto de los 6 subreddits")
    parser.add_argument("--extract", action="store_true", help="Genera <Subreddit>_filtrado.json para los 6 subreddits")
    parser.add_argument("--opiniones", action="store_true", help="Genera OpinionesPolemicas_filtrado.json")
    parser.add_argument("--all", action="store_true", help="Ejecuta todos los pasos anteriores en orden")
    args = parser.parse_args()

    if not any([args.download, args.subset, args.extract, args.opiniones, args.all]):
        parser.print_help()
        print("\nNota: los JSON ya generados (data/*_filtrado.json) se entregan "
              "directamente en este proyecto, así que normalmente NO hace falta "
              "ejecutar este script.")
        return

    if args.download or args.all:
        download_files()
    if args.subset or args.all:
        build_subset()
    if args.extract or args.all:
        build_all_subreddit_jsons()
    if args.opiniones or args.all:
        build_opiniones_json()


if __name__ == "__main__":
    main()
