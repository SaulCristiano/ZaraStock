#include <WiFi.h>

// ------- CONFIG WIFI -------
const char* ssid = "PILOLO_DE_ARRIBA";
const char* password = "AAAAAAAAAA1111111111";

// ------- CONFIG SERVIDOR (TU PC) -------
const char* serverIP = "192.168.1.84";
const uint16_t serverPort = 5000;

WiFiClient client;

// --- PROTOTIPOS (para que el compilador conozca las funciones antes de usarlas) ---
String etiquetaAJson();
void responderPing(const String& rid);
void procesarLineaServidor(String line);


// ------- CONFIG BOTÓN (si lo quieres mantener) -------
const int buttonPin = 0;   // GPIO0
int lastButton = HIGH;
unsigned long lastDebounceTime = 0;
const unsigned long debounceDelay = 300;

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
//  TCP / CONEXIÓN
// ------------------------------
bool conectarServidor() {
  Serial.print("Conectando al servidor ");
  Serial.print(serverIP);
  Serial.print(":");
  Serial.println(serverPort);

  if (client.connect(serverIP, serverPort)) {
    Serial.println("✅ Conectado al servidor!");
    return true;
  } else {
    Serial.println("❌ No se pudo conectar.");
    return false;
  }
}

void asegurarConexion() {
  if (WiFi.status() != WL_CONNECTED) return;

  if (!client.connected()) {
    client.stop();
    conectarServidor();
  }
}

void enviarLinea(const String& line) {
  if (!client.connected()) return;
  client.print(line + "\n");
}


// ------------------------------
//  PARSEO SIMPLE DE JSON (campos fijos)
//  Funciona para: {"ID":1,"Temporada":"Invierno",...}
// ------------------------------
String extraerStringJSON(const String& json, const String& key) {
  // Busca "key":
  String needle = "\"" + key + "\"";
  int k = json.indexOf(needle);
  if (k < 0) return "";

  int colon = json.indexOf(':', k);
  if (colon < 0) return "";

  // Puede haber espacios, y luego comillas
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

  // Desde después de ':' hasta coma o '}'
  int start = colon + 1;
  while (start < (int)json.length() && (json[start] == ' ')) start++;

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
  while (start < (int)json.length() && (json[start] == ' ')) start++;

  int endComma = json.indexOf(',', start);
  int endBrace = json.indexOf('}', start);
  int end = (endComma >= 0) ? endComma : endBrace;
  if (end < 0) end = json.length();

  String num = json.substring(start, end);
  num.trim();
  num.replace(",", "."); // por si acaso
  return num.toFloat();
}

// ------------------------------
//  APLICAR CONFIGURACIÓN RECIBIDA
// ------------------------------
void aplicarSET(const String& json) {
  int id = extraerIntJSON(json, "ID");
  String temporada = extraerStringJSON(json, "Temporada");
  String tipo = extraerStringJSON(json, "Tipo");
  String ubicacion = extraerStringJSON(json, "Ubicacion");
  float precio = extraerFloatJSON(json, "Precio");

  // Guardar en la etiqueta
  etiqueta.id = id;
  etiqueta.temporada = temporada;
  etiqueta.tipo = tipo;
  etiqueta.ubicacion = ubicacion;
  etiqueta.precio = precio;
  etiqueta.configurada = (id >= 0 && temporada.length() > 0 && tipo.length() > 0 && ubicacion.length() > 0);

  Serial.println("\n✅ ETIQUETA CONFIGURADA:");
  Serial.print("ID: "); Serial.println(etiqueta.id);
  Serial.print("Temporada: "); Serial.println(etiqueta.temporada);
  Serial.print("Tipo: "); Serial.println(etiqueta.tipo);
  Serial.print("Ubicacion: "); Serial.println(etiqueta.ubicacion);
  Serial.print("Precio: "); Serial.println(etiqueta.precio, 2);

  // Confirmación al servidor
  if (etiqueta.configurada) {
    enviarLinea("ACK ID=" + String(etiqueta.id));
  } else {
    enviarLinea("NACK");
  }
}

bool resetEtiqueta() {
  etiqueta.configurada = false;
  etiqueta.id = -1;
  etiqueta.temporada = "";
  etiqueta.tipo = "";
  etiqueta.ubicacion = "";
  etiqueta.precio = 0.0f;
  return true; // ahora mismo siempre OK
}



// ------------------------------
//  PROCESAR LÍNEAS DEL SERVIDOR
// ------------------------------
void procesarLineaServidor(String line) {
  line.trim();
  if (line.length() == 0) return;

    // Ej: "PING 123456"
  if (line.startsWith("PING ")) {
    String rid = line.substring(5);
    rid.trim();
    responderPing(rid);
    return;
  }


  // Ej: "HELLO ESP32"
  if (line.startsWith("HELLO")) {
    Serial.print("📥 Respuesta: ");
    Serial.println(line);
    return;
  }

  // Ej: "OK"
  if (line == "OK") {
    // Puedes ignorarlo o imprimirlo
    // Serial.println("📥 OK");
    return;
  }

  // Ej: "SET {json}"
  if (line.startsWith("SET ")) {
    String json = line.substring(4);
    json.trim();
    aplicarSET(json);
    return;
  }

  // Si llega cualquier otra cosa:
  Serial.print("📥 Línea desconocida: ");
  Serial.println(line);
}

void leerServidor() {
  while (client.connected() && client.available()) {
    String line = client.readStringUntil('\n');
    procesarLineaServidor(line);
  }
}

void enviarEventoBoton() {
  // Si está vacía, no hay nada que mover/vender
  if (!etiqueta.configurada) {
    bool ok = resetEtiqueta();
    Serial.println("\n🧹 ETIQUETA YA ESTABA VACÍA");
    if (client.connected()) {
      enviarLinea("RESET OK IP=" + WiFi.localIP().toString());
    }
    return;
  }

  // 1) Si está en almacén -> pasa a tienda (MOVIMIENTO)
  if (etiqueta.ubicacion == "almacén") {
    String from = etiqueta.ubicacion;
    etiqueta.ubicacion = "tienda";

    // Payload JSON para el servidor
    String payload = "{";
    payload += "\"ID\":" + String(etiqueta.id) + ",";
    payload += "\"Temporada\":\"" + etiqueta.temporada + "\",";
    payload += "\"Tipo\":\"" + etiqueta.tipo + "\",";
    payload += "\"From\":\"" + from + "\",";
    payload += "\"To\":\"" + etiqueta.ubicacion + "\",";
    payload += "\"Precio\":" + String(etiqueta.precio, 2);
    payload += "}";

    Serial.println("\n📦 MOVIMIENTO: almacén -> tienda");
    if (client.connected()) {
      enviarLinea("MOVE " + payload);
    }
    return;
  }

  // 2) Si está en tienda -> vendido (VENTA)
  if (etiqueta.ubicacion == "tienda") {
    String payload = "{";
    payload += "\"ID\":" + String(etiqueta.id) + ",";
    payload += "\"Temporada\":\"" + etiqueta.temporada + "\",";
    payload += "\"Tipo\":\"" + etiqueta.tipo + "\",";
    payload += "\"Precio\":" + String(etiqueta.precio, 2);
    payload += "}";

    Serial.println("\n💰 VENTA: tienda -> vendido");
    if (client.connected()) {
      enviarLinea("SOLD " + payload);
    }

    // Tras vender: dejar la etiqueta vacía para reutilizarla
    resetEtiqueta();
    if (client.connected()) {
      enviarLinea("RESET OK AFTER_SALE IP=" + WiFi.localIP().toString());
    }
    return;
  }

  // Si por lo que sea llega otro valor inesperado
  Serial.println("\n⚠️ Ubicación desconocida. Reseteando por seguridad.");
  resetEtiqueta();
  if (client.connected()) {
    enviarLinea("RESET OK UNKNOWN_UBI IP=" + WiFi.localIP().toString());
  }
}



String etiquetaAJson() {
  // OJO: esto es JSON sencillo (sin escapar comillas dentro de strings, no hace falta con tus valores)
  String json = "{";
  json += "\"ID\":" + String(etiqueta.id) + ",";
  json += "\"Temporada\":\"" + etiqueta.temporada + "\",";
  json += "\"Tipo\":\"" + etiqueta.tipo + "\",";
  json += "\"Ubicacion\":\"" + etiqueta.ubicacion + "\",";
  // precio con 2 decimales
  json += "\"Precio\":" + String(etiqueta.precio, 2);
  json += "}";
  return json;
}

void responderPing(const String& rid) {
  if (!client.connected()) return;

  if (!etiqueta.configurada) {
    enviarLinea("PONG " + rid + " EMPTY");
  } else {
    enviarLinea(String("PONG ") + rid + " DATA " + etiquetaAJson());
  }
}


// ------------------------------
//  SETUP / LOOP
// ------------------------------
void setup() {
  Serial.begin(115200);
  delay(300);

  pinMode(buttonPin, INPUT_PULLUP);

  Serial.println("\nConectando a WiFi...");
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }

  Serial.println("\n✅ WiFi conectada.");
  Serial.print("IP asignada: ");
  Serial.println(WiFi.localIP());

  conectarServidor();

  // Estado inicial vacío
  Serial.println("Etiqueta inicial: VACÍA (sin configurar).");
}

void loop() {
  asegurarConexion();
  leerServidor();

  // Botón (si lo quieres mantener)
  int reading = digitalRead(buttonPin);
  unsigned long now = millis();

  if (reading == LOW && lastButton == HIGH && (now - lastDebounceTime > debounceDelay)) {
    enviarEventoBoton();
    lastDebounceTime = now;
  }
  lastButton = reading;
}
