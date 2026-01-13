#include <WiFi.h>

// --- WIFI ---
const char* ssid     = "PILOLO_DE_ARRIBA";
const char* password = "AAAAAAAAAA1111111111";

// --- SERVIDOR TCP ---
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

Etiqueta etiqueta;

// ------------------------------
//  Utils TCP
// ------------------------------
void enviarLinea(const String& line) {
  if (client.connected()) {
    client.print(line + "\n");
  }
}

// ------------------------------
//  Conexión WiFi / TCP
// ------------------------------
bool conectarWiFi(unsigned long timeoutMs = 20000) {
  Serial.println("\n[WIFI] Conectando...");
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
  }
  Serial.println("[WIFI] ❌ No se pudo conectar (timeout)");
  return false;
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
    Serial.println("[TCP] ✅ Conectado al servidor");
    return true;
  }
  Serial.println("[TCP] ❌ No se pudo conectar (timeout)");
  return false;
}

// ------------------------------
//  Parseo JSON simple (campos fijos)
// ------------------------------
String extraerStringJSON(const String& json, const String& key) {
  String needle = "\"" + key + "\"";
  int k = json.indexOf(needle);
  if (k < 0) return "";

  int colon = json.indexOf(':', k);
  if (colon < 0) return "";

  int firstQuote = json.indexOf('\"', colon + 1);
  if (firstQuote < 0) return "";

  int secondQuote = json.indexOf('\"', firstQuote + 1);
  if (secondQuote < 0) return "";

  return json.substring(firstQuote + 1, secondQuote);
}

int extraerIntJSON(const String& json, const String& key) {
  String needle = "\"" + key + "\"";
  int k = json.indexOf(needle);
  if (k < 0) return -1;

  int colon = json.indexOf(':', k);
  if (colon < 0) return -1;

  int start = colon + 1;
  while (start < (int)json.length() && json[start] == ' ') start++;

  int endComma = json.indexOf(',', start);
  int endBrace = json.indexOf('}', start);
  int end = (endComma >= 0) ? endComma : endBrace;
  if (end < 0) end = json.length();

  String num = json.substring(start, end);
  num.trim();
  return num.toInt();
}

float extraerFloatJSON(const String& json, const String& key) {
  String needle = "\"" + key + "\"";
  int k = json.indexOf(needle);
  if (k < 0) return 0.0f;

  int colon = json.indexOf(':', k);
  if (colon < 0) return 0.0f;

  int start = colon + 1;
  while (start < (int)json.length() && json[start] == ' ') start++;

  int endComma = json.indexOf(',', start);
  int endBrace = json.indexOf('}', start);
  int end = (endComma >= 0) ? endComma : endBrace;
  if (end < 0) end = json.length();

  String num = json.substring(start, end);
  num.trim();
  num.replace(",", ".");
  return num.toFloat();
}

// ------------------------------
//  Aplicar SET
// ------------------------------
void aplicarSET(const String& json) {
  etiqueta.id        = extraerIntJSON(json, "ID");
  etiqueta.temporada = extraerStringJSON(json, "Temporada");
  etiqueta.tipo      = extraerStringJSON(json, "Tipo");
  etiqueta.ubicacion = extraerStringJSON(json, "Ubicacion");
  etiqueta.precio    = extraerFloatJSON(json, "Precio");

  etiqueta.configurada =
    (etiqueta.id >= 0 &&
     etiqueta.temporada.length() > 0 &&
     etiqueta.tipo.length() > 0 &&
     etiqueta.ubicacion.length() > 0);

  Serial.println("\n[SET] Recibido. Estado etiqueta:");
  Serial.print("  ID: "); Serial.println(etiqueta.id);
  Serial.print("  Temporada: "); Serial.println(etiqueta.temporada);
  Serial.print("  Tipo: "); Serial.println(etiqueta.tipo);
  Serial.print("  Ubicacion: "); Serial.println(etiqueta.ubicacion);
  Serial.print("  Precio: "); Serial.println(etiqueta.precio, 2);

  if (etiqueta.configurada) {
    enviarLinea("ACK ID=" + String(etiqueta.id));
  } else {
    enviarLinea("NACK");
  }
}

// ------------------------------
//  Lectura de líneas del servidor
// ------------------------------
void procesarLineaServidor(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line.startsWith("SET ")) {
    String json = line.substring(4);
    json.trim();
    aplicarSET(json);
    return;
  }

  Serial.print("[RX] ");
  Serial.println(line);
}

void leerServidor() {
  while (client.connected() && client.available()) {
    String line = client.readStringUntil('\n');
    procesarLineaServidor(line);
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);

  Serial.println("\n=== ESP32 WiFi + TCP + SET (BASICO) ===");
  Serial.println("[ETIQUETA] Inicial: VACÍA");

  if (conectarWiFi()) {
    conectarServidor();
  }
}

void loop() {
  // Reintentos WiFi
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n[WIFI] ⚠️ Desconectado. Reintentando...");
    if (conectarWiFi()) conectarServidor();
    delay(1000);
    return;
  }

  // Reintentos TCP
  if (!client.connected()) {
    Serial.println("\n[TCP] ⚠️ Desconectado. Reintentando...");
    conectarServidor();
    delay(1500);
    return;
  }

  // Leer comandos del servidor
  leerServidor();
  delay(50);
}
