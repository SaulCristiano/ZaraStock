#include <Arduino.h>
#include <WiFi.h>
#include <SPI.h>
#include <Adafruit_PN532.h>

// ------- WIFI / SERVER -------
const char* ssid = "WifiR";
const char* password = "12345678";
const char* serverIP = "10.220.115.231";
const uint16_t serverPort = 5000;
WiFiClient client;

// ------- NFC -------
#define SDA_PIN 21
#define SCL_PIN 22
Adafruit_PN532 nfc(SDA_PIN, SCL_PIN);

// ROLE del lector: "CAJA" o "Puerta"
const char* NFC_ROLE = "CAJA";  // <--- CAMBIA ESTO EN EL OTRO ESP32

// --- Debounce NFC ---
static bool stablePresent = false;
static bool lastRawPresent = false;
static uint32_t lastChangeMs = 0;
const uint32_t DEBOUNCE_MS = 250;
const uint16_t POLL_TIMEOUT_MS = 50;

static uint8_t lastUid[7];
static uint8_t lastUidLen = 0;
static bool hasLastUid = false;

// --- Petición de lectura UID desde servidor ---
static bool waitingUid = false;
static String waitingRid = "";

// -------- Helpers TCP --------
void enviarLinea(const String& s) {
  if (client.connected()) client.print(s + "\n");
}

bool conectarServidor() {
  Serial.print("Conectando al servidor ");
  Serial.print(serverIP); Serial.print(":"); Serial.println(serverPort);
  if (client.connect(serverIP, serverPort)) {
    Serial.println("✅ Conectado!");
    // Anunciar rol
    enviarLinea(String("ROLE NFC ") + NFC_ROLE);
    return true;
  }
  Serial.println("❌ No conectado.");
  return false;
}

void asegurarConexion() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (!client.connected()) {
    client.stop();
    conectarServidor();
  }
}

// -------- Helpers NFC --------
bool sameUid(const uint8_t* a, uint8_t aLen, const uint8_t* b, uint8_t bLen) {
  if (aLen != bLen) return false;
  for (uint8_t i = 0; i < aLen; i++) if (a[i] != b[i]) return false;
  return true;
}

String uidToHex(const uint8_t* uid, uint8_t uidLength) {
  String out;
  for (uint8_t i = 0; i < uidLength; i++) {
    if (uid[i] < 0x10) out += "0";
    out += String(uid[i], HEX);
  }
  out.toUpperCase();
  return out;
}

// -------- Parse líneas servidor --------
void procesarLineaServidor(String line) {
  line.trim();
  if (!line.length()) return;

  // PING rid -> PONG rid NFC BOX
  if (line.startsWith("PING ")) {
    String rid = line.substring(5); rid.trim();
    enviarLinea(String("PONG ") + rid + " NFC " + NFC_ROLE);
    return;
  }

  // READUID rid -> activar modo "esperar próximo UID"
  if (line.startsWith("READUID ")) {
    waitingRid = line.substring(8);
    waitingRid.trim();
    waitingUid = true;
    Serial.print("📥 READUID recibido. Esperando tag... RID=");
    Serial.println(waitingRid);
    return;
  }

  // Mensajes varios
  Serial.print("📥 ");
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

  Serial.println("\nConectando a WiFi...");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.println("\n✅ WiFi conectada.");
  Serial.println(WiFi.localIP());

  conectarServidor();

  Serial.println("\nIniciando PN532 (I2C)...");
  nfc.begin();

  uint32_t versiondata = nfc.getFirmwareVersion();
  if (!versiondata) {
    Serial.println("No se encontró PN532. Revisa cableado.");
    while (true) delay(10);
  }
  nfc.SAMConfig();
  Serial.println("✅ PN532 listo.");
}

void loop() {
  asegurarConexion();
  leerServidor();

  uint8_t uid[7];
  uint8_t uidLength = 0;

  bool rawPresent = nfc.readPassiveTargetID(
    PN532_MIFARE_ISO14443A, uid, &uidLength, POLL_TIMEOUT_MS
  );

  uint32_t now = millis();
  if (rawPresent != lastRawPresent) {
    lastRawPresent = rawPresent;
    lastChangeMs = now;
  }

  if ((now - lastChangeMs) >= DEBOUNCE_MS && rawPresent != stablePresent) {
    stablePresent = rawPresent;

    // entrada
    if (stablePresent) {
      if (!hasLastUid || !sameUid(uid, uidLength, lastUid, lastUidLen)) {
        String hex = uidToHex(uid, uidLength);
        Serial.print("UID detectado: ");
        Serial.println(hex);

        memcpy(lastUid, uid, uidLength);
        lastUidLen = uidLength;
        hasLastUid = true;

        // Si el servidor lo pidió, contestar UNA vez
        if (waitingUid && client.connected()) {
          enviarLinea(String("UID ") + waitingRid + " " + hex);
          Serial.print("📤 Enviado UID al servidor. RID=");
          Serial.println(waitingRid);
          waitingUid = false;
          waitingRid = "";
        }
      }
    } else {
      hasLastUid = false;
      lastUidLen = 0;
    }
  }
}
