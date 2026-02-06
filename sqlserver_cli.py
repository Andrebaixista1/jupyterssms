#!/usr/bin/env python3
import curses
import curses.ascii
import curses.textpad
import csv
import json
import os
import subprocess
import sys
import traceback
import time
from datetime import datetime

try:
    import pyodbc
except Exception:
    pyodbc = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "jupyter-ssms")
LOG_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "jupyter-ssms")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LOG_PATH = os.path.join(LOG_DIR, "jupyter_ssms.log")
VERSION = "Io v2.06022026"
FOCUS_ATTR = 0

DEFAULT_CONFIG = {
    "host": "",
    "port": "1433",
    "user": "",
    "database": "master",
    "driver": "ODBC Driver 18 for SQL Server",
    "encrypt": True,
    "trust_server_certificate": True,
    "remember": True,
    "save_password": False,
    "history": [],
}


def log_event(message):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")
    except Exception:
        try:
            with open("/tmp/jupyter_ssms.log", "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {message}\n")
        except Exception:
            pass


def load_config():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = dict(DEFAULT_CONFIG)
        cfg.update(data or {})
        if not isinstance(cfg.get("history"), list):
            cfg["history"] = []
        if not cfg.get("database"):
            cfg["database"] = "master"
        # nunca preenche host/usuario automaticamente
        cfg["host"] = ""
        cfg["user"] = ""
        return cfg
    except Exception:
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log_event(f"Erro salvando config: {e}")


def safe_addstr(win, y, x, text, attr=0):
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass

def safe_curs_set(value):
    try:
        curses.curs_set(value)
    except curses.error:
        pass

def safe_use_default_colors():
    try:
        curses.use_default_colors()
    except curses.error:
        pass

def safe_start_color():
    try:
        curses.start_color()
    except curses.error:
        pass

def safe_raw():
    try:
        curses.raw()
    except curses.error:
        pass

def safe_noraw():
    try:
        curses.noraw()
    except curses.error:
        pass

def safe_keypad(win, enabled=True):
    try:
        win.keypad(enabled)
    except curses.error:
        pass

def split_line_at_cursor(win):
    try:
        maxy, maxx = win.getmaxyx()
        y, x = win.getyx()
    except Exception:
        return
    if y >= maxy - 1:
        return
    remainder_chars = []
    for col in range(x, maxx):
        try:
            ch = win.inch(y, col)
            c = curses.ascii.ascii(ch)
            if c == 0:
                c = curses.ascii.SP
            remainder_chars.append(chr(c))
        except curses.error:
            break
    remainder = "".join(remainder_chars).rstrip()
    try:
        win.move(y, x)
        win.clrtoeol()
        win.move(y + 1, 0)
        win.insertln()
        if remainder:
            win.addstr(y + 1, 0, remainder[:maxx])
        win.move(y + 1, 0)
    except curses.error:
        pass

def insert_newline_at_cursor(box):
    win = box.win
    try:
        maxy, maxx = win.getmaxyx()
        y, x = win.getyx()
    except Exception:
        return
    try:
        text = box.gather()
    except Exception:
        return
    lines = text.splitlines()
    if len(lines) < maxy:
        lines.extend([""] * (maxy - len(lines)))
    if y >= len(lines):
        return
    line = lines[y]
    if x > len(line):
        x = len(line)
    left = line[:x]
    right = line[x:]
    lines[y] = left
    if y + 1 <= len(lines):
        lines.insert(y + 1, right)
    else:
        lines.append(right)
    lines = lines[:maxy]
    win.erase()
    for row, text in enumerate(lines):
        try:
            win.addstr(row, 0, text.rstrip()[: maxx - 1])
        except curses.error:
            pass
    try:
        win.move(min(y + 1, maxy - 1), 0)
    except curses.error:
        pass

def delete_forward_at_cursor(box):
    win = box.win
    try:
        maxy, maxx = win.getmaxyx()
        y, x = win.getyx()
    except Exception:
        return
    try:
        text = box.gather()
    except Exception:
        return
    lines = text.splitlines()
    if len(lines) < maxy:
        lines.extend([""] * (maxy - len(lines)))
    if y >= len(lines):
        return
    line = lines[y]
    if x < len(line):
        lines[y] = line[:x] + line[x + 1 :]
    elif y + 1 < len(lines):
        lines[y] = line + lines[y + 1]
        del lines[y + 1]
    lines = lines[:maxy]
    win.erase()
    for row, text in enumerate(lines):
        try:
            win.addstr(row, 0, text.rstrip()[: maxx - 1])
        except curses.error:
            pass
    try:
        win.move(min(y, maxy - 1), min(x, maxx - 1))
    except curses.error:
        pass

def get_clipboard_text():
    for cmd in (
        ["wl-paste", "-n"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
    ):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return proc.stdout or ""
        except Exception:
            continue
    return ""

def set_clipboard_text(text):
    if text is None:
        return False
    for cmd in (
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    ):
        try:
            subprocess.run(cmd, input=text, text=True, check=True)
            return True
        except Exception:
            continue
    return False


def draw_header(win, title):
    h, w = win.getmaxyx()
    safe_addstr(win, 0, 2, title[: w - 4], curses.A_BOLD)
    safe_addstr(win, 1, 0, "-" * (w - 1))


def prompt_input(stdscr, prompt, initial="", mask=False):
    h, w = stdscr.getmaxyx()
    win_h = 3
    win_w = max(40, min(w - 4, 80))
    win_y = h // 2 - 1
    win_x = w // 2 - win_w // 2
    win = curses.newwin(win_h, win_w, win_y, win_x)
    win.border()
    safe_addstr(win, 0, 2, " Entrada ")
    safe_addstr(win, 1, 2, prompt[: win_w - 4])
    safe_curs_set(1)
    buf = list(initial)
    while True:
        display = "".join("*" if mask else ch for ch in buf)
        safe_addstr(win, 2, 2, " " * (win_w - 4))
        safe_addstr(win, 2, 2, display[: win_w - 4])
        win.refresh()
        ch = win.getch()
        if ch in (curses.KEY_ENTER, 10, 13):
            safe_curs_set(0)
            return "".join(buf)
        if ch in (27,):
            safe_curs_set(0)
            return None
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
        elif 32 <= ch <= 126:
            buf.append(chr(ch))


def build_conn_str(cfg, password):
    host = cfg.get("host", "").strip()
    port = cfg.get("port", "1433").strip() or "1433"
    user = cfg.get("user", "").strip()
    db = cfg.get("database", "").strip()
    driver = cfg.get("driver", "ODBC Driver 18 for SQL Server").strip()
    server = f"{host},{port}" if port else host
    encrypt = bool(cfg.get("encrypt", True))
    trust = bool(cfg.get("trust_server_certificate", True))
    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"UID={user}",
        f"PWD={password}",
        f"Encrypt={'yes' if encrypt else 'no'}",
        f"TrustServerCertificate={'yes' if trust else 'no'}",
    ]
    if db:
        parts.append(f"DATABASE={db}")
    return ";".join(parts)


def connect_db(cfg, password):
    if pyodbc is None:
        return None, "pyodbc nao instalado"
    try:
        conn_str = build_conn_str(cfg, password)
        conn = pyodbc.connect(conn_str, timeout=5, autocommit=True)
        return conn, None
    except Exception as e:
        return None, str(e)


def fetch_databases(conn):
    sql = "SELECT name FROM sys.databases ORDER BY name"
    cur = conn.cursor()
    cur.execute(sql)
    return [row[0] for row in cur.fetchall()]


def fetch_tables(conn):
    sql = """
    SELECT TABLE_SCHEMA, TABLE_NAME
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE='BASE TABLE'
    ORDER BY TABLE_SCHEMA, TABLE_NAME
    """
    cur = conn.cursor()
    cur.execute(sql)
    return [f"{r[0]}.{r[1]}" for r in cur.fetchall()]


def fetch_columns(conn, schema, table):
    sql = """
    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA=? AND TABLE_NAME=?
    ORDER BY ORDINAL_POSITION
    """
    cur = conn.cursor()
    cur.execute(sql, (schema, table))
    return cur.fetchall()


def run_query(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    if cur.description is None:
        conn.commit()
        return None, None, cur.rowcount
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return cols, rows, None


def format_table(cols, rows, max_w, max_h):
    if not cols:
        return []
    max_cell = 30
    widths = []
    for i, c in enumerate(cols):
        col_vals = [str(c)]
        for r in rows[: max_h - 4]:
            col_vals.append(str(r[i]))
        width = min(max(len(v) for v in col_vals), max_cell)
        widths.append(width)
    total = sum(widths) + 3 * (len(widths) - 1)
    show_cols = len(cols)
    while total > max_w and show_cols > 1:
        show_cols -= 1
        total = sum(widths[:show_cols]) + 3 * (show_cols - 1)
    cols = cols[:show_cols]
    widths = widths[:show_cols]
    lines = []
    header = " | ".join(str(c)[:w].ljust(w) for c, w in zip(cols, widths))
    sep = "-+-".join("-" * w for w in widths)
    lines.append(header)
    lines.append(sep)
    for r in rows[: max_h - 4]:
        line = " | ".join(str(v)[:w].ljust(w) for v, w in zip(r[:show_cols], widths))
        lines.append(line)
    return lines


def format_table_full(cols, rows, max_cell=30):
    if not cols:
        return [], 0
    widths = []
    for i, c in enumerate(cols):
        col_vals = [str(c)]
        for r in rows:
            col_vals.append(str(r[i]))
        width = min(max(len(v) for v in col_vals), max_cell)
        widths.append(width)
    header = " | ".join(str(c)[:w].ljust(w) for c, w in zip(cols, widths))
    sep = "-+-".join("-" * w for w in widths)
    lines = [header, sep]
    for r in rows:
        line = " | ".join(str(v)[:w].ljust(w) for v, w in zip(r, widths))
        lines.append(line)
    total_width = len(header)
    return lines, total_width


def format_table_view(cols, rows, start_row, max_rows, max_cell=60, sample=200):
    if not cols:
        return [], 0
    sample_rows = rows[: min(len(rows), sample)]
    widths = []
    for i, c in enumerate(cols):
        col_vals = [str(c)]
        for r in sample_rows:
            col_vals.append(str(r[i]))
        width = min(max(len(v) for v in col_vals), max_cell)
        widths.append(width)
    header = " | ".join(str(c)[:w].ljust(w) for c, w in zip(cols, widths))
    sep = "-+-".join("-" * w for w in widths)
    lines = [header, sep]
    for r in rows[start_row : start_row + max_rows]:
        line = " | ".join(str(v)[:w].ljust(w) for v, w in zip(r, widths))
        lines.append(line)
    total_width = len(header)
    return lines, total_width


def normalize_editor_text(text, reference=None):
    def clean_line(line):
        # Remove control characters (e.g., NUL) that can appear from curses buffers
        return "".join(ch for ch in line if ch == "\t" or ch >= " ")

    lines = [clean_line(l).rstrip() for l in text.splitlines()]
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return "\n".join(lines)

    def norm_line(line):
        return " ".join(line.split())

    norms = [norm_line(l) for l in non_empty]
    if reference:
        ref_clean = clean_line(reference)
        ref_norm = norm_line(ref_clean)
        if all(n == ref_norm for n in norms):
            # If the original text was a single line, collapse duplicated lines
            if "\n" not in ref_clean:
                return ref_clean.strip()
            return ref_clean.strip("\n")
    return "\n".join(lines)


def default_csv_path():
    base = os.path.join(os.path.expanduser("~"), "Downloads")
    if not os.path.isdir(base):
        base = os.path.expanduser("~")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(base, f"jupyter-ssms_results_{ts}.csv")

def choose_save_path(default_path):
    # Prefer GUI dialog if available
    for tool in ("zenity", "kdialog"):
        if subprocess.run(["bash", "-lc", f"command -v {tool}"], capture_output=True).returncode == 0:
            if tool == "zenity":
                args = [
                    "zenity",
                    "--file-selection",
                    "--save",
                    "--confirm-overwrite",
                    "--title=Salvar CSV",
                    f"--filename={default_path}",
                ]
            else:
                args = [
                    "kdialog",
                    "--getsavefilename",
                    default_path,
                    "CSV (*.csv)",
                    "--title",
                    "Salvar CSV",
                ]
            proc = subprocess.run(args, capture_output=True, text=True)
            if proc.returncode == 0:
                path = (proc.stdout or "").strip()
                return path if path else None
            return None
    return None


def export_csv(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(cols)
        for r in rows:
            writer.writerow(list(r))


def screen_message(stdscr, title, message, pause=True):
    stdscr.clear()
    draw_header(stdscr, title)
    h, w = stdscr.getmaxyx()
    lines = message.splitlines()
    for i, line in enumerate(lines[: h - 3]):
        safe_addstr(stdscr, 2 + i, 2, line[: w - 4])
    if pause:
        safe_addstr(stdscr, h - 2, 2, "Pressione qualquer tecla...")
        stdscr.getch()

def screen_help(stdscr):
    text = "\n".join(
        [
            f"Jupyter-SSMS {VERSION}",
            f"OS: {get_os_pretty_name()}",
            "",
            "Conexao:",
            "- Digite direto no campo selecionado (nao precisa Enter).",
            "- Setas/TAB: navegar campos.",
            "- ESPACO: alternar ON/OFF (Encrypt, TrustCert, Lembrar, SalvarSenha).",
            "- F2: conectar.",
            "- Historico no topo (TAB para alternar foco).",
            "",
            "Workspace (layout SSMS):",
            "- Esquerda: arvore (Server > Databases > Tables).",
            "- Direita (topo): editor SQL.",
            "- Direita (baixo): resultados.",
            "- F9: modo avancado.",
            "- TAB: alterna foco (arvore/editor/resultados).",
            "- Shift+TAB: foco anterior.",
            "- Ctrl+N: nova query (aba).",
            "- Ctrl+TAB: proxima query.",
            "- Ctrl+Shift+TAB: query anterior.",
            "- Ctrl+X: fechar query atual.",
            "- F8/F7: proxima/anterior (fallback).",
            "- Ctrl+C: copiar texto do editor.",
            "- Ctrl+V: colar no editor.",
            "- Home/End: inicio/fim da linha no editor.",
            "- F5: executar query.",
            "- F6: exportar resultados para CSV (separador ';').",
            "- Ao salvar: abre o gerenciador de arquivos (se disponivel).",
            "- R: atualizar listas.",
            "- Mouse: clique para mudar foco.",
            "",
            "Acoes:",
            "- Enter em DB: usa o database.",
            "- Enter em tabela: gera SELECT TOP 100.",
            "- S/I/U/D em tabela: gera template CRUD.",
            "",
            "Atalhos gerais:",
            "- F1: ajuda.",
            "- ESC: voltar/sair.",
            "",
            "Resultados:",
            "- Setas: navega linhas/colunas (com foco em Results).",
        ]
    )
    screen_message(stdscr, "Ajuda", text)

def get_os_pretty_name():
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("PRETTY_NAME="):
                    val = line.split("=", 1)[1].strip().strip('"')
                    return val
    except Exception:
        pass
    return "Linux"


def screen_splash(stdscr):
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    art = r"""
     ██╗██╗   ██╗██████╗ ██╗   ██╗████████╗███████╗██████╗               ███████╗███████╗███╗   ███╗███████╗
     ██║██║   ██║██╔══██╗╚██╗ ██╔╝╚══██╔══╝██╔════╝██╔══██╗              ██╔════╝██╔════╝████╗ ████║██╔════╝
     ██║██║   ██║██████╔╝ ╚████╔╝    ██║   █████╗  ██████╔╝    █████╗    ███████╗███████╗██╔████╔██║███████╗
██   ██║██║   ██║██╔═══╝   ╚██╔╝     ██║   ██╔══╝  ██╔══██╗    ╚════╝    ╚════██║╚════██║██║╚██╔╝██║╚════██║
╚█████╔╝╚██████╔╝██║        ██║      ██║   ███████╗██║  ██║              ███████║███████║██║ ╚═╝ ██║███████║
 ╚════╝  ╚═════╝ ╚═╝        ╚═╝      ╚═╝   ╚══════╝╚═╝  ╚═╝              ╚══════╝╚══════╝╚═╝     ╚═╝╚══════╝
""".strip("\n").splitlines()

    def fit_ascii(lines, max_w, max_h):
        if max_w <= 0 or max_h <= 0:
            return []
        # downsample height if needed
        if len(lines) > max_h:
            step = len(lines) / max_h
            lines = [lines[int(i * step)] for i in range(max_h)]
        # downsample width if needed
        out = []
        for line in lines:
            if len(line) <= max_w:
                out.append(line)
                continue
            step = len(line) / max_w
            out.append("".join(line[int(i * step)] for i in range(max_w)))
        return out
    info = [
        f"Jupyter-SSMS {VERSION}",
        "Criado e desenvolvido por André Felipe Pinto © 2026",
        f"OS: {get_os_pretty_name()}",
        f"Python: {sys.version.split()[0]}",
        "Pressione qualquer tecla para continuar...",
    ]
    max_art_h = max(4, h - (len(info) + 6))
    max_art_w = max(20, w - 4)
    art = fit_ascii(art, max_art_w, max_art_h)
    start_y = max(1, (h // 2) - (len(art) + len(info)) // 2 - 1)
    for i, line in enumerate(art):
        x = max(2, (w - len(line)) // 2)
        safe_addstr(stdscr, start_y + i, x, line[: w - 4], curses.A_BOLD)
    info_y = start_y + len(art) + 1
    for i, line in enumerate(info):
        x = max(2, (w - len(line)) // 2)
        safe_addstr(stdscr, info_y + i, x, line[: w - 4])
    stdscr.refresh()

    stdscr.nodelay(True)
    for _ in range(30):  # ~1.5s
        ch = stdscr.getch()
        if ch != -1:
            break
        time.sleep(0.05)
    stdscr.nodelay(False)

def conn_key(entry):
    return (
        entry.get("host", "").strip().lower(),
        entry.get("port", "").strip(),
        entry.get("user", "").strip().lower(),
        entry.get("database", "").strip().lower(),
        entry.get("driver", "").strip(),
        bool(entry.get("encrypt", True)),
        bool(entry.get("trust_server_certificate", True)),
    )


def upsert_history(cfg, entry, max_items=20):
    history = list(cfg.get("history", []))
    key = conn_key(entry)
    new_history = []
    for item in history:
        if conn_key(item) == key:
            continue
        new_history.append(item)
    new_history.insert(0, entry)
    cfg["history"] = new_history[:max_items]
    save_config(cfg)


def format_history_entry(entry):
    name = entry.get("name", "").strip()
    host = entry.get("host", "")
    port = entry.get("port", "")
    user = entry.get("user", "")
    db = entry.get("database", "") or "-"
    base = f"{user}@{host}:{port}/{db}"
    label = f"{name} - {base}" if name else base
    if entry.get("password"):
        label += " [senha]"
    return label


def screen_history(stdscr, cfg, current, password):
    history = list(cfg.get("history", []))
    if not history:
        screen_message(stdscr, "Historico", "Sem conexoes salvas.")
        return cfg, current, password
    idx = 0
    while True:
        stdscr.clear()
        draw_header(stdscr, "Historico de conexoes")
        h, w = stdscr.getmaxyx()
        for i, item in enumerate(history[: h - 6]):
            y = 3 + i
            label = format_history_entry(item)
            attr = curses.A_REVERSE if i == idx else 0
            safe_addstr(stdscr, y, 2, label[: w - 4], attr)
        safe_addstr(stdscr, h - 2, 2, "Enter = carregar | DEL = remover | ESC = voltar")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (27,):
            return cfg, current, password
        if ch in (curses.KEY_UP,):
            idx = (idx - 1) % len(history)
        elif ch in (curses.KEY_DOWN,):
            idx = (idx + 1) % len(history)
        elif ch in (curses.KEY_DC, 330):
            item = history.pop(idx)
            cfg["history"] = history
            save_config(cfg)
            if not history:
                return cfg, current, password
            idx = min(idx, len(history) - 1)
        elif ch in (curses.KEY_ENTER, 10, 13):
            item = history[idx]
            for key in ("host", "port", "user", "database", "driver"):
                if key in item:
                    current[key] = item[key]
            if "name" in item:
                current["name"] = item.get("name", "")
            if "encrypt" in item:
                cfg["encrypt"] = bool(item.get("encrypt"))
            if "trust_server_certificate" in item:
                cfg["trust_server_certificate"] = bool(item.get("trust_server_certificate"))
            save_config(cfg)
            if item.get("password"):
                password = item.get("password", "")
            return cfg, current, password


def screen_connect(stdscr, cfg, current, password):
    fields = [
        ("Nome", "name", "text"),
        ("Host", "host", "text"),
        ("Port", "port", "text"),
        ("User", "user", "text"),
        ("Password", "__password", "password"),
        ("Database", "database", "text"),
        ("Driver", "driver", "text"),
        ("Encrypt", "encrypt", "bool"),
        ("TrustCert", "trust_server_certificate", "bool"),
        ("Lembrar", "remember", "bool"),
        ("SalvarSenha", "save_password", "bool"),
    ]
    area = "history" if cfg.get("history") else "fields"
    hist_idx = 0
    idx = 0
    while True:
        stdscr.clear()
        draw_header(stdscr, f"Jupyter-SSMS {VERSION} - Conexao")
        h, w = stdscr.getmaxyx()
        history = list(cfg.get("history", []))
        hist_y = 2
        hist_h = max(2, min(len(history) + 1 if history else 2, max(3, h // 4)))
        fields_header_y = hist_y + hist_h + 2  # linha em branco entre historico e campos
        fields_start_y = fields_header_y + 1
        field_x = 4

        # Historico no topo (sempre visivel)
        safe_addstr(stdscr, hist_y, 2, "Historico de conexoes:")
        if history:
            if hist_idx >= len(history):
                hist_idx = max(0, len(history) - 1)
            max_hist_lines = hist_h - 1
            start = 0
            if hist_idx >= max_hist_lines:
                start = hist_idx - max_hist_lines + 1
            for i, item in enumerate(history[start : start + max_hist_lines]):
                idx_abs = start + i
                label = format_history_entry(item)
                attr = curses.A_REVERSE if (area == "history" and idx_abs == hist_idx) else 0
                safe_addstr(stdscr, hist_y + 1 + i, 4, label[: w - 6], attr)
        else:
            if area == "history":
                area = "fields"
            safe_addstr(stdscr, hist_y + 1, 4, "Sem conexoes salvas.")

        safe_addstr(stdscr, fields_header_y, 2, "Nova Conexao SSMS")
        for i, (label, key, ftype) in enumerate(fields):
            y = fields_start_y + i
            if ftype == "password":
                val = "*" * len(password) if password else ""
            elif ftype == "bool":
                val = "ON" if cfg.get(key, False) else "OFF"
            else:
                val = str(current.get(key, ""))
            line = f"{label}: {val}"
            attr = curses.A_REVERSE if (area == "fields" and i == idx) else 0
            safe_addstr(stdscr, y, field_x, line[: w - 4], attr)
        safe_addstr(stdscr, h - 4, 2, "Digite direto no campo | TAB = alternar Historico/Campos")
        safe_addstr(stdscr, h - 3, 2, "F2 = Conectar | F1 = Ajuda")
        safe_addstr(stdscr, h - 2, 2, "ESPACO = toggle | DEL = remover historico | ESC = Sair")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (27,):
            return None, None, None
        if ch in (9,):  # TAB
            area = "history" if area == "fields" else "fields"
            continue
        if area == "history":
            if ch in (curses.KEY_UP,):
                if history:
                    hist_idx = (hist_idx - 1) % len(history)
                continue
            if ch in (curses.KEY_DOWN,):
                if history:
                    hist_idx = (hist_idx + 1) % len(history)
                continue
            if ch in (curses.KEY_DC, 330) and history:
                history.pop(hist_idx)
                cfg["history"] = history
                save_config(cfg)
                if hist_idx >= len(history):
                    hist_idx = max(0, len(history) - 1)
                continue
            if ch in (curses.KEY_ENTER, 10, 13) and history:
                item = history[hist_idx]
                for key in ("host", "port", "user", "database", "driver", "name"):
                    if key in item:
                        current[key] = item[key]
                if "encrypt" in item:
                    cfg["encrypt"] = bool(item.get("encrypt"))
                if "trust_server_certificate" in item:
                    cfg["trust_server_certificate"] = bool(item.get("trust_server_certificate"))
                save_config(cfg)
                if item.get("password"):
                    password = item.get("password", "")
                area = "fields"
                continue
        if ch in (curses.KEY_UP,):
            idx = (idx - 1) % len(fields)
            continue
        if ch in (curses.KEY_DOWN,):
            idx = (idx + 1) % len(fields)
            continue
        label, key, ftype = fields[idx]
        if ch == curses.KEY_F1:
            screen_help(stdscr)
            continue
        if ch == curses.KEY_F2:
            if not current.get("host") or not current.get("user"):
                screen_message(stdscr, "Erro", "Host e User sao obrigatorios.")
                continue
            if cfg.get("remember") and not current.get("name"):
                suggested = f"{current.get('user','')}@{current.get('host','')}"
                name = prompt_input(stdscr, "Nome da conexao:", suggested)
                if not name:
                    screen_message(stdscr, "Erro", "Nome da conexao e obrigatorio para salvar.")
                    continue
                current["name"] = name
            return cfg, current, password
        if ftype == "bool":
            if ch in (ord(" "), curses.KEY_ENTER, 10, 13):
                cfg[key] = not bool(cfg.get(key, False))
                if key == "save_password" and not cfg.get("save_password"):
                    password = ""
                save_config(cfg)
            continue
        if ch in (curses.KEY_ENTER, 10, 13):
            idx = (idx + 1) % len(fields)
            continue
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if ftype == "password":
                password = password[:-1]
            else:
                val = str(current.get(key, ""))
                current[key] = val[:-1]
            continue
        if 32 <= ch <= 126:
            if ftype == "password":
                password += chr(ch)
            else:
                val = str(current.get(key, ""))
                current[key] = val + chr(ch)
            continue


def panel_window(stdscr, y, x, h, w, title, focused=False):
    win = curses.newwin(h, w, y, x)
    win.clear()
    safe_keypad(win, True)
    if focused and FOCUS_ATTR:
        win.attron(FOCUS_ATTR)
        win.border()
        win.attroff(FOCUS_ATTR)
        safe_addstr(win, 0, 2, f" {title} ", FOCUS_ATTR)
    else:
        win.border()
        safe_addstr(win, 0, 2, f" {title} ")
    return win


def panel_message(stdscr, y, x, h, w, title, message):
    win = panel_window(stdscr, y, x, h, w, title)
    lines = message.splitlines() if message else []
    max_lines = h - 3
    for i, line in enumerate(lines[:max_lines]):
        safe_addstr(win, 1 + i, 2, line[: w - 4])
    safe_addstr(win, h - 2, 2, "Pressione qualquer tecla...")
    win.refresh()
    win.getch()


def panel_show_result(stdscr, y, x, h, w, title, cols, rows, rowcount):
    win = panel_window(stdscr, y, x, h, w, title)
    if cols:
        lines = format_table(cols, rows, w - 4, h - 4)
        for i, line in enumerate(lines[: h - 3]):
            safe_addstr(win, 1 + i, 2, line[: w - 4])
        safe_addstr(win, h - 2, 2, f"Linhas exibidas: {len(rows)}")
    else:
        safe_addstr(win, 1, 2, f"OK. Linhas afetadas: {rowcount}")
        safe_addstr(win, h - 2, 2, "Pressione qualquer tecla...")
    win.refresh()
    win.getch()


def panel_query_editor(stdscr, conn, y, x, h, w, initial_sql=""):
    win = panel_window(stdscr, y, x, h, w, "Query")
    safe_addstr(win, 1, 2, "F2 executar | F1 ajuda | ESC voltar")
    edit_h = max(3, h - 4)
    edit_w = max(10, w - 4)
    edit_y = y + 2
    edit_x = x + 2
    txt_win = curses.newwin(edit_h, edit_w, edit_y, edit_x)
    safe_keypad(txt_win, True)
    txt_win.erase()
    txt_win.refresh()

    actions = {
        curses.KEY_F2: "execute",
        27: "cancel",
    }
    safe_curs_set(1)
    content, action = edit_text_multiline(
        stdscr,
        txt_win,
        initial_sql,
        action_keys=actions,
        help_callback=lambda: screen_help(stdscr),
    )
    safe_curs_set(0)
    if action == "cancel":
        return initial_sql
    sql = content.strip()
    if not sql:
        return initial_sql
    try:
        cols, rows, rowcount = run_query(conn, sql)
        panel_show_result(stdscr, y, x, h, w, "Resultado", cols, rows, rowcount)
    except Exception as e:
        panel_message(stdscr, y, x, h, w, "Erro", str(e))
    return sql


def build_tree_items(dbs, expanded_dbs, tables_cache, expanded_tables, columns_cache):
    items = []
    items.append({"type": "root", "label": "SERVER", "depth": 0})
    for db in dbs:
        items.append(
            {
                "type": "db",
                "label": db,
                "depth": 1,
                "expanded": db in expanded_dbs,
                "db": db,
            }
        )
        if db in expanded_dbs:
            tables = tables_cache.get(db, [])
            for t in tables:
                items.append(
                    {
                        "type": "table",
                        "label": t,
                        "depth": 2,
                        "expanded": (db, t) in expanded_tables,
                        "db": db,
                        "table": t,
                    }
                )
                if (db, t) in expanded_tables:
                    cols = columns_cache.get((db, t), [])
                    for c in cols:
                        items.append(
                            {
                                "type": "column",
                                "label": c,
                                "depth": 3,
                                "db": db,
                                "table": t,
                            }
                        )
    return items


def ensure_db_context(conn, current_db, target_db):
    if not target_db or target_db == current_db:
        return current_db
    try:
        conn.execute(f"USE [{target_db}]")
        return target_db
    except Exception:
        return current_db


def fetch_tables_for_db(conn, current_db, db):
    prev = current_db
    if db != current_db:
        conn.execute(f"USE [{db}]")
    tables = fetch_tables(conn)
    if prev != db:
        conn.execute(f"USE [{prev}]")
    return tables


def fetch_columns_for_table(conn, current_db, db, schema, table):
    prev = current_db
    if db != current_db:
        conn.execute(f"USE [{db}]")
    cols = fetch_columns(conn, schema, table)
    if prev != db:
        conn.execute(f"USE [{prev}]")
    return cols

def build_table_ref(schema, table, db=None, include_db=False):
    if include_db and db:
        return f"[{db}].[{schema}].[{table}]"
    if schema.lower() == "dbo":
        return f"[{table}]"
    return f"[{schema}].[{table}]"

def split_table_name(name):
    if "." in name:
        return name.split(".", 1)
    return "dbo", name

def build_insert_sql(schema, table, columns):
    cols = ", ".join(f"[{c}]" for c in columns)
    params = ", ".join(["?"] * len(columns))
    return f"INSERT INTO {build_table_ref(schema, table)} ({cols}) VALUES ({params})"

def edit_text_multiline(stdscr, win, initial_text, action_keys=None, help_callback=None):
    maxy, maxx = win.getmaxyx()
    lines = initial_text.splitlines() or [""]
    cy = 0
    cx = 0
    scroll_y = 0
    scroll_x = 0

    def ensure_cursor_visible():
        nonlocal scroll_y, scroll_x
        if cy < scroll_y:
            scroll_y = cy
        if cy >= scroll_y + maxy:
            scroll_y = cy - maxy + 1
        if cx < scroll_x:
            scroll_x = cx
        if cx >= scroll_x + maxx:
            scroll_x = cx - maxx + 1

    def render():
        win.erase()
        for i in range(maxy):
            row = scroll_y + i
            if row >= len(lines):
                break
            line = lines[row]
            view = line[scroll_x : scroll_x + maxx]
            try:
                win.addstr(i, 0, view)
            except curses.error:
                pass
        screen_y = max(0, min(cy - scroll_y, maxy - 1))
        screen_x = max(0, min(cx - scroll_x, maxx - 1))
        try:
            win.move(screen_y, screen_x)
        except curses.error:
            pass
        win.refresh()

    def insert_char(ch):
        nonlocal cx
        line = lines[cy]
        lines[cy] = line[:cx] + ch + line[cx:]
        cx += 1

    def insert_newline():
        nonlocal cy, cx
        line = lines[cy]
        left = line[:cx]
        right = line[cx:]
        lines[cy] = left
        lines.insert(cy + 1, right)
        cy += 1
        cx = 0

    def backspace():
        nonlocal cy, cx
        if cx > 0:
            line = lines[cy]
            lines[cy] = line[:cx - 1] + line[cx:]
            cx -= 1
        elif cy > 0:
            prev = lines[cy - 1]
            line = lines[cy]
            cx = len(prev)
            lines[cy - 1] = prev + line
            del lines[cy]
            cy -= 1

    def delete_forward():
        nonlocal cy, cx
        line = lines[cy]
        if cx < len(line):
            lines[cy] = line[:cx] + line[cx + 1 :]
        elif cy < len(lines) - 1:
            lines[cy] = line + lines[cy + 1]
            del lines[cy + 1]

    def paste_text(text):
        nonlocal cy, cx
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        for ch in text:
            if ch == "\n":
                insert_newline()
            else:
                insert_char(ch)

    while True:
        ensure_cursor_visible()
        render()
        ch = win.getch()

        if action_keys and ch in action_keys:
            return "\n".join(lines), action_keys[ch]

        if ch == curses.KEY_F1 and help_callback:
            help_callback()
            continue

        if ch in (curses.KEY_UP,):
            if cy > 0:
                cy -= 1
                cx = min(cx, len(lines[cy]))
        elif ch in (curses.KEY_DOWN,):
            if cy < len(lines) - 1:
                cy += 1
                cx = min(cx, len(lines[cy]))
        elif ch in (curses.KEY_LEFT,):
            if cx > 0:
                cx -= 1
            elif cy > 0:
                cy -= 1
                cx = len(lines[cy])
        elif ch in (curses.KEY_RIGHT,):
            if cx < len(lines[cy]):
                cx += 1
            elif cy < len(lines) - 1:
                cy += 1
                cx = 0
        elif ch in (curses.KEY_HOME, 262):
            cx = 0
        elif ch in (curses.KEY_END, 360):
            cx = len(lines[cy])
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            backspace()
        elif ch == curses.KEY_DC:
            delete_forward()
        elif ch in (curses.KEY_ENTER, 10, 13):
            insert_newline()
        elif ch == 3:  # Ctrl+C
            set_clipboard_text("\n".join(lines))
        elif ch == 22:  # Ctrl+V
            paste_text(get_clipboard_text())
        elif 32 <= ch <= 126:
            insert_char(chr(ch))
        elif 128 <= ch <= 255:
            try:
                insert_char(chr(ch))
            except Exception:
                pass


def editor_edit(stdscr, y, x, h, w, initial_sql):
    win = panel_window(stdscr, y, x, h, w, "SQLQuery_1")
    safe_addstr(win, 1, 2, "F5 executar | F1 ajuda | ESC voltar")
    edit_h = max(3, h - 4)
    edit_w = max(10, w - 4)
    txt_win = curses.newwin(edit_h, edit_w, y + 2, x + 2)
    safe_keypad(txt_win, True)
    txt_win.erase()
    txt_win.refresh()

    actions = {
        curses.KEY_F5: "execute",
        curses.KEY_F2: "execute",
        9: "tab_next",
        curses.KEY_BTAB: "tab_prev",
        353: "tab_prev",
        curses.ascii.SO: "new_tab",   # Ctrl+N
        curses.ascii.CAN: "close_tab",# Ctrl+X
        curses.KEY_CTAB: "switch_tab_next",
        341: "switch_tab_next",
        curses.KEY_CATAB: "switch_tab_prev",
        342: "switch_tab_prev",
        curses.KEY_F8: "switch_tab_next",
        curses.KEY_F7: "switch_tab_prev",
        27: "cancel",
    }

    safe_curs_set(1)
    content, action = edit_text_multiline(
        stdscr,
        txt_win,
        initial_sql,
        action_keys=actions,
        help_callback=lambda: screen_help(stdscr),
    )
    safe_curs_set(0)
    if action == "cancel":
        return initial_sql, None
    sql = content.strip()
    sql = normalize_editor_text(sql, initial_sql)
    if not sql:
        return initial_sql, action
    return sql, action or "edited"


def screen_workspace(stdscr, conn, cfg, current):
    focus = "tree"
    tree_idx = 0
    dbs = []
    expanded_dbs = set()
    tables_cache = {}
    expanded_tables = set()
    columns_cache = {}
    tabs = []
    tab_index = 0
    tab_seq = 1
    enter_edit_on_focus = False
    def new_tab(initial_text=""):
        nonlocal tab_seq, tab_index
        title = f"SQLQuery_{tab_seq}"
        tab_seq += 1
        tabs.append(
            {
                "title": title,
                "text": initial_text,
                "result": {
                    "scroll": 0,
                    "scroll_x": 0,
                    "row_count": 0,
                    "col_count": 0,
                    "title": "Results",
                    "cols": None,
                    "rows": None,
                    "msg": "",
                    "error": "",
                },
            }
        )
        tab_index = len(tabs) - 1

    def current_tab():
        return tabs[tab_index]

    def execute_and_set(sql):
        nonlocal focus
        res = current_tab()["result"]
        try:
            cols, rows, rowcount = run_query(conn, sql)
            if cols:
                res["cols"] = cols
                res["rows"] = rows
                res["row_count"] = len(rows)
                res["col_count"] = len(cols)
                res["title"] = f"Results ({res['row_count']} rows, {res['col_count']} cols)"
                res["msg"] = ""
                res["error"] = ""
            else:
                res["cols"] = None
                res["rows"] = None
                res["row_count"] = rowcount if rowcount is not None else 0
                res["col_count"] = 0
                res["title"] = "Results"
                res["msg"] = f"OK. Linhas afetadas: {rowcount}"
                res["error"] = ""
            res["scroll"] = 0
            res["scroll_x"] = 0
            focus = "results"
        except Exception as e:
            res["cols"] = None
            res["rows"] = None
            res["title"] = "Erro"
            res["row_count"] = 0
            res["col_count"] = 0
            res["msg"] = ""
            res["error"] = str(e)
            res["scroll"] = 0
            res["scroll_x"] = 0
            focus = "results"

    new_tab("")

    try:
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        except Exception:
            pass
        while True:
            tab = current_tab()
            tab["text"] = normalize_editor_text(tab["text"])
            res = tab["result"]
            if not dbs:
                try:
                    dbs = fetch_databases(conn)
                except Exception as e:
                    screen_message(stdscr, "Erro", str(e))
                    return "disconnect"

            stdscr.clear()
            draw_header(stdscr, f"Jupyter-SSMS {VERSION}")
            h, w = stdscr.getmaxyx()
            if h < 20 or w < 80:
                screen_message(stdscr, "Erro", "Terminal muito pequeno. Use ao menos 80x20.")
                return "disconnect"
            top = 2
            toolbar = (
                f"Database: {current.get('database') or 'master'} | "
                f"Server: {current.get('host') or '-'}:{current.get('port') or '1433'} | "
                f"User: {current.get('user') or '-'} | F5 Executar | F9 Avancado | TAB Foco | F1 Ajuda"
            )
            safe_addstr(stdscr, top, 2, toolbar[: w - 4])

            left_w = max(26, min(40, w // 3))
            content_top = top + 1
            content_bottom = h - 2
            content_h = max(6, content_bottom - content_top)

            right_x = left_w + 1
            right_w = max(10, w - right_x - 1)
            editor_h = max(6, content_h // 2)
            result_h = max(4, content_h - editor_h - 1)

            if focus == "editor" and enter_edit_on_focus:
                new_text, action = editor_edit(stdscr, content_top, right_x, editor_h, right_w, tab["text"])
                tab["text"] = new_text
                enter_edit_on_focus = False
                if action == "execute":
                    execute_and_set(tab["text"])
                elif action == "tab_next":
                    focus = "results"
                elif action == "tab_prev":
                    focus = "tree"
                elif action == "new_tab":
                    new_tab("")
                    focus = "editor"
                    enter_edit_on_focus = True
                elif action == "switch_tab_next":
                    tab_index = (tab_index + 1) % len(tabs)
                    focus = "editor"
                    enter_edit_on_focus = True
                elif action == "switch_tab_prev":
                    tab_index = (tab_index - 1) % len(tabs)
                    focus = "editor"
                    enter_edit_on_focus = True
                continue

            # left separator
            for y in range(content_top, content_top + content_h):
                safe_addstr(stdscr, y, left_w, "|")

            # Tree panel (left)
            tree_win = panel_window(stdscr, content_top, 1, content_h, left_w, "Connections", focused=(focus == "tree"))
            tree_items = build_tree_items(dbs, expanded_dbs, tables_cache, expanded_tables, columns_cache)
            if tree_idx >= len(tree_items):
                tree_idx = max(0, len(tree_items) - 1)
            max_tree_lines = content_h - 2
            start = 0
            if tree_idx >= max_tree_lines:
                start = tree_idx - max_tree_lines + 1
            for i, item in enumerate(tree_items[start : start + max_tree_lines]):
                idx = start + i
                depth = item.get("depth", 0)
                prefix = "   "
                if item["type"] in ("db", "table"):
                    prefix = "[-]" if item.get("expanded") else "[+]"
                elif item["type"] == "column":
                    prefix = " - "
                label = f"{'  ' * depth}{prefix} {item['label']}"
                attr = curses.A_REVERSE if (focus == "tree" and idx == tree_idx) else 0
                safe_addstr(tree_win, 1 + i, 2, label[: left_w - 4], attr)

            # Editor panel (right top)
            editor_y = content_top
            editor_x = right_x
            editor_title = f"{tab['title']} ({tab_index + 1}/{len(tabs)})"
            editor_win = panel_window(stdscr, editor_y, editor_x, editor_h, right_w, editor_title, focused=(focus == "editor"))
            editor_lines = tab["text"].splitlines() or [""]
            max_editor_lines = editor_h - 2
            for i, line in enumerate(editor_lines[:max_editor_lines]):
                safe_addstr(editor_win, 1 + i, 2, line[: right_w - 4])
            if focus == "editor":
                safe_addstr(editor_win, editor_h - 2, 2, "Enter=Editar | F5=Executar | TAB=Foco")

            # Results panel (right bottom)
            result_y = editor_y + editor_h + 1
            results_win = panel_window(stdscr, result_y, editor_x, result_h, right_w, res["title"], focused=(focus == "results"))
            max_result_lines = result_h - 2
            avail_w = max(1, right_w - 4)
            if res["error"]:
                lines = res["error"].splitlines() or [res["error"]]
                for i, line in enumerate(lines[:max_result_lines]):
                    safe_addstr(results_win, 1 + i, 2, line[:avail_w])
            elif res["cols"] is not None and res["rows"] is not None:
                max_data_rows = max(1, max_result_lines - 2)
                max_scroll_y = max(0, res["row_count"] - max_data_rows)
                res["scroll"] = max(0, min(res["scroll"], max_scroll_y))
                lines, total_width = format_table_view(
                    res["cols"], res["rows"], res["scroll"], max_data_rows
                )
                max_scroll_x = max(0, total_width - avail_w)
                res["scroll_x"] = max(0, min(res["scroll_x"], max_scroll_x))
                for i, line in enumerate(lines[:max_result_lines]):
                    view = line[res["scroll_x"] : res["scroll_x"] + avail_w]
                    safe_addstr(results_win, 1 + i, 2, view)
            elif res["msg"]:
                safe_addstr(results_win, 1, 2, res["msg"][:avail_w])
            else:
                safe_addstr(results_win, 1, 2, "Sem resultados.")
            if focus == "results":
                info = f"Setas=Scroll | <-/->=Colunas | F6=Salvar CSV | Rows={res['row_count']} Cols={res['col_count']}"
                safe_addstr(results_win, result_h - 2, 2, info[: right_w - 4])

            # Footer
            footer = "ESC = Desconectar | R = Atualizar | F9 = Modo avancado | TAB = Alternar foco | Shift+TAB = Foco anterior | Ctrl+N = Nova query | Ctrl+X = Fechar query | Ctrl+TAB = Trocar query | F6 = Salvar CSV | F1 = Ajuda"
            safe_addstr(stdscr, h - 1, 2, footer[: w - 4])

            stdscr.refresh()
            tree_win.refresh()
            editor_win.refresh()
            results_win.refresh()

            ch = stdscr.getch()
            if ch == curses.KEY_F1:
                screen_help(stdscr)
                continue
            if ch in (27,):
                return "disconnect"
            if ch == curses.KEY_F9:
                screen_advanced(stdscr, cfg, current, conn)
                continue
            if ch == curses.KEY_F6:
                if res["cols"] is not None and res["rows"] is not None:
                    default_path = default_csv_path()
                    try:
                        curses.endwin()
                    except Exception:
                        pass
                    path = choose_save_path(default_path) or prompt_input(stdscr, "Salvar CSV em:", default_path)
                    if path:
                        try:
                            export_csv(path, res["cols"], res["rows"])
                            panel_message(stdscr, result_y, editor_x, result_h, right_w, "Download CSV", f"Salvo em:\n{path}")
                        except Exception as e:
                            panel_message(stdscr, result_y, editor_x, result_h, right_w, "Erro", str(e))
                else:
                    panel_message(stdscr, result_y, editor_x, result_h, right_w, "Download CSV", "Nenhum resultado para exportar.")
                continue
            if ch == curses.ascii.SO:  # Ctrl+N
                new_tab("")
                focus = "editor"
                enter_edit_on_focus = True
                continue
            if ch == curses.ascii.CAN:  # Ctrl+X
                if len(tabs) > 1:
                    tabs.pop(tab_index)
                    if tab_index >= len(tabs):
                        tab_index = len(tabs) - 1
                else:
                    tabs[0]["text"] = ""
                    tabs[0]["result"]["cols"] = None
                    tabs[0]["result"]["rows"] = None
                    tabs[0]["result"]["row_count"] = 0
                    tabs[0]["result"]["col_count"] = 0
                    tabs[0]["result"]["title"] = "Results"
                    tabs[0]["result"]["msg"] = ""
                    tabs[0]["result"]["error"] = ""
                    tabs[0]["result"]["scroll"] = 0
                    tabs[0]["result"]["scroll_x"] = 0
                focus = "editor"
                continue
            if ch in (curses.KEY_CTAB, 341):
                tab_index = (tab_index + 1) % len(tabs)
                focus = "editor"
                continue
            if ch in (curses.KEY_CATAB, 342):
                tab_index = (tab_index - 1) % len(tabs)
                focus = "editor"
                continue
            if ch == curses.KEY_F8:
                tab_index = (tab_index + 1) % len(tabs)
                focus = "editor"
                continue
            if ch == curses.KEY_F7:
                tab_index = (tab_index - 1) % len(tabs)
                focus = "editor"
                continue
            if ch in (9, curses.KEY_BTAB, 353):  # TAB / Shift+TAB
                if ch == 9:
                    if focus == "tree":
                        focus = "editor"
                    elif focus == "editor":
                        focus = "results"
                    else:
                        focus = "tree"
                else:
                    if focus == "tree":
                        focus = "results"
                    elif focus == "editor":
                        focus = "tree"
                    else:
                        focus = "editor"
                continue
            if ch == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except Exception:
                    continue
                # click in tree panel
                if content_top <= my < content_top + content_h and 1 <= mx < left_w:
                    focus = "tree"
                    max_tree_lines = content_h - 2
                    start = 0
                    if tree_idx >= max_tree_lines:
                        start = tree_idx - max_tree_lines + 1
                    rel = my - (content_top + 1)
                    if 0 <= rel < max_tree_lines:
                        idx_click = start + rel
                        if idx_click < len(tree_items):
                            tree_idx = idx_click
                    continue
                # click in editor panel
                if editor_y <= my < editor_y + editor_h and editor_x <= mx < editor_x + right_w:
                    focus = "editor"
                    enter_edit_on_focus = True
                    continue
                # click in results panel
                if result_y <= my < result_y + result_h and editor_x <= mx < editor_x + right_w:
                    focus = "results"
                    # scroll wheel in results
                    if bstate & getattr(curses, "BUTTON4_PRESSED", 0):
                        res["scroll"] = max(0, res["scroll"] - 3)
                    if bstate & getattr(curses, "BUTTON5_PRESSED", 0):
                        res["scroll"] = min(max(0, res["row_count"] - 1), res["scroll"] + 3)
                    continue
            if ch in (ord("r"), ord("R")):
                dbs = []
                tables_cache = {}
                columns_cache = {}
                continue

            if focus == "tree":
                if ch in (curses.KEY_UP,):
                    tree_idx = (tree_idx - 1) % len(tree_items)
                    continue
                if ch in (curses.KEY_DOWN,):
                    tree_idx = (tree_idx + 1) % len(tree_items)
                    continue

                item = tree_items[tree_idx] if tree_items else None
                if not item:
                    continue

                if ch in (curses.KEY_RIGHT, ord(" ")):
                    if item["type"] == "db":
                        db = item["db"]
                        if db in expanded_dbs:
                            expanded_dbs.remove(db)
                        else:
                            try:
                                tables_cache[db] = fetch_tables_for_db(conn, current.get("database"), db)
                            except Exception as e:
                                panel_message(stdscr, content_top, right_x, content_h, right_w, "Erro", str(e))
                            expanded_dbs.add(db)
                    elif item["type"] == "table":
                        key = (item["db"], item["table"])
                        if key in expanded_tables:
                            expanded_tables.remove(key)
                        else:
                            if "." in item["table"]:
                                schema, table = item["table"].split(".", 1)
                            else:
                                schema, table = "dbo", item["table"]
                            try:
                                cols = fetch_columns_for_table(conn, current.get("database"), item["db"], schema, table)
                                columns_cache[key] = [c[0] for c in cols]
                            except Exception:
                                columns_cache[key] = []
                            expanded_tables.add(key)
                    continue

                if ch in (curses.KEY_LEFT,):
                    if item["type"] == "db" and item["db"] in expanded_dbs:
                        expanded_dbs.remove(item["db"])
                    if item["type"] == "table":
                        key = (item["db"], item["table"])
                        if key in expanded_tables:
                            expanded_tables.remove(key)
                    continue

                if ch in (curses.KEY_ENTER, 10, 13):
                    if item["type"] == "db":
                        selected = item["db"]
                        try:
                            conn.execute(f"USE [{selected}]")
                            current["database"] = selected
                            tables_cache = {}
                            columns_cache = {}
                        except Exception as e:
                            panel_message(stdscr, content_top, right_x, content_h, right_w, "Erro", str(e))
                    elif item["type"] == "table":
                        if "." in item["table"]:
                            schema, table = item["table"].split(".", 1)
                        else:
                            schema, table = "dbo", item["table"]
                        # Garante que o DB correto esta selecionado
                        if item["db"] != current.get("database"):
                            try:
                                conn.execute(f"USE [{item['db']}]")
                                current["database"] = item["db"]
                                tables_cache = {}
                                columns_cache = {}
                            except Exception as e:
                                panel_message(stdscr, content_top, right_x, content_h, right_w, "Erro", str(e))
                                continue
                        tab["text"] = f"SELECT TOP 100 * FROM {build_table_ref(schema, table)}"
                    continue

                if item["type"] == "table" and ch in (ord("s"), ord("S"), ord("i"), ord("I"), ord("u"), ord("U"), ord("d"), ord("D")):
                    if "." in item["table"]:
                        schema, table = item["table"].split(".", 1)
                    else:
                        schema, table = "dbo", item["table"]
                    if item["db"] != current.get("database"):
                        try:
                            conn.execute(f"USE [{item['db']}]")
                            current["database"] = item["db"]
                            tables_cache = {}
                            columns_cache = {}
                        except Exception as e:
                            panel_message(stdscr, content_top, right_x, content_h, right_w, "Erro", str(e))
                            continue
                    if ch in (ord("s"), ord("S")):
                        tab["text"] = f"SELECT TOP 100 * FROM {build_table_ref(schema, table)}"
                    elif ch in (ord("i"), ord("I")):
                        tab["text"] = f"INSERT INTO {build_table_ref(schema, table)} (col1, col2) VALUES (val1, val2)"
                    elif ch in (ord("u"), ord("U")):
                        tab["text"] = f"UPDATE {build_table_ref(schema, table)} SET col1 = val1 WHERE condicao"
                    else:
                        tab["text"] = f"DELETE FROM {build_table_ref(schema, table)} WHERE condicao"
                    continue

            elif focus == "editor":
                if ch in (curses.KEY_ENTER, 10, 13):
                    new_text, action = editor_edit(stdscr, editor_y, editor_x, editor_h, right_w, tab["text"])
                    tab["text"] = new_text
                    if action == "execute":
                        execute_and_set(tab["text"])
                    elif action == "tab_next":
                        focus = "results"
                    elif action == "tab_prev":
                        focus = "tree"
                    elif action == "new_tab":
                        new_tab("")
                        focus = "editor"
                        enter_edit_on_focus = True
                    elif action == "close_tab":
                        if len(tabs) > 1:
                            tabs.pop(tab_index)
                            if tab_index >= len(tabs):
                                tab_index = len(tabs) - 1
                        else:
                            tabs[0]["text"] = ""
                            tabs[0]["result"]["cols"] = None
                            tabs[0]["result"]["rows"] = None
                            tabs[0]["result"]["row_count"] = 0
                            tabs[0]["result"]["col_count"] = 0
                            tabs[0]["result"]["title"] = "Results"
                            tabs[0]["result"]["msg"] = ""
                            tabs[0]["result"]["error"] = ""
                            tabs[0]["result"]["scroll"] = 0
                            tabs[0]["result"]["scroll_x"] = 0
                        focus = "editor"
                        enter_edit_on_focus = True
                    elif action == "switch_tab_next":
                        tab_index = (tab_index + 1) % len(tabs)
                        focus = "editor"
                        enter_edit_on_focus = True
                    elif action == "switch_tab_prev":
                        tab_index = (tab_index - 1) % len(tabs)
                        focus = "editor"
                        enter_edit_on_focus = True
                    continue
                if ch in (curses.KEY_F5, curses.KEY_F2):
                    if tab["text"].strip():
                        execute_and_set(tab["text"])
                    continue
                if ch == curses.ascii.CAN:  # Ctrl+X
                    if len(tabs) > 1:
                        tabs.pop(tab_index)
                        if tab_index >= len(tabs):
                            tab_index = len(tabs) - 1
                    else:
                        tabs[0]["text"] = ""
                        tabs[0]["result"]["cols"] = None
                        tabs[0]["result"]["rows"] = None
                        tabs[0]["result"]["row_count"] = 0
                        tabs[0]["result"]["col_count"] = 0
                        tabs[0]["result"]["title"] = "Results"
                        tabs[0]["result"]["msg"] = ""
                        tabs[0]["result"]["error"] = ""
                        tabs[0]["result"]["scroll"] = 0
                        tabs[0]["result"]["scroll_x"] = 0
                    focus = "editor"
                    continue

            elif focus == "results":
                if ch in (curses.KEY_UP,):
                    res["scroll"] = max(0, res["scroll"] - 1)
                elif ch in (curses.KEY_DOWN,):
                    if res["rows"]:
                        res["scroll"] = min(max(0, res["row_count"] - 1), res["scroll"] + 1)
                elif ch in (curses.KEY_LEFT,):
                    res["scroll_x"] = max(0, res["scroll_x"] - 3)
                elif ch in (curses.KEY_RIGHT,):
                    res["scroll_x"] = res["scroll_x"] + 3
                elif ch in (curses.KEY_NPAGE,):
                    res["scroll"] = min(max(0, res["row_count"] - 1), res["scroll"] + max(1, result_h - 3))
                elif ch in (curses.KEY_PPAGE,):
                    res["scroll"] = max(0, res["scroll"] - max(1, result_h - 3))
                continue
    except Exception:
        log_event("CRASH_WORKSPACE\n" + traceback.format_exc())
        screen_message(stdscr, "Erro", "Ocorreu um erro inesperado no workspace.")
        return "disconnect"

def screen_menu(stdscr, title, items):
    idx = 0
    while True:
        stdscr.clear()
        draw_header(stdscr, title)
        h, w = stdscr.getmaxyx()
        for i, item in enumerate(items):
            y = 3 + i
            attr = curses.A_REVERSE if i == idx else 0
            safe_addstr(stdscr, y, 2, item[: w - 4], attr)
        safe_addstr(stdscr, h - 2, 2, "Enter = Selecionar | F1 = Ajuda | ESC = Voltar")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (27,):
            return None
        if ch == curses.KEY_F1:
            screen_help(stdscr)
            continue
        if ch in (curses.KEY_UP,):
            idx = (idx - 1) % len(items)
        elif ch in (curses.KEY_DOWN,):
            idx = (idx + 1) % len(items)
        elif ch in (curses.KEY_ENTER, 10, 13):
            return items[idx]

def screen_pick(stdscr, title, items, footer="Enter = Selecionar | ESC = Voltar"):
    if not items:
        screen_message(stdscr, title, "Nenhum item encontrado.")
        return None
    idx = 0
    while True:
        stdscr.clear()
        draw_header(stdscr, title)
        h, w = stdscr.getmaxyx()
        max_lines = h - 4
        start = 0
        if idx >= max_lines:
            start = idx - max_lines + 1
        for i, item in enumerate(items[start : start + max_lines]):
            y = 2 + i
            attr = curses.A_REVERSE if (start + i) == idx else 0
            safe_addstr(stdscr, y, 2, str(item)[: w - 4], attr)
        safe_addstr(stdscr, h - 2, 2, footer[: w - 4])
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (27,):
            return None
        if ch in (curses.KEY_UP,):
            idx = (idx - 1) % len(items)
        elif ch in (curses.KEY_DOWN,):
            idx = (idx + 1) % len(items)
        elif ch in (curses.KEY_ENTER, 10, 13):
            return items[idx]

def screen_select_multi(stdscr, title, items):
    if not items:
        screen_message(stdscr, title, "Nenhum item encontrado.")
        return None
    selected = [False] * len(items)
    idx = 0
    while True:
        stdscr.clear()
        draw_header(stdscr, title)
        h, w = stdscr.getmaxyx()
        max_lines = h - 4
        start = 0
        if idx >= max_lines:
            start = idx - max_lines + 1
        for i, item in enumerate(items[start : start + max_lines]):
            idx_abs = start + i
            mark = "[x]" if selected[idx_abs] else "[ ]"
            line = f"{mark} {item}"
            attr = curses.A_REVERSE if idx_abs == idx else 0
            safe_addstr(stdscr, 2 + i, 2, line[: w - 4], attr)
        safe_addstr(stdscr, h - 2, 2, "Espaco = marcar | Enter = confirmar | ESC = voltar")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (27,):
            return None
        if ch in (curses.KEY_UP,):
            idx = (idx - 1) % len(items)
        elif ch in (curses.KEY_DOWN,):
            idx = (idx + 1) % len(items)
        elif ch in (ord(" "),):
            selected[idx] = not selected[idx]
        elif ch in (curses.KEY_ENTER, 10, 13):
            chosen = [items[i] for i, flag in enumerate(selected) if flag]
            if chosen:
                return chosen

def screen_confirm(stdscr, title, message):
    stdscr.clear()
    draw_header(stdscr, title)
    h, w = stdscr.getmaxyx()
    lines = message.splitlines()
    for i, line in enumerate(lines[: h - 4]):
        safe_addstr(stdscr, 2 + i, 2, line[: w - 4])
    safe_addstr(stdscr, h - 2, 2, "Enter = Iniciar | ESC = Cancelar")
    stdscr.refresh()
    while True:
        ch = stdscr.getch()
        if ch in (27,):
            return False
        if ch in (curses.KEY_ENTER, 10, 13):
            return True

def render_progress(stdscr, title, origin_label, dest_label, table_name, table_idx, table_total, copied, total):
    stdscr.clear()
    draw_header(stdscr, title)
    h, w = stdscr.getmaxyx()
    safe_addstr(stdscr, 2, 2, "NÃO FECHAR O APP ATÉ FINALIZAR")
    safe_addstr(stdscr, 4, 2, f"Origem: {origin_label}"[: w - 4])
    safe_addstr(stdscr, 5, 2, f"Destino: {dest_label}"[: w - 4])
    safe_addstr(stdscr, 7, 2, f"Tabela {table_idx}/{table_total}: {table_name}"[: w - 4])
    if total > 0:
        percent = int((copied / total) * 100)
    else:
        percent = 0
    bar_w = max(10, w - 10)
    filled = int((percent / 100) * bar_w)
    bar = "[" + "#" * filled + "-" * (bar_w - filled) + "]"
    safe_addstr(stdscr, 9, 2, bar[: w - 4])
    safe_addstr(stdscr, 10, 2, f"{copied}/{total} linhas ({percent}%)"[: w - 4])
    stdscr.refresh()

def mirror_tables(stdscr, origin_conn, dest_conn, origin_db, dest_db, tables, origin_label, dest_label):
    try:
        origin_conn.execute(f"USE [{origin_db}]")
        dest_conn.execute(f"USE [{dest_db}]")
    except Exception as e:
        screen_message(stdscr, "Erro", str(e))
        return False
    total_tables = len(tables)
    batch_size = 1000
    for idx, t in enumerate(tables, start=1):
        schema, table = split_table_name(t)
        try:
            cols = fetch_columns(origin_conn, schema, table)
            col_names = [c[0] for c in cols]
            if not col_names:
                continue
            select_cols = ", ".join(f"[{c}]" for c in col_names)
            select_sql = f"SELECT {select_cols} FROM {build_table_ref(schema, table)}"
            insert_sql = build_insert_sql(schema, table, col_names)
            try:
                total = origin_conn.execute(f"SELECT COUNT(*) FROM {build_table_ref(schema, table)}").fetchone()[0]
            except Exception:
                total = 0
            copied = 0
            cur = origin_conn.cursor()
            cur.execute(select_sql)
            dest_cur = dest_conn.cursor()
            try:
                dest_cur.fast_executemany = True
            except Exception:
                pass
            render_progress(stdscr, "Modo Avançado - Espelhar Banco", origin_label, dest_label, t, idx, total_tables, copied, total)
            while True:
                rows = cur.fetchmany(batch_size)
                if not rows:
                    break
                dest_cur.executemany(insert_sql, rows)
                copied += len(rows)
                render_progress(stdscr, "Modo Avançado - Espelhar Banco", origin_label, dest_label, t, idx, total_tables, copied, total)
        except Exception as e:
            screen_message(stdscr, "Erro", f"{t}\n{e}")
            return False
    return True

def screen_advanced(stdscr, cfg, current, conn):
    while True:
        choice = screen_menu(stdscr, "Modo Avançado", ["Espelhar Banco", "Voltar"])
        if choice != "Espelhar Banco":
            return

        origin_choice = screen_menu(
            stdscr,
            "Espelhar Banco - Origem",
            [
                f"Usar conexao atual ({current.get('user','')}@{current.get('host','')}:{current.get('port','')}/{current.get('database','')})",
                "Outra conexao de origem",
                "Voltar",
            ],
        )
        if origin_choice is None or origin_choice == "Voltar":
            continue

        origin_conn = conn
        origin_label = f"{current.get('user','')}@{current.get('host','')}:{current.get('port','')}"
        origin_db_default = current.get("database") or "master"
        close_origin = False

        if origin_choice.startswith("Outra"):
            tmp_current = {
                "name": "",
                "host": "",
                "port": cfg.get("port", "1433") or "1433",
                "user": "",
                "database": "master",
                "driver": cfg.get("driver", "ODBC Driver 18 for SQL Server"),
            }
            cfg2, cur2, pwd2 = screen_connect(stdscr, cfg, tmp_current, "")
            if cfg2 is None:
                continue
            conn_cfg = dict(cfg2)
            conn_cfg.update(cur2)
            origin_conn, err = connect_db(conn_cfg, pwd2)
            if err:
                screen_message(stdscr, "Erro", err)
                continue
            origin_label = f"{cur2.get('user','')}@{cur2.get('host','')}:{cur2.get('port','')}"
            origin_db_default = cur2.get("database") or "master"
            close_origin = True

        tmp_current = {
            "name": "",
            "host": "",
            "port": cfg.get("port", "1433") or "1433",
            "user": "",
            "database": "master",
            "driver": cfg.get("driver", "ODBC Driver 18 for SQL Server"),
        }
        cfg3, cur3, pwd3 = screen_connect(stdscr, cfg, tmp_current, "")
        if cfg3 is None:
            if close_origin:
                try:
                    origin_conn.close()
                except Exception:
                    pass
            continue
        conn_cfg = dict(cfg3)
        conn_cfg.update(cur3)
        dest_conn, err = connect_db(conn_cfg, pwd3)
        if err:
            if close_origin:
                try:
                    origin_conn.close()
                except Exception:
                    pass
            screen_message(stdscr, "Erro", err)
            continue
        dest_label = f"{cur3.get('user','')}@{cur3.get('host','')}:{cur3.get('port','')}"

        try:
            origin_dbs = fetch_databases(origin_conn)
            dest_dbs = fetch_databases(dest_conn)
        except Exception as e:
            screen_message(stdscr, "Erro", str(e))
            try:
                dest_conn.close()
            except Exception:
                pass
            if close_origin:
                try:
                    origin_conn.close()
                except Exception:
                    pass
            continue

        origin_db = screen_pick(stdscr, "Origem - Database", origin_dbs)
        if not origin_db:
            try:
                dest_conn.close()
            except Exception:
                pass
            if close_origin:
                try:
                    origin_conn.close()
                except Exception:
                    pass
            continue

        dest_db = screen_pick(stdscr, "Destino - Database", dest_dbs)
        if not dest_db:
            try:
                dest_conn.close()
            except Exception:
                pass
            if close_origin:
                try:
                    origin_conn.close()
                except Exception:
                    pass
            continue

        mode = screen_menu(stdscr, "Espelhar Banco", ["Database inteiro", "Tabela(s)", "Voltar"])
        if mode is None or mode == "Voltar":
            try:
                dest_conn.close()
            except Exception:
                pass
            if close_origin:
                try:
                    origin_conn.close()
                except Exception:
                    pass
            continue

        try:
            origin_conn.execute(f"USE [{origin_db}]")
            tables = fetch_tables(origin_conn)
        except Exception as e:
            screen_message(stdscr, "Erro", str(e))
            try:
                dest_conn.close()
            except Exception:
                pass
            if close_origin:
                try:
                    origin_conn.close()
                except Exception:
                    pass
            continue

        if mode == "Tabela(s)":
            tables = screen_select_multi(stdscr, "Selecionar Tabelas", tables)
            if not tables:
                try:
                    dest_conn.close()
                except Exception:
                    pass
                if close_origin:
                    try:
                        origin_conn.close()
                    except Exception:
                        pass
                continue

        confirm = screen_confirm(
            stdscr,
            "Confirmar Espelhamento",
            "\n".join(
                [
                    f"Origem: {origin_label} / {origin_db}",
                    f"Destino: {dest_label} / {dest_db}",
                    f"Tabelas: {len(tables)}",
                    "",
                    "NÃO FECHAR O APP ATÉ FINALIZAR.",
                ]
            ),
        )
        if not confirm:
            try:
                dest_conn.close()
            except Exception:
                pass
            if close_origin:
                try:
                    origin_conn.close()
                except Exception:
                    pass
            continue

        ok = mirror_tables(stdscr, origin_conn, dest_conn, origin_db, dest_db, tables, origin_label, dest_label)
        try:
            dest_conn.close()
        except Exception:
            pass
        if close_origin:
            try:
                origin_conn.close()
            except Exception:
                pass
        if ok:
            screen_message(stdscr, "Concluido", "Espelhamento finalizado com sucesso.")

def screen_databases(stdscr, conn, current_db):
    try:
        dbs = fetch_databases(conn)
    except Exception as e:
        screen_message(stdscr, "Erro", str(e))
        return current_db
    idx = 0
    while True:
        stdscr.clear()
        draw_header(stdscr, "Databases")
        h, w = stdscr.getmaxyx()
        safe_addstr(stdscr, 2, 2, f"Atual: {current_db or '-'}")
        for i, name in enumerate(dbs[: h - 6]):
            y = 4 + i
            attr = curses.A_REVERSE if i == idx else 0
            safe_addstr(stdscr, y, 2, name[: w - 4], attr)
        safe_addstr(stdscr, h - 2, 2, "Enter = Usar DB | R = Atualizar | ESC = Voltar")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (27,):
            return current_db
        if ch in (curses.KEY_UP,):
            idx = (idx - 1) % len(dbs)
        elif ch in (curses.KEY_DOWN,):
            idx = (idx + 1) % len(dbs)
        elif ch in (ord("r"), ord("R")):
            try:
                dbs = fetch_databases(conn)
            except Exception as e:
                screen_message(stdscr, "Erro", str(e))
        elif ch in (curses.KEY_ENTER, 10, 13):
            selected = dbs[idx]
            try:
                conn.execute(f"USE [{selected}]")
                return selected
            except Exception as e:
                screen_message(stdscr, "Erro", str(e))


def screen_tables(stdscr, conn):
    try:
        tables = fetch_tables(conn)
    except Exception as e:
        screen_message(stdscr, "Erro", str(e))
        return None
    idx = 0
    while True:
        stdscr.clear()
        draw_header(stdscr, "Tabelas")
        h, w = stdscr.getmaxyx()
        left_w = w // 2
        safe_addstr(stdscr, 2, 2, "Tabelas")
        safe_addstr(stdscr, 2, left_w + 2, "Colunas")
        max_rows = h - 6
        for i, name in enumerate(tables[:max_rows]):
            y = 4 + i
            attr = curses.A_REVERSE if i == idx else 0
            safe_addstr(stdscr, y, 2, name[: left_w - 4], attr)
        if tables:
            sel = tables[idx]
            if "." in sel:
                schema, table = sel.split(".", 1)
                try:
                    cols = fetch_columns(conn, schema, table)
                    for i, col in enumerate(cols[: max_rows]):
                        y = 4 + i
                        name = f"{col[0]} ({col[1]}) {'NULL' if col[2]=='YES' else 'NOT NULL'}"
                        safe_addstr(stdscr, y, left_w + 2, name[: w - left_w - 4])
                except Exception:
                    pass
        safe_addstr(stdscr, h - 2, 2, "S=SELECT  I=INSERT  U=UPDATE  D=DELETE  R=Atualizar  F1=Ajuda  ESC=Voltar")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (27,):
            return None
        if ch == curses.KEY_F1:
            screen_help(stdscr)
            continue
        if ch in (curses.KEY_UP,):
            idx = (idx - 1) % len(tables)
        elif ch in (curses.KEY_DOWN,):
            idx = (idx + 1) % len(tables)
        elif ch in (ord("r"), ord("R")):
            try:
                tables = fetch_tables(conn)
            except Exception as e:
                screen_message(stdscr, "Erro", str(e))
        elif ch in (ord("s"), ord("S"), ord("i"), ord("I"), ord("u"), ord("U"), ord("d"), ord("D")):
            if not tables:
                continue
            sel = tables[idx]
            schema, table = sel.split(".", 1)
            if ch in (ord("s"), ord("S")):
                sql = f"SELECT TOP 100 * FROM [{schema}].[{table}]"
            elif ch in (ord("i"), ord("I")):
                sql = f"INSERT INTO [{schema}].[{table}] (col1, col2) VALUES (val1, val2)"
            elif ch in (ord("u"), ord("U")):
                sql = f"UPDATE [{schema}].[{table}] SET col1 = val1 WHERE condicao"
            else:
                sql = f"DELETE FROM [{schema}].[{table}] WHERE condicao"
            return sql


def screen_query(stdscr, conn, initial_sql=""):
    stdscr.clear()
    draw_header(stdscr, "Query")
    h, w = stdscr.getmaxyx()
    safe_addstr(stdscr, 2, 2, "Edite o SQL. F2 = executar | F1 = ajuda | ESC = voltar")
    edit_h = h - 8
    edit_w = w - 4
    edit_win = curses.newwin(edit_h, edit_w, 4, 2)
    edit_win.border()
    txt_win = curses.newwin(edit_h - 2, edit_w - 2, 5, 3)
    safe_keypad(txt_win, True)
    txt_win.erase()
    txt_win.addstr(0, 0, initial_sql)
    txt_win.refresh()
    box = curses.textpad.Textbox(txt_win, insert_mode=True)
    box.stripspaces = 0

    state = {"cancel": False}

    def validator(ch):
        if ch == curses.KEY_DC:
            delete_forward_at_cursor(box)
            return 0
        if ch in (curses.KEY_ENTER, 10, 13):
            insert_newline_at_cursor(box)
            return 0
        if ch == 3:  # Ctrl+C
            text = box.gather().rstrip()
            if text:
                set_clipboard_text(text)
            return 0
        if ch == 22:  # Ctrl+V
            text = get_clipboard_text()
            if text:
                for c in text:
                    if c == "\r":
                        continue
                    if c == "\n":
                        box.do_command(curses.ascii.NL)
                    else:
                        box.do_command(ord(c))
            return 0
        if ch in (curses.KEY_HOME, 262):
            return 1  # Ctrl+A
        if ch in (curses.KEY_END, 360):
            return 5  # Ctrl+E
        if ch == curses.KEY_F2:
            return 7  # Ctrl+G para finalizar
        if ch == curses.KEY_F1:
            screen_help(stdscr)
            return 0
        if ch == 27:
            state["cancel"] = True
            return 7
        return ch

    safe_curs_set(1)
    content = box.edit(validator)
    safe_curs_set(0)
    if state["cancel"]:
        return
    sql = content.strip()
    if not sql:
        return
    try:
        cols, rows, rowcount = run_query(conn, sql)
        stdscr.clear()
        draw_header(stdscr, "Resultado")
        h, w = stdscr.getmaxyx()
        if cols:
            lines = format_table(cols, rows, w - 4, h - 6)
            for i, line in enumerate(lines[: h - 4]):
                safe_addstr(stdscr, 2 + i, 2, line[: w - 4])
            safe_addstr(stdscr, h - 2, 2, f"Linhas exibidas: {len(rows)}")
        else:
            safe_addstr(stdscr, 2, 2, f"OK. Linhas afetadas: {rowcount}")
        stdscr.getch()
    except Exception as e:
        screen_message(stdscr, "Erro", str(e))


def app(stdscr):
    safe_curs_set(0)
    safe_start_color()
    safe_use_default_colors()
    safe_keypad(stdscr, True)
    safe_raw()
    global FOCUS_ATTR
    try:
        if curses.has_colors():
            curses.init_pair(1, curses.COLOR_BLUE, -1)
            FOCUS_ATTR = curses.color_pair(1)
    except curses.error:
        FOCUS_ATTR = 0
    try:
        screen_splash(stdscr)
        cfg = load_config()
        current = {
            "name": "",
            "host": "",
            "port": cfg.get("port", "1433") or "1433",
            "user": "",
            "database": "master",
            "driver": cfg.get("driver", "ODBC Driver 18 for SQL Server"),
        }
        password = ""
        while True:
            cfg, current, password = screen_connect(stdscr, cfg, current, password)
            if cfg is None:
                return
            stdscr.clear()
            draw_header(stdscr, f"Jupyter-SSMS {VERSION} - Conectando...")
            stdscr.refresh()
            conn_cfg = dict(cfg)
            conn_cfg.update(current)
            conn, err = connect_db(conn_cfg, password)
            if err:
                screen_message(stdscr, "Erro", err)
                continue
            # Persistir configuracoes nao sensiveis
            cfg["port"] = current.get("port", cfg.get("port", "1433"))
            cfg["driver"] = current.get("driver", cfg.get("driver", "ODBC Driver 18 for SQL Server"))
            save_config(cfg)

            if cfg.get("remember"):
                entry = {
                    "name": current.get("name", ""),
                    "host": current.get("host", ""),
                    "port": current.get("port", "1433"),
                    "user": current.get("user", ""),
                    "database": current.get("database", "master"),
                    "driver": current.get("driver", cfg.get("driver", "")),
                    "encrypt": bool(cfg.get("encrypt", True)),
                    "trust_server_certificate": bool(cfg.get("trust_server_certificate", True)),
                }
                if cfg.get("save_password") and password:
                    entry["password"] = password
                upsert_history(cfg, entry)

            while True:
                action = screen_workspace(stdscr, conn, cfg, current)
                if action == "disconnect":
                    try:
                        conn.close()
                    except Exception:
                        pass
                    break
                if action == "exit":
                    try:
                        conn.close()
                    except Exception:
                        pass
                    return
    finally:
        safe_noraw()


if __name__ == "__main__":
    try:
        curses.wrapper(app)
    except Exception:
        try:
            curses.endwin()
        except Exception:
            pass
        tb = traceback.format_exc()
        log_event("CRASH\\n" + tb)
        sys.stderr.write("Erro: o app fechou inesperadamente. Veja o log em jupyter_ssms.log\\n")
    except KeyboardInterrupt:
        pass
