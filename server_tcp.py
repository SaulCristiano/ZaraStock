import socket
import json
import threading

HOST = "0.0.0.0"
PORT = 5000

client_lock = threading.Lock()
client_conn = None
client_addr = None


def send_line(conn: socket.socket, text: str):
    conn.sendall((text + "\n").encode("utf-8"))


def rx_thread(conn: socket.socket, addr):
    """Lee líneas del cliente y las imprime (ACK, etc.)."""
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
                    print(f"\n[RX {addr}] {msg}")
    except Exception as e:
        print(f"\n[RX] Error: {e}")
    finally:
        with client_lock:
            global client_conn, client_addr
            client_conn = None
            client_addr = None
        try:
            conn.close()
        except:
            pass
        print("\nCliente desconectado.")


def accept_one_client():
    global client_conn, client_addr

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)
        print(f"Servidor TCP escuchando en {HOST}:{PORT}")
        print("Esperando a que se conecte una etiqueta...\n")

        conn, addr = server.accept()
        with client_lock:
            client_conn = conn
            client_addr = addr

        print(f"Cliente conectado desde {addr}")

        t = threading.Thread(target=rx_thread, args=(conn, addr), daemon=True)
        t.start()

        # Mantener el hilo principal vivo con el menú
        menu_loop()


def pedir_float(prompt):
    while True:
        s = input(prompt).strip().replace(",", ".")
        try:
            return float(s)
        except:
            print("Número inválido. Ejemplo: 19.99")


def configurar_etiqueta():
    with client_lock:
        conn = client_conn
        addr = client_addr

    if conn is None:
        print("No hay ninguna etiqueta conectada.")
        return

    print("\n--- CONFIGURAR ETIQUETA ---")
    # Campos manuales (como en tu versión original)
    id_ = int(input("ID (int): ").strip())
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

    try:
        send_line(conn, cmd)
        print(f"Enviado a {addr}: {cmd}")
        print("Esperando ACK en consola (si llega)...")
    except Exception as e:
        print("No se pudo enviar:", e)


def menu_loop():
    while True:
        print("\n--- MENÚ SERVIDOR ---")
        print("1) Configurar etiqueta (enviar SET)")
        print("0) Salir")
        op = input("Opción: ").strip()

        if op == "1":
            configurar_etiqueta()
        elif op == "0":
            print("Saliendo (cerrando servidor).")
            with client_lock:
                conn = client_conn
            try:
                if conn:
                    conn.close()
            except:
                pass
            break
        else:
            print("Opción no válida.")


if __name__ == "__main__":
    accept_one_client()
