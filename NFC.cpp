#include <Arduino.h>
#include <SPI.h>
#include <Adafruit_PN532.h>

#define SDA_PIN 21
#define SCL_PIN 22

Adafruit_PN532 nfc(SDA_PIN, SCL_PIN);

// --- Debounce ---
static bool stablePresent = false;     // estado "confirmado" (debounced)
static bool lastRawPresent = false;    // última lectura cruda
static uint32_t lastChangeMs = 0;

const uint32_t DEBOUNCE_MS = 250;      // ajusta (200-500 suele ir bien)
const uint16_t POLL_TIMEOUT_MS = 50;   // lectura rápida, no bloqueante

// Para recordar el último UID leído (opcional, por si hay falsos flancos)
static uint8_t lastUid[7];
static uint8_t lastUidLen = 0;
static bool hasLastUid = false;

bool sameUid(const uint8_t* a, uint8_t aLen, const uint8_t* b, uint8_t bLen) {
  if (aLen != bLen) return false;
  for (uint8_t i = 0; i < aLen; i++) if (a[i] != b[i]) return false;
  return true;
}

void printUid(const uint8_t *uid, uint8_t uidLength) {
  Serial.print("UID: ");
  for (uint8_t i = 0; i < uidLength; i++) {
    if (uid[i] < 0x10) Serial.print("0"); // bonito: 0A en vez de A
    Serial.print(uid[i], HEX);
  }
  Serial.println();
}

void setup() {
  Serial.begin(115200);

  Serial.println("\nIniciando PN532 (I2C)...");
  nfc.begin();

  uint32_t versiondata = nfc.getFirmwareVersion();
  if (!versiondata) {
    Serial.println("No se encontró PN532. Revisa configuración y cableado.");
    while (true) { delay(10); }
  }

  nfc.SAMConfig();
  Serial.println("Listo. Acerca un tag NFC para leer su UID...");
}

void loop() {
  uint8_t uid[7];
  uint8_t uidLength = 0;

  // Lectura cruda: ¿hay tag ahora mismo?
  bool rawPresent = nfc.readPassiveTargetID(
    PN532_MIFARE_ISO14443A, uid, &uidLength, POLL_TIMEOUT_MS
  );

  // Detectar cambios crudos
  uint32_t now = millis();
  if (rawPresent != lastRawPresent) {
    lastRawPresent = rawPresent;
    lastChangeMs = now;
  }

  // Si el estado crudo se ha mantenido estable DEBOUNCE_MS, lo aceptamos
  if ((now - lastChangeMs) >= DEBOUNCE_MS && rawPresent != stablePresent) {
    stablePresent = rawPresent;

    // Flanco de entrada: ausente -> presente
    if (stablePresent) {
      // Aquí uid/uidLength vienen de la lectura cruda actual.
      // Opcional: evita duplicado si fuera el mismo UID por un “rebote” raro.
      if (!hasLastUid || !sameUid(uid, uidLength, lastUid, lastUidLen)) {
        printUid(uid, uidLength);
        memcpy(lastUid, uid, uidLength);
        lastUidLen = uidLength;
        hasLastUid = true;
      }
    }
    // Flanco de salida: presente -> ausente
else {
  // Al retirar el tag, “olvidamos” el último UID
  // para permitir que el mismo tag vuelva a disparar al acercarlo otra vez.
  hasLastUid = false;
  lastUidLen = 0;
}

  }

  // No delay bloqueante. Puedes hacer otras cosas aquí.
}
