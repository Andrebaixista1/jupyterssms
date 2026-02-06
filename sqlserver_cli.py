#!/usr/bin/env python3
import curses
import curses.textpad
import json
import os
import sys
import traceback
import time
from datetime import datetime

try:
    import pyodbc
except Exception:
    pyodbc = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_PATH = os.path.join(BASE_DIR, "jupyter_ssms.log")
VERSION = "Io v0.06022026"

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
    "password": "",
    "history": [],
}


def log_event(message):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")
    except Exception:
        pass


def load_config():
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
            save_config(cfg)
        return cfg
    except Exception:
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)


def save_config(cfg):
    try:
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
        conn = pyodbc.connect(conn_str, timeout=5)
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
    rows = cur.fetchmany(500)
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
            "- F3: historico de conexoes.",
            "",
            "Menu:",
            "- Databases: listar e trocar DB.",
            "- Tabelas: ver tabelas e colunas.",
            "- CRUD (template): gera SELECT/INSERT/UPDATE/DELETE.",
            "- Query: executar SQL livre.",
            "",
            "Atalhos gerais:",
            "- F1: ajuda.",
            "- ESC: voltar/sair.",
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
    art = [
        "        .-\"\"\"-.",
        "     .-'  .-.  '-.",
        "    /    (   )    \\",
        "   |  .-.-' `-.-.  |",
        "   |  |  JUPITER |  |",
        "    \\  '._.___.'  /",
        "     '-._____.-'",
        "        /  |  \\",
        "     __/___|___\\__",
    ]
    info = [
        f"Jupyter-SSMS {VERSION}",
        f"OS: {get_os_pretty_name()}",
        f"Python: {sys.version.split()[0]}",
        "Pressione qualquer tecla para continuar...",
    ]
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
    host = entry.get("host", "")
    port = entry.get("port", "")
    user = entry.get("user", "")
    db = entry.get("database", "") or "-"
    label = f"{user}@{host}:{port}/{db}"
    if entry.get("password"):
        label += " [senha]"
    return label


def screen_history(stdscr, cfg, password):
    history = list(cfg.get("history", []))
    if not history:
        screen_message(stdscr, "Historico", "Sem conexoes salvas.")
        return cfg, password
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
            return cfg, password
        if ch in (curses.KEY_UP,):
            idx = (idx - 1) % len(history)
        elif ch in (curses.KEY_DOWN,):
            idx = (idx + 1) % len(history)
        elif ch in (curses.KEY_DC, 330):
            item = history.pop(idx)
            cfg["history"] = history
            save_config(cfg)
            if not history:
                return cfg, password
            idx = min(idx, len(history) - 1)
        elif ch in (curses.KEY_ENTER, 10, 13):
            item = history[idx]
            for key in ("host", "port", "user", "database", "driver", "encrypt", "trust_server_certificate"):
                if key in item:
                    cfg[key] = item[key]
            save_config(cfg)
            if item.get("password"):
                password = item.get("password", "")
            return cfg, password


def screen_connect(stdscr, cfg):
    fields = [
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
    password = cfg.get("password", "") if cfg.get("save_password") else ""
    idx = 0
    while True:
        stdscr.clear()
        draw_header(stdscr, f"Jupyter-SSMS {VERSION} - Conexao")
        h, w = stdscr.getmaxyx()
        for i, (label, key, ftype) in enumerate(fields):
            y = 3 + i
            if ftype == "password":
                val = "*" * len(password) if password else ""
            elif ftype == "bool":
                val = "ON" if cfg.get(key, False) else "OFF"
            else:
                val = str(cfg.get(key, ""))
            line = f"{label}: {val}"
            attr = curses.A_REVERSE if i == idx else 0
            safe_addstr(stdscr, y, 2, line[: w - 4], attr)
        safe_addstr(stdscr, h - 4, 2, "Digite direto no campo | TAB/Setas = navegar")
        safe_addstr(stdscr, h - 3, 2, "F2 = Conectar | F3 = Historico | F1 = Ajuda")
        safe_addstr(stdscr, h - 2, 2, "ESPACO = toggle | ESC = Sair")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (27,):
            return None, None
        if ch in (curses.KEY_UP,):
            idx = (idx - 1) % len(fields)
            continue
        if ch in (curses.KEY_DOWN,):
            idx = (idx + 1) % len(fields)
            continue
        if ch in (9,):  # TAB
            idx = (idx + 1) % len(fields)
            continue
        label, key, ftype = fields[idx]
        if ch == curses.KEY_F3:
            cfg, password = screen_history(stdscr, cfg, password)
            continue
        if ch == curses.KEY_F1:
            screen_help(stdscr)
            continue
        if ch == curses.KEY_F2:
            if not cfg.get("host") or not cfg.get("user"):
                screen_message(stdscr, "Erro", "Host e User sao obrigatorios.")
                continue
            return cfg, password
        if ftype == "bool":
            if ch in (ord(" "), curses.KEY_ENTER, 10, 13):
                cfg[key] = not bool(cfg.get(key, False))
                if key == "save_password" and not cfg.get("save_password"):
                    cfg["password"] = ""
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
                val = str(cfg.get(key, ""))
                cfg[key] = val[:-1]
                save_config(cfg)
            continue
        if 32 <= ch <= 126:
            if ftype == "password":
                password += chr(ch)
            else:
                val = str(cfg.get(key, ""))
                cfg[key] = val + chr(ch)
                save_config(cfg)
            continue


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
    txt_win.addstr(0, 0, initial_sql)
    txt_win.refresh()
    box = curses.textpad.Textbox(txt_win, insert_mode=True)

    state = {"cancel": False}

    def validator(ch):
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
    safe_use_default_colors()
    screen_splash(stdscr)
    cfg = load_config()
    current_db = cfg.get("database", "")
    while True:
        cfg, password = screen_connect(stdscr, cfg)
        if cfg is None:
            return
        stdscr.clear()
        draw_header(stdscr, f"Jupyter-SSMS {VERSION} - Conectando...")
        stdscr.refresh()
        conn, err = connect_db(cfg, password)
        if err:
            screen_message(stdscr, "Erro", err)
            continue
        current_db = cfg.get("database", "")
        while True:
            choice = screen_menu(
                stdscr,
                "Menu",
                [
                    "Databases",
                    "Tabelas",
                    "Query",
                    "CRUD (template)",
                    "Desconectar",
                    "Sair",
                ],
            )
            if choice is None:
                continue
            if choice == "Databases":
                current_db = screen_databases(stdscr, conn, current_db)
            elif choice == "Tabelas":
                sql = screen_tables(stdscr, conn)
                if sql:
                    screen_query(stdscr, conn, sql)
            elif choice == "Query":
                screen_query(stdscr, conn, "")
            elif choice == "CRUD (template)":
                sql = screen_tables(stdscr, conn)
                if sql:
                    screen_query(stdscr, conn, sql)
            elif choice == "Desconectar":
                try:
                    conn.close()
                except Exception:
                    pass
                break
            elif choice == "Sair":
                try:
                    conn.close()
                except Exception:
                    pass
                return


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
