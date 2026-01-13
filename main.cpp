#include <WiFi.h>

// --- WIFI ---
const char* ssid     = "NombreRED";
const char* password = "ContraseñaRED";

// --- SERVIDOR TCP (tu PC)  ---
const char* serverIP = "192.168.1.84";
const uint16_t serverPort = 5000;

WiFiClient client;

bool conectarWiFi(unsigned long timeoutMs = 20000) {
  Serial.println("\n[WIFI] Conectando...");
  Serial.print("[WIFI] SSID: ");
  Serial.println(ssid);

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < timeoutMs) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("[WIFI] ✅ Conectado");
    Serial.print("[WIFI] IP: ");
    Serial.println(WiFi.localIP());
    Serial.print("[WIFI] RSSI: ");
    Serial.println(WiFi.RSSI());
    return true;
  } else {
    Serial.println("[WIFI] ❌ No se pudo conectar (timeout)");
    Serial.print("[WIFI] Estado: ");
    Serial.println((int)WiFi.status());
    return false;
  }
}

bool conectarServidor(unsigned long timeoutMs = 5000) {
  Serial.println("\n[TCP] Conectando al servidor...");
  Serial.print("[TCP] Destino: ");
  Serial.print(serverIP);
  Serial.print(":");
  Serial.println(serverPort);

  client.stop(); // por si había algo viejo

  unsigned long start = millis();
  while (!client.connect(serverIP, serverPort) && (millis() - start) < timeoutMs) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();

  if (client.connected()) {
    Serial.println("[TCP] ✅ Conectado al servidor");
    return true;
  } else {
    Serial.println("[TCP] ❌ No se pudo conectar al servidor (timeout)");
    return false;
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);

  Serial.println("\n=== ESP32 WiFi + TCP (MINIMO) ===");

  // 1) WiFi
  if (!conectarWiFi()) {
    Serial.println("[BOOT] Reintentará en loop.");
    return;
  }

  // 2) TCP
  conectarServidor();
}

void loop() {
  // Si se cae el WiFi, reintenta
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n[WIFI] ⚠️ WiFi desconectado. Reintentando...");
    conectarWiFi();
    // tras recuperar WiFi, intentamos servidor
    if (WiFi.status() == WL_CONNECTED) {
      conectarServidor();
    }
    delay(1000);
    return;
  }

  // Si se cae TCP, reintenta cada 2s
  if (!client.connected()) {
    Serial.println("\n[TCP] ⚠️ Servidor desconectado. Reintentando...");
    conectarServidor();
    delay(2000);
    return;
  }

  // Mantener vivo.
  delay(1000);
}
