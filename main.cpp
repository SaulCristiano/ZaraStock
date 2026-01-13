#include <WiFi.h>

// --- WIFI ---
const char* ssid     = "WifiRED";
const char* password = "ContraseñaRED";

// --- SERVIDOR TCP (tu PC) ---
const char* serverIP = "192.168.1.84";
const uint16_t serverPort = 5000;

WiFiClient client;

// ------------------------------
//  ESTRUCTURA ETIQUETA 
// ------------------------------
struct Etiqueta {
  bool configurada = false;
  int id = -1;
  String temporada = "";
  String tipo = "";
  String ubicacion = "";
  float precio = 0.0f;
};

Etiqueta etiqueta; // etiqueta actual (arranca vacía)

// ------------------------------
//  CONEXIÓN WIFI / TCP
// ------------------------------
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
    return true;
  } else {
    Serial.println("[WIFI] ❌ No se pudo conectar (timeout)");
    return false;
  }
}

bool conectarServidor(unsigned long timeoutMs = 5000) {
  Serial.println("\n[TCP] Conectando al servidor...");
  Serial.print("[TCP] Destino: ");
  Serial.print(serverIP);
  Serial.print(":");
  Serial.println(serverPort);

  client.stop();

  unsigned long start = millis();
  while (!client.connect(serverIP, serverPort) && (millis() - start) < timeoutMs) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();

  if (client.connected()) {
    Serial.println("[TCP] ✅ Conectado al servidor (conexión persistente)");
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
  Serial.println("[ETIQUETA] Estado inicial: VACÍA (sin configurar)");

  if (conectarWiFi()) {
    conectarServidor();
  }
}

void loop() {
  // Si se cae WiFi, reintenta
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n[WIFI] ⚠️ WiFi desconectado. Reintentando...");
    if (conectarWiFi()) {
      conectarServidor();
    }
    delay(1000);
    return;
  }

  // Si se cae TCP, reintenta
  if (!client.connected()) {
    Serial.println("\n[TCP] ⚠️ Servidor desconectado. Reintentando...");
    conectarServidor();
    delay(2000);
    return;
  }

  // Conexión OK
  delay(1000);
}
