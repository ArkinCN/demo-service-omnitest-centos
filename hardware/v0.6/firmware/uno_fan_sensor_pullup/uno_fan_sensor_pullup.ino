#include <Arduino.h>
#if !defined(__AVR_ATmega328P__) || F_CPU != 16000000L
#error This firmware requires UNO R3 ATmega328P at 16 MHz
#endif
// Timer1 Fast PWM, TOP=639: 16 MHz / (1 * 640) = 25 kHz on D9/OC1A.
uint8_t duty = 0;
char command[24];
uint8_t used = 0;
bool overflowed = false;
void applyDuty(uint8_t value) {
  uint8_t saved = SREG;
  cli();
  TCCR1A &= ~(_BV(COM1A1) | _BV(COM1A0));
  if (value == 0 || value == 100) {
    digitalWrite(9, value == 100 ? HIGH : LOW);
  } else {
    OCR1A = (640UL * value / 100) - 1;
    TCCR1A |= _BV(COM1A1);
  }
  duty = value;
  SREG = saved;
}
void processCommand() {
  command[used] = 0;
  if (strcmp(command, "STATUS") == 0) {
    Serial.print(F("OK DUTY ")); Serial.println(duty); return;
  }
  if (strncmp(command, "SET ", 4) != 0 || used <= 4) {
    Serial.println(F("ERR COMMAND")); return;
  }
  unsigned int value = 0;
  for (uint8_t i = 4; i < used; ++i) {
    if (command[i] < '0' || command[i] > '9') {
      Serial.println(F("ERR VALUE")); return;
    }
    value = value * 10 + command[i] - '0';
    if (value > 100) { Serial.println(F("ERR RANGE")); return; }
  }
  applyDuty(value);
  Serial.print(F("OK DUTY ")); Serial.println(duty);
}
// OPTIONAL ONLY: first verify sensor OUT is open collector and has no internal 12V pull-up.
// D2 provides a weak 5V pull-up; firmware does not count tach pulses or control RPM.
void setup() {
  pinMode(2, INPUT_PULLUP);
  digitalWrite(9, LOW); pinMode(9, OUTPUT);
  TCCR1A = _BV(WGM11);
  TCCR1B = _BV(WGM13) | _BV(WGM12) | _BV(CS10);
  ICR1 = 639; TCNT1 = 0; applyDuty(0);
  Serial.begin(115200);
  Serial.println(F("READY UNO_FAN_V2 25000"));
}
void loop() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\r') continue;
    if (ch == '\n') {
      if (overflowed) Serial.println(F("ERR LENGTH"));
      else if (used) processCommand();
      used = 0; overflowed = false;
    } else if (!overflowed) {
      if (used < sizeof(command)-1) command[used++] = ch;
      else overflowed = true;
    }
  }
}
