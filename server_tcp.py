import socket

HOST = "0.0.0.0"
PORT = 5000

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen(5)

    print(f"Servidor TCP escuchando en {HOST}:{PORT}")

    while True:
        conn, addr = server.accept()
        print(f"Cliente conectado desde {addr}")
        conn.close()

if __name__ == "__main__":
    main()
