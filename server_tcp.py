import socket

HOST = "0.0.0.0"
PORT = 5000

def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)
        print(f"Servidor TCP escuchando en {HOST}:{PORT}")

        while True:
            conn, addr = server.accept()
            print(f"Cliente conectado desde {addr}")

            with conn:
                # Mantener conexión abierta hasta que el cliente cierre
                while True:
                    data = conn.recv(1024)
                    if not data:
                        break
                    # (Opcional) imprimir lo recibido
                    print(f"Recibido ({addr}): {data!r}")

            print(f"Cliente desconectado: {addr}")

if __name__ == "__main__":
    main()
