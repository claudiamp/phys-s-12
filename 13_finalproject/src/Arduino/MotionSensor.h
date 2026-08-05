#pragma once
#include <Arduino.h>

class MotionSensor {
  private:
    int _pin;
    bool _triggered;
    unsigned long _readyAt;
    unsigned long _warmupMs;

  public:
    MotionSensor(int pin, unsigned long warmupMs = 60000) {
      _pin = pin;
      _triggered = false;
      _readyAt = 0;
      _warmupMs = warmupMs;
    }

    void begin() {
      pinMode(_pin, INPUT);
      _readyAt = millis() + _warmupMs;
    }

    bool ready() const {
      return (long)(millis() - _readyAt) >= 0;
    }

    bool detected() {
      bool current = digitalRead(_pin) == HIGH;

      if (!ready()) {
        return false;
      }

      if (current && !_triggered) {
        _triggered = true;
        return true;
      }

      if (!current) {
        _triggered = false;
      }

      return false;
    }
};
