import socket
import threading
import json
import time
import os
import re
import csv
from datetime import datetime

HOST = "0.0.0.0"
PORT = 5000

clients_lock = threading.Lock()
clients = {}  # cid -> dict(conn, addr, configured, last_seen, buffer, tag_data)

next_id_lock = threading.Lock()
next_tag_id = 1

# Para recopilar respuestas al PING (rid -> {cid: payload})
ping_lock = threading.Lock()
ping_responses = {}  # rid -> dict(cid -> dict(status, data_json_or_none, raw))


# ------------------ Utilidades ------------------

def now_ts():
    return time.strftime("%H:%M:%S")

def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def c(txt, code):
    return f"\x1b[{code}m{txt}\x1b[0m"

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def send_line(conn: socket.socket, text: str):
    conn.sendall((text + "\n").encode("utf-8", errors="ignore"))


# ------------------ CSV Logging ------------------

MOV_CSV = "movimientos.csv"
VEN_CSV = "ventas.csv"

def append_csv(filename: str, headers: list[str], row: dict):
    file_exists = os.path.exists(filename)
    with open(filename, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        if not file_exists:
            w.writeheader()
        w.writerow(row)

def read_last_rows(filename: str, limit: int = 20):
    if not os.path.exists(filename):
        return [], []
    with open(filename, "r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        rows = list(r)
        headers = r.fieldnames or []
    return headers, rows[-limit:]


# ------------------ Tabla bonita (ANSI-safe) ------------------

def normalize_rows(rows, cols, fill="-"):
    out = []
    for r in rows:
        r = list(r)
        if len(r) < cols:
            r += [fill] * (cols - len(r))
        elif len(r) > cols:
            r = r[:cols]
        out.append(r)
    return out

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", str(s))

def visible_len(s: str) -> int:
    return len(strip_ansi(s))

def pad_visible(s: str, width: int) -> str:
    s = str(s)
    return s + (" " * max(0, width - visible_len(s)))

def _table(rows, headers):
    cols = len(headers)
    rows = normalize_rows(rows, cols, fill="-")

    widths = [len(h) for h in headers]
    for r in rows:
        for i in range(cols):
            widths[i] = max(widths[i], visible_len(r[i]))

    def line(sep="-", cross="+"):
        return cross + cross.join(sep * (w + 2) for w in widths) + cross

    out = []
    out.append(line("-"))
    out.append("| " + " | ".join(headers[i].ljust(widths[i]) for i in range(cols)) + " |")
    out.append(line("="))
    for r in rows:
        out.append("| " + " | ".join(pad_visible(r[i], widths[i]) for i in range(cols)) + " |")
    out.append(line("-"))
    return "\n".join(out)


# ------------------ Networking ------------------

def handle_client(client_id: int):
    with clients_lock:
        conn = clients[client_id]["conn"]
        addr = clients[client_id]["addr"]

    print(f"[{now_ts()}] [+] Cliente conectado: {addr} (client_id={client_id})")

    try:
        send_line(conn, "Etiqueta conectada al servidor.")

        while True:
            data = conn.recv(1024)
            if not data:
                break

            with clients_lock:
                clients[client_id]["last_seen"] = time.time()
                clients[client_id]["buffer"] += data
                buf = clients[client_id]["buffer"]

            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                msg = line.decode("utf-8", errors="ignore").strip()
                if msg:
                    process_message(client_id, msg)

            with clients_lock:
                if client_id in clients:
                    clients[client_id]["buffer"] = buf

    except Exception as e:
        print(f"[{now_ts()}] [!] Error con {addr}: {e}")
    finally:
        try:
            conn.close()
        except:
            pass
        with clients_lock:
            if client_id in clients:
                del clients[client_id]
        print(f"[{now_ts()}] [-] Cliente desconectado: {addr} (client_id={client_id})")


def process_message(client_id: int, msg: str):
    with clients_lock:
        addr = clients[client_id]["addr"] if client_id in clients else ("?", 0)

    print(f"[{now_ts()}] [{addr}] {msg}")

    # ----- PING/PONG para ver stock -----
    if msg.startswith("PONG "):
        parts = msg.split(" ", 3)  # PONG rid STATUS [rest]
        if len(parts) >= 3:
            rid = parts[1].strip()
            status = parts[2].strip()
            rest = parts[3].strip() if len(parts) == 4 else ""

            data_json = None
            if status == "DATA" and rest:
                data_json = rest

            with ping_lock:
                if rid not in ping_responses:
                    ping_responses[rid] = {}
                ping_responses[rid][client_id] = {
                    "status": status,
                    "data": data_json,
                    "raw": msg
                }
        return

    # ----- Alta (ACK) -----
    if msg.startswith("ACK"):
        return

    # ----- Reset manual -----
    if msg.startswith("RESET"):
        # No hace falta guardar; el broadcast ya lo verá.
        return

    # ----- Movimiento -----
    # Formato: MOVE {json}
    if msg.startswith("MOVE "):
        payload = msg[5:].strip()
        try:
            d = json.loads(payload)
            append_csv(
                MOV_CSV,
                headers=["timestamp", "ip", "id", "temporada", "tipo", "from", "to", "precio"],
                row={
                    "timestamp": now_iso(),
                    "ip": addr[0],
                    "id": d.get("ID", ""),
                    "temporada": d.get("Temporada", ""),
                    "tipo": d.get("Tipo", ""),
                    "from": d.get("From", ""),
                    "to": d.get("To", ""),
                    "precio": d.get("Precio", ""),
                }
            )
        except Exception as e:
            print(f"[{now_ts()}] [!] MOVE mal formado: {e}")
        return

    # ----- Venta -----
    # Formato: SOLD {json}
    if msg.startswith("SOLD "):
        payload = msg[5:].strip()
        try:
            d = json.loads(payload)
            append_csv(
                VEN_CSV,
                headers=["timestamp", "ip", "id", "temporada", "tipo", "precio"],
                row={
                    "timestamp": now_iso(),
                    "ip": addr[0],
                    "id": d.get("ID", ""),
                    "temporada": d.get("Temporada", ""),
                    "tipo": d.get("Tipo", ""),
                    "precio": d.get("Precio", ""),
                }
            )
        except Exception as e:
            print(f"[{now_ts()}] [!] SOLD mal formado: {e}")
        return

    # Otros mensajes
    return


def acceptor_thread():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(20)
    print(f"[{now_ts()}] Servidor TCP escuchando en {HOST}:{PORT}")

    client_id_counter = 1
    while True:
        conn, addr = s.accept()
        with clients_lock:
            cid = client_id_counter
            client_id_counter += 1
            clients[cid] = {
                "conn": conn,
                "addr": addr,
                "configured": False,
                "last_seen": time.time(),
                "buffer": b"",
                "tag_data": None,
            }
        t = threading.Thread(target=handle_client, args=(cid,), daemon=True)
        t.start()


# ------------------ Menú: alta ------------------

def input_choice(prompt, valid):
    while True:
        v = input(prompt).strip()
        if v in valid:
            return v
        print("Valor inválido. Opciones:", ", ".join(valid))

def input_float(prompt):
    while True:
        s = input(prompt).strip().replace(",", ".")
        try:
            return float(s)
        except:
            print("Precio inválido. Ejemplo: 19.99")

def agregar_etiqueta():
    global next_tag_id

    with clients_lock:
        vacios = [cid for cid, info in clients.items() if not info["configured"]]

    if not vacios:
        print("No hay etiquetas VACÍAS conectadas. Enciende una y conéctala primero.")
        return

    print("\nEtiquetas vacías disponibles:")
    with clients_lock:
        for cid in vacios:
            a = clients[cid]["addr"]
            print(f"  [{cid}] {a[0]}:{a[1]}")

    while True:
        try:
            cid = int(input("Elige el client_id al que asignar esta etiqueta: ").strip())
        except:
            print("Introduce un número válido.")
            continue
        with clients_lock:
            if cid in clients and not clients[cid]["configured"]:
                break
        print("Ese client_id no existe o ya está configurado.")

    temporada = input_choice("Temporada (Invierno/Verano): ", {"Invierno", "Verano"})
    tipo = input_choice("Tipo (Gorra/Camiseta/Pantalones/Calcetines): ",
                        {"Gorra", "Camiseta", "Pantalones", "Calcetines"})
    ubicacion = input_choice("Ubicación inicial (almacén/tienda): ", {"almacén", "tienda"})
    precio = input_float("Precio (float): ")

    with next_id_lock:
        tag_id = next_tag_id
        next_tag_id += 1

    tag = {
        "ID": tag_id,
        "Temporada": temporada,
        "Tipo": tipo,
        "Ubicacion": ubicacion,
        "Precio": precio
    }

    with clients_lock:
        conn = clients[cid]["conn"]

    payload = json.dumps(tag, ensure_ascii=False)
    cmd = f"SET {payload}"

    try:
        send_line(conn, cmd)
        with clients_lock:
            clients[cid]["configured"] = True
            clients[cid]["tag_data"] = tag
        print(f"✅ Etiqueta asignada al cliente [{cid}] -> ID={tag_id}")
    except Exception as e:
        print("❌ No se pudo enviar al cliente:", e)


# ------------------ Menú: ver stock (PING) ------------------

def ver_stock_ping(timeout_s=1.5):
    with clients_lock:
        snapshot = list(clients.items())

    if not snapshot:
        print("No hay etiquetas conectadas.")
        return

    rid = str(int(time.time() * 1000))
    with ping_lock:
        ping_responses[rid] = {}

    for cid, info in snapshot:
        try:
            send_line(info["conn"], f"PING {rid}")
        except:
            pass

    t0 = time.time()
    while time.time() - t0 < timeout_s:
        time.sleep(0.05)

    with ping_lock:
        resp = ping_responses.get(rid, {})
        del ping_responses[rid]

    headers = ["CID", "IP:PUERTO", "ESTADO", "ID", "TEMP", "TIPO", "UBIC", "PRECIO"]
    rows = []

    for cid, info in snapshot:
        a = info["addr"]
        ipport = f"{a[0]}:{a[1]}"

        if cid not in resp:
            rows.append([str(cid), ipport, c("NO RESP", "31"), "-", "-", "-", "-", "-"])
            continue

        status = resp[cid]["status"]

        if status == "EMPTY":
            rows.append([str(cid), ipport, c("VACÍA", "33"), "-", "-", "-", "-", "-"])
        elif status == "DATA":
            data_json = resp[cid]["data"] or "{}"
            try:
                d = json.loads(data_json)
                rows.append([
                    str(cid),
                    ipport,
                    c("OK", "32"),
                    str(d.get("ID", "")),
                    str(d.get("Temporada", "")),
                    str(d.get("Tipo", "")),
                    str(d.get("Ubicacion", "")),
                    f'{float(d.get("Precio", 0.0)):.2f}'
                ])
            except:
                rows.append([str(cid), ipport, c("MAL JSON", "31"), "-", "-", "-", "-", "-"])
        else:
            rows.append([str(cid), ipport, c(status, "35"), "-", "-", "-", "-", "-"])

    clear()
    print(c("=== STOCK EN VIVO (PING A TODAS LAS ETIQUETAS) ===", "36"))
    print(f"RID: {rid}   Respuestas en ~{timeout_s:.1f}s   Hora: {now_ts()}\n")
    print(_table(rows, headers))


# ------------------ Menú: consultar CSV ------------------

def consultar_csv():
    while True:
        print("\n--- CONSULTA DE REGISTROS ---")
        print("1) Ver movimientos.csv")
        print("2) Ver ventas.csv")
        print("3) Resumen de ganancias (ventas)")
        print("0) Volver")
        op = input("Opción: ").strip()

        if op == "1":
            headers, rows = read_last_rows(MOV_CSV, limit=25)
            clear()
            print(c("=== MOVIMIENTOS (últimos 25) ===", "36"))
            if not rows:
                print("No hay datos aún (movimientos.csv no existe o está vacío).")
            else:
                table_headers = headers
                table_rows = [[r.get(h, "") for h in table_headers] for r in rows]
                print(_table(table_rows, table_headers))

        elif op == "2":
            headers, rows = read_last_rows(VEN_CSV, limit=25)
            clear()
            print(c("=== VENTAS (últimos 25) ===", "36"))
            if not rows:
                print("No hay datos aún (ventas.csv no existe o está vacío).")
            else:
                table_headers = headers
                table_rows = [[r.get(h, "") for h in table_headers] for r in rows]
                print(_table(table_rows, table_headers))

        elif op == "3":
            headers, rows = read_last_rows(VEN_CSV, limit=10_000)
            total = 0.0
            for r in rows:
                try:
                    total += float(str(r.get("precio", "0")).replace(",", "."))
                except:
                    pass
            clear()
            print(c("=== RESUMEN DE GANANCIAS ===", "36"))
            print(f"Ventas registradas: {len(rows)}")
            print(f"Total (€): {total:.2f}")

        elif op == "0":
            return
        else:
            print("Opción no válida.")


# ------------------ Menú principal ------------------

def menu_loop():
    while True:
        print("\n--- MENÚ SERVIDOR ---")
        print("1) Agregar una etiqueta (configurar NodeMCU conectado)")
        print("2) Ver stock (PING a todas las etiquetas)")
        print("3) Consultar registros (CSV)")
        print("0) Salir")
        op = input("Opción: ").strip()

        if op == "1":
            agregar_etiqueta()
        elif op == "2":
            ver_stock_ping()
        elif op == "3":
            consultar_csv()
        elif op == "0":
            print("Saliendo.")
            break
        else:
            print("Opción no válida.")


def main():
    t = threading.Thread(target=acceptor_thread, daemon=True)
    t.start()
    menu_loop()


if __name__ == "__main__":
    main()
