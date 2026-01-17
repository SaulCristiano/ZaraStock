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
ping_cv = threading.Condition(ping_lock)
ping_responses = {}  # rid -> dict(cid -> dict(status, data, raw))

# Para esperar ACK de SET (cid -> {"id": int, "ok": bool, "ts": float})
ack_lock = threading.Lock()
ack_cv = threading.Condition(ack_lock)
ack_responses = {}  # cid -> last_ack_id

# Espera UID desde lector NFC (rid -> {"cid":int, "uid":str, "role":str})
uid_lock = threading.Lock()
uid_cv = threading.Condition(uid_lock)
uid_responses = {}  # rid -> dict


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


# ------------------ COLOR Segun ubicación ------------------

def color_ubicacion(ubi: str) -> str:
    u = (ubi or "").strip().lower()
    if  u == "almacén":
        return c(ubi, "34")  # azul
    if u == "tienda":
        return c(ubi, "35")  # magenta
    if u == "vendido":
        return c(ubi, "32")  # verde (si algún día lo envías)
    return ubi


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

    # ROLE NFC BOX / ROLE NFC DOOR
    if msg.startswith("ROLE "):
        parts = msg.split()
        # ROLE NFC BOX
        if len(parts) >= 3 and parts[1] == "NFC":
            nfc_role = parts[2].upper()
            with clients_lock:
                if client_id in clients:
                    clients[client_id]["role"] = "NFC"
                    clients[client_id]["nfc_role"] = nfc_role
            print(f"[{now_ts()}] [i] Cliente {client_id} registrado como NFC {nfc_role}")
        return

    # UID <rid> <HEXUID>
    if msg.startswith("UID "):
        parts = msg.split()
        if len(parts) >= 3:
            rid = parts[1].strip()
            hexuid = parts[2].strip().upper()
            with uid_cv:
                uid_responses[rid] = {"cid": client_id, "uid": hexuid}
                uid_cv.notify_all()
        return


    # ----- PING/PONG -----
    if msg.startswith("PONG "):
        parts = msg.split(" ", 3)  # PONG rid STATUS [rest]
        if len(parts) >= 3:
            rid = parts[1].strip()
            status = parts[2].strip()
            rest = parts[3].strip() if len(parts) == 4 else ""

            data_json = None
            if status == "DATA" and rest:
                data_json = rest

            with ping_cv:
                ping_responses.setdefault(rid, {})
                ping_responses[rid][client_id] = {
                    "status": status,
                    "data": data_json,
                    "raw": msg
                }
                ping_cv.notify_all()
        return

    # ----- ACK -----
    if msg.startswith("ACK"):
        # Esperado: "ACK ID=3"
        ack_id = None
        try:
            i = msg.find("ID=")
            if i != -1:
                ack_id = int(msg[i+3:].strip())
        except:
            ack_id = None

        with ack_cv:
            ack_responses[client_id] = ack_id
            ack_cv.notify_all()
        return


    # ----- RESET -----
    if msg.startswith("RESET"):
        return

    # ----- Movimiento -----
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
                "configured": False,  # ya NO es fuente de verdad
                "last_seen": time.time(),
                "buffer": b"",
                "tag_data": None,
                "role": "TAG", # Por defecto NFC por el contrario
                "nfc_role": None # Caja / Puerta
            }
        t = threading.Thread(target=handle_client, args=(cid,), daemon=True)
        t.start()


# ------------------ POLLING GLOBAL (la clave del refactor) ------------------

def poll_tags(timeout_s: float = 3.0):
    """
    Hace un 'broadcast lógico' PING a todos los conectados y devuelve:
      - snapshot: lista de (cid, info) en el momento del ping
      - resp: dict cid -> {status, data, raw} con respuestas recibidas
      - rid: request id
    """
    with clients_lock:
        snapshot = list(clients.items())

    if not snapshot:
        return [], {}, None

    rid = str(int(time.time() * 1000))
    expected = {cid for cid, _ in snapshot}

    with ping_cv:
        ping_responses[rid] = {}

    # enviar PING
    for cid, info in snapshot:
        try:
            send_line(info["conn"], f"PING {rid}")
        except:
            pass

    deadline = time.time() + timeout_s
    with ping_cv:
        while True:
            got = set(ping_responses.get(rid, {}).keys())
            if got >= expected:
                break

            remaining = deadline - time.time()
            if remaining <= 0:
                break

            ping_cv.wait(timeout=remaining)

        resp = ping_responses.get(rid, {})
        ping_responses.pop(rid, None)

    return snapshot, resp, rid

# --------- Leer NFC de CAJA -----
def get_nfc_reader(role_name: str):
    role_name = role_name.upper()
    with clients_lock:
        for cid, info in clients.items():
            if info.get("role") == "NFC" and info.get("nfc_role") == role_name:
                return cid, info["conn"], info["addr"]
    return None, None, None

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

    snapshot, resp, rid = poll_tags(timeout_s=3.0)

    clear()
    print(c("=== ALTA / CONFIGURAR ETIQUETA (solo VACÍAS) ===", "36"))
    print(f"RID: {rid}   Hora: {now_ts()}\n")

    if not snapshot:
        print("No hay etiquetas conectadas.")
        return

    # Filtrar solo las EMPTY (en tiempo real)
    empty = []
    for cid, info in snapshot:
        if cid in resp and resp[cid]["status"] == "EMPTY":
            a = info["addr"]
            empty.append([str(cid), f"{a[0]}:{a[1]}", c("VACÍA", "33")])

    if not empty:
        print("No hay etiquetas VACÍAS ahora mismo (según PING).")
        return

    # Tabla pequeña y limpia
    headers = ["CID", "IP:PUERTO", "ESTADO"]
    print(_table(empty, headers))

    # Selección
    empty_cids = {int(r[0]) for r in empty}
    while True:
        try:
            cid = int(input("\nElige el CID al que asignar esta etiqueta: ").strip())
        except:
            print("Introduce un número válido.")
            continue
        if cid in empty_cids:
            break
        print("Ese CID no está en la lista de VACÍAS.")

    temporada = input_choice("Temporada (Invierno/Verano): ", {"Invierno", "Verano"})
    tipo = input_choice("Tipo (Gorra/Camiseta/Pantalones/Calcetines): ",
                        {"Gorra", "Camiseta", "Pantalones", "Calcetines"})
    # ubicacion = input_choice("Ubicación inicial (almacén/tienda): ", {"almacén", "tienda"})
    precio = input_float("Precio (float): ")

    clear()
    print(c("=== ALTA / CONFIGURAR ETIQUETA (solo VACÍAS) ===", "36"))
    print(f"RID: {rid}   Hora: {now_ts()}\n")
    print("Acerque su etiqueta NFC al lector de CAJA para asignar UID...\n")

    nfc_cid, nfc_conn, _ = get_nfc_reader("BOX")
    if not nfc_conn:
        print("❌ No hay lector NFC BOX conectado.")
        return

    read_rid = str(int(time.time() * 1000))

    # limpiar posible residuo
    with uid_cv:
        uid_responses.pop(read_rid, None)

    # pedir UID
    try:
        send_line(nfc_conn, f"READUID {read_rid}")
    except Exception as e:
        print("❌ No se pudo pedir UID al lector BOX:", e)
        return

    # esperar UID
    uid_hex = None
    deadline = time.time() + 10.0  # 10s para acercar el tag
    with uid_cv:
        while True:
            got = uid_responses.get(read_rid)
            if got:
                uid_hex = got["uid"]
                uid_responses.pop(read_rid, None)
                break
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            uid_cv.wait(timeout=remaining)

    if not uid_hex:
        print("⚠️ No se detectó UID a tiempo.")
        return

    print(f"✅ UID capturado: {uid_hex}\n")

    with next_id_lock:
        tag_id = next_tag_id
        next_tag_id += 1

    tag = {
        "ID": tag_id,
        "Temporada": temporada,
        "Tipo": tipo,
        "Ubicacion": "Almacén", # ubicacion
        "Precio": precio,
        "UID": uid_hex
    }

    with clients_lock:
        if cid not in clients:
            print("Esa etiqueta se ha desconectado justo ahora.")
            return
        conn = clients[cid]["conn"]

    payload = json.dumps(tag, ensure_ascii=False)
    cmd = f"SET {payload}"

    try:
        send_line(conn, cmd)

        # Esperar ACK del mismo CID y mismo ID
        ok = False
        deadline = time.time() + 2.0  # timeout 2s (ajústalo)

        with ack_cv:
            while True:
                got = ack_responses.get(cid, None)
                if got == tag_id:
                    ok = True
                    break

                remaining = deadline - time.time()
                if remaining <= 0:
                    break

                ack_cv.wait(timeout=remaining)

        if ok:
            with clients_lock:
                if cid in clients:
                    clients[cid]["configured"] = True
                    clients[cid]["tag_data"] = tag
            print(f"\n✅ Etiqueta confirmada por ACK: CID [{cid}] -> ID={tag_id}")
        else:
            print(f"\n⚠️ SET enviado pero NO llegó ACK a tiempo (CID [{cid}] -> ID={tag_id})")

    except Exception as e:
        print("\n❌ No se pudo enviar al cliente:", e)



# ------------------ Menú: ver stock (PING) ------------------

def ver_stock_ping(timeout_s=3.0):
    snapshot, resp, rid = poll_tags(timeout_s=timeout_s)
    if not snapshot:
        print("No hay etiquetas conectadas.")
        return

    headers = ["CID", "IP:PUERTO", "ESTADO", "ID", "TEMP", "TIPO", "UBIC", "PRECIO"]
    rows = []

    for cid, info in snapshot:
        a = info["addr"]
        ipport = f"{a[0]}:{a[1]}"

        with clients_lock:
            role = clients.get(cid, {}).get("role", "TAG")
            nfc_role = clients.get(cid, {}).get("nfc_role", "")
        
        if role == "NFC":
            rows.append([str(cid), ipport, c("NFC", "36"), "-", "-", "-", c(nfc_role, "35"), "-"])
            continue



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
                    #str(d.get("Ubicacion", "")),
                    color_ubicacion(str(d.get("Ubicacion", ""))),
                    f'{float(d.get("Precio", 0.0)):.2f}'
                ])
            except:
                rows.append([str(cid), ipport, c("MAL JSON", "31"), "-", "-", "-", "-", "-"])
        else:
            rows.append([str(cid), ipport, c(status, "35"), "-", "-", "-", "-", "-"])

    clear()
    print(c("=== STOCK EN VIVO (PING A TODAS LAS ETIQUETAS) ===", "36"))
    print(f"RID: {rid}   Timeout: {timeout_s:.1f}s   Hora: {now_ts()}\n")
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
                table_rows = [[r.get(h, "") for h in headers] for r in rows]
                print(_table(table_rows, headers))

        elif op == "2":
            headers, rows = read_last_rows(VEN_CSV, limit=25)
            clear()
            print(c("=== VENTAS (últimos 25) ===", "36"))
            if not rows:
                print("No hay datos aún (ventas.csv no existe o está vacío).")
            else:
                table_rows = [[r.get(h, "") for h in headers] for r in rows]
                print(_table(table_rows, headers))

        elif op == "3":
            headers, rows = read_last_rows(VEN_CSV, limit=100000)
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
        print("1) Agregar una etiqueta (usa PING y muestra solo VACÍAS)")
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
