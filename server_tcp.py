import socket
import json
import threading
import time

HOST = "0.0.0.0"
PORT = 5000

clients_lock = threading.Lock()
clients = {}  # cid -> {"conn": conn, "addr": addr}

cid_lock = threading.Lock()
next_cid = 1


def send_line(conn: socket.socket, text: str):
    conn.sendall((text + "\n").encode("utf-8"))


def rx_thread(cid: int):
    """Recibe líneas del cliente y las imprime. Si se desconecta, lo elimina."""
    with clients_lock:
        conn = clients[cid]["conn"]
        addr = clients[cid]["addr"]

    buf = b""
    try:
        while True:
            data = conn.recv(1024)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                msg = line.decode("utf-8", errors="ignore").strip()
                if msg:
                    print(f"\n[CID {cid} | {addr[0]}:{addr[1]}] {msg}")
    except Exception as e:
        print(f"\n[CID {cid}] Error RX: {e}")
    finally:
        try:
            conn.close()
        except:
            pass
        with clients_lock:
            clients.pop(cid, None)
        print(f"\n[CID {cid}] Cliente desconectado ({addr[0]}:{addr[1]})")


def acceptor_thread():
    global next_cid
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(20)

    print(f"Servidor TCP escuchando en {HOST}:{PORT}")
    print("Aceptando múltiples conexiones...\n")

    while True:
        conn, addr = server.accept()

        with cid_lock:
            cid = next_cid
            next_cid += 1

        with clients_lock:
            clients[cid] = {"conn": conn, "addr": addr}

        print(f"[+] Conectado CID {cid} desde {addr[0]}:{addr[1]}")

        t = threading.Thread(target=rx_thread, args=(cid,), daemon=True)
        t.start()


def pedir_float(prompt):
    while True:
        s = input(prompt).strip().replace(",", ".")
        try:
            return float(s)
        except:
            print("Número inválido. Ejemplo: 19.99")


def listar_clientes():
    with clients_lock:
        if not clients:
            print("No hay clientes conectados.")
            return
        print("\nClientes conectados:")
        for cid, info in clients.items():
            a = info["addr"]
            print(f"  CID {cid} -> {a[0]}:{a[1]}")


def elegir_cid():
    while True:
        listar_clientes()
        s = input("\nElige CID: ").strip()
        try:
            cid = int(s)
        except:
            print("CID inválido (debe ser número).")
            continue

        with clients_lock:
            if cid in clients:
                return cid

        print("Ese CID no existe (quizá se desconectó).")


def configurar_etiqueta():
    with clients_lock:
        hay = bool(clients)
    if not hay:
        print("No hay ninguna etiqueta conectada.")
        return

    cid = elegir_cid()

    print("\n--- CONFIGURAR ETIQUETA ---")
    try:
        id_ = int(input("ID (int): ").strip())
    except:
        print("ID inválido.")
        return

    temporada = input("Temporada (Invierno/Verano): ").strip()
    tipo = input("Tipo (Gorra/Camiseta/Pantalones/Calcetines): ").strip()
    ubicacion = input("Ubicacion (almacén/tienda): ").strip()
    precio = pedir_float("Precio (float): ")

    tag = {
        "ID": id_,
        "Temporada": temporada,
        "Tipo": tipo,
        "Ubicacion": ubicacion,
        "Precio": precio
    }

    payload = json.dumps(tag, ensure_ascii=False)
    cmd = f"SET {payload}"

    with clients_lock:
        conn = clients.get(cid, {}).get("conn")
        addr = clients.get(cid, {}).get("addr")

    if conn is None:
        print("Ese CID ya no está conectado.")
        return

    try:
        send_line(conn, cmd)
        print(f"Enviado a CID {cid} ({addr[0]}:{addr[1]}): {cmd}")
        print("Si el dispositivo responde, verás ACK/NACK en consola.")
    except Exception as e:
        print("No se pudo enviar:", e)


def menu_loop():
    while True:
        print("\n--- MENÚ SERVIDOR ---")
        print("1) Configurar etiqueta (enviar SET a un CID)")
        print("2) Ver clientes conectados")
        print("0) Salir")
        op = input("Opción: ").strip()

        if op == "1":
            configurar_etiqueta()
        elif op == "2":
            listar_clientes()
        elif op == "0":
            print("Saliendo.")
            break
        else:
            print("Opción no válida.")


def main():
    t = threading.Thread(target=acceptor_thread, daemon=True)
    t.start()

    # Espera pequeñita para que salga el banner antes del menú (opcional)
    time.sleep(0.1)
    menu_loop()


if __name__ == "__main__":
    main()
