#pragma once
#include <Arduino.h>

class PillBox {
  private:
    int _pin;
    bool _openLevel;
    bool _reading;      // raw last reading (for debounce timing)
    bool _state;        // debounced current state
    bool _lastState;    // debounced state on previous update
    unsigned long _lastDebounceTime;
    unsigned long _debounceDelay;

  public:
    PillBox(int pin, bool openLevel = HIGH, unsigned long debounceDelay = 50) {
      _pin = pin;
      _openLevel = openLevel;
      _debounceDelay = debounceDelay;
    }

    void begin() {
      pinMode(_pin, INPUT_PULLUP);
      _state = digitalRead(_pin);
      _lastState = _state;
      _reading = _state;
      _lastDebounceTime = millis();
    }

    void update() {
      bool r = digitalRead(_pin);
      if (r != _reading) {
        _reading = r;
        _lastDebounceTime = millis();
      }
      _lastState = _state;
      if (millis() - _lastDebounceTime > _debounceDelay) {
        _state = _reading;
      }
    }

    bool anyOpen()    { return _state == _openLevel; }                          // true WHILE open
    bool justOpened() { return _state == _openLevel && _lastState != _openLevel; } // true for ONE loop
    bool justClosed() { return _state != _openLevel && _lastState == _openLevel; }
};